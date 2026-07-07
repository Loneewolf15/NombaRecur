import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import select

from app.database import engine, Session
from app.models.subscription import Subscription
from app.models.billing_attempt import BillingAttempt
from app.services.billing import process_subscription_renewal

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def run_billing_cycle(tenant_id: str = None):
    """
    Finds all active/past_due subscriptions that are due for renewal and processes them.
    If tenant_id is provided, only processes that tenant's subscriptions (for manual triggers).
    """
    logger.info(f"Running billing cycle{' for tenant ' + tenant_id if tenant_id else ''}...")
    now = datetime.utcnow()

    with Session(engine) as session:
        stmt = select(Subscription).where(
            Subscription.status.in_(["active", "past_due"]),
            Subscription.next_billing_at <= now
        )
        if tenant_id:
            stmt = stmt.where(Subscription.tenant_id == tenant_id)
        due_subscriptions = session.exec(stmt).all()

        processed = 0
        for sub in due_subscriptions:
            try:
                await process_subscription_renewal(session, sub.id)
                processed += 1
            except Exception as e:
                logger.error(f"Error processing subscription {sub.id}: {e}")
                # Roll back any failed transaction so the session stays usable
                # for the next subscription in the loop.
                try:
                    session.rollback()
                except Exception:
                    pass
        return processed

async def run_crash_recovery():
    """
    Finds BillingAttempts that have been pending for > 30 minutes.
    This usually means the server crashed before the webhook arrived, or Nomba never sent it.
    We need to query Nomba to find out what happened.
    """
    logger.info("Running crash recovery for pending billing attempts...")
    thirty_mins_ago = datetime.utcnow() - timedelta(minutes=30)
    
    with Session(engine) as session:
        stmt = select(BillingAttempt).where(
            BillingAttempt.status == "pending",
            BillingAttempt.attempted_at <= thirty_mins_ago
        )
        stuck_attempts = session.exec(stmt).all()
        
        for attempt in stuck_attempts:
            try:
                # We need the tenant to initialize NombaClient
                from app.models.tenant import Tenant
                from app.services.nomba import NombaClient
                from app.models.plan import Plan
                from app.services.billing import _mark_attempt_success
                
                subscription = session.get(Subscription, attempt.subscription_id)
                tenant = session.get(Tenant, attempt.tenant_id)
                nomba = NombaClient(tenant, session)
                
                res = await nomba.fetch_transaction_status(attempt.merchant_tx_ref)
                
                # Check status: 2 = success, 3 = failed in Sandbox (per common conventions, we'll check message/status)
                status_msg = res.get("status", "").lower()
                response_code = res.get("responseCode")
                
                if response_code in ("00", "200") or status_msg == "success":
                    logger.info(f"Reconciliation SUCCESS for {attempt.merchant_tx_ref}")
                    plan = session.get(Plan, subscription.plan_id)
                    _mark_attempt_success(session, attempt, subscription, plan)
                else:
                    logger.info(f"Reconciliation FAILED for {attempt.merchant_tx_ref}: {status_msg}")
                    attempt.status = "failed"
                    attempt.error_code = response_code
                    attempt.error_message = f"Reconciled as failed: {status_msg}"
                    attempt.completed_at = datetime.utcnow()
                    session.add(attempt)
                session.commit()
            
            except Exception as e:
                from app.services.nomba import NombaAPIError
                if isinstance(e, NombaAPIError) and e.code == "400" and "Error fetching checkout transaction" in str(e):
                    # Live environment returning 400 instead of 200 with success:false
                    logger.warning(f"Scheduler reconcile: Nomba returned 400 for {attempt.merchant_tx_ref}, keeping pending.")
                else:
                    logger.error(f"Reconciliation query failed for {attempt.merchant_tx_ref}: {e}")
                    attempt.status = "failed"
                    attempt.error_code = "TIMEOUT"
                    attempt.error_message = f"Webhook missed, reconciliation API failed: {e}"
                    attempt.completed_at = datetime.utcnow()
                    session.add(attempt)
                    session.commit()

def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            run_billing_cycle,
            trigger=IntervalTrigger(minutes=5),  # Check every 5 minutes for due subscriptions
            id="billing_cycle",
            name="Run recurring billing loop",
            replace_existing=True,
        )
        
        scheduler.add_job(
            run_crash_recovery,
            trigger=IntervalTrigger(minutes=15), # Check every 15 minutes for stuck attempts
            id="crash_recovery",
            name="Recover pending billing attempts",
            replace_existing=True,
        )
        
        scheduler.start()
        logger.info("APScheduler started.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler shutdown.")
