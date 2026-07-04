import logging
from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func
from datetime import datetime

logger = logging.getLogger(__name__)

from app.database import get_session
from app.models.tenant import Tenant
from app.dependencies import get_current_tenant
from app.models.subscription import Subscription
from app.models.billing_attempt import BillingAttempt
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class DashboardQuery(BaseModel):
    limit: int = 10
    status: Optional[str] = None

@router.api_route("/search", methods=["POST", "QUERY"])
def search_billing_attempts(query: DashboardQuery, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """Filter billing attempts by status."""
    stmt = (
        select(BillingAttempt)
        .where(BillingAttempt.tenant_id == tenant.id)
        .order_by(BillingAttempt.attempted_at.desc())
        .limit(query.limit)
    )
    if query.status:
        stmt = stmt.where(BillingAttempt.status == query.status)
    attempts = session.exec(stmt).all()
    return [
        {
            "id": a.id,
            "merchant_tx_ref": a.merchant_tx_ref,
            "amount_kobo": a.amount_kobo,
            "rail": a.rail,
            "status": a.status,
            "created_at": a.attempted_at.isoformat(),
            "error_message": a.error_message
        }
        for a in attempts
    ]

@router.api_route("/", methods=["GET", "QUERY"])
def get_dashboard_stats(query_params: DashboardQuery = None, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    limit = query_params.limit if query_params else 5

    # Active Subscriptions Count
    active_subs = session.exec(
        select(func.count(Subscription.id))
        .where(Subscription.tenant_id == tenant.id)
        .where(Subscription.status.in_(["active", "past_due"]))
    ).one()

    # Pending Renewals Count (Subscriptions that are due or will be due within 24 hours)
    now = datetime.utcnow()
    pending_renewals = session.exec(
        select(func.count(Subscription.id))
        .where(Subscription.tenant_id == tenant.id)
        .where(Subscription.status.in_(["active", "past_due"]))
        .where(Subscription.next_billing_at <= now)
    ).one()

    # Total Revenue (Sum of all successful billing attempts in kobo -> NGN)
    revenue_kobo = session.exec(
        select(func.sum(BillingAttempt.amount_kobo))
        .where(BillingAttempt.tenant_id == tenant.id)
        .where(BillingAttempt.status == "success")
    ).one()
    total_revenue_ngn = (revenue_kobo or 0) / 100.0

    # Recent Billing Attempts (Immutable Log)
    recent_attempts = session.exec(
        select(BillingAttempt)
        .where(BillingAttempt.tenant_id == tenant.id)
        .order_by(BillingAttempt.attempted_at.desc())
        .limit(10)
    ).all()

    attempts_data = [
        {
            "id": a.id,
            "merchant_tx_ref": a.merchant_tx_ref,
            "amount_kobo": a.amount_kobo,
            "rail": a.rail,
            "status": a.status,
            "created_at": a.attempted_at.isoformat(),
            "error_message": a.error_message
        }
        for a in recent_attempts
    ]

    return {
        "active_subscriptions": active_subs,
        "total_revenue_ngn": total_revenue_ngn,
        "pending_renewals": pending_renewals,
        "recent_attempts": attempts_data
    }

@router.get("/analytics")
def get_dashboard_analytics(session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """Fetch aggregated analytics for charting."""
    # Rail breakdown
    rail_counts = {
        "card_initial": session.exec(select(func.count(BillingAttempt.id)).where(BillingAttempt.tenant_id == tenant.id, BillingAttempt.rail == "card_initial", BillingAttempt.status == "success")).first() or 0,
        "card_recurring": session.exec(select(func.count(BillingAttempt.id)).where(BillingAttempt.tenant_id == tenant.id, BillingAttempt.rail == "card_recurring", BillingAttempt.status == "success")).first() or 0,
        "direct_debit": session.exec(select(func.count(BillingAttempt.id)).where(BillingAttempt.tenant_id == tenant.id, BillingAttempt.rail == "direct_debit", BillingAttempt.status == "success")).first() or 0,
        "virtual_account": session.exec(select(func.count(BillingAttempt.id)).where(BillingAttempt.tenant_id == tenant.id, BillingAttempt.rail == "virtual_account", BillingAttempt.status == "success")).first() or 0,
    }

    # Simplistic revenue trend: last 7 attempts as proxies for time
    attempts = session.exec(
        select(BillingAttempt)
        .where(BillingAttempt.tenant_id == tenant.id, BillingAttempt.status == "success")
        .order_by(BillingAttempt.attempted_at.desc())
        .limit(10)
    ).all()
    
    attempts.reverse() # chronological
    
    revenue_trend = []
    labels = []
    for a in attempts:
        revenue_trend.append(a.amount_kobo / 100)
        labels.append(a.attempted_at.strftime("%H:%M"))
        
    # If no data, provide empty structure for Chart.js
    if not labels:
        labels = ["No Data"]
        revenue_trend = [0]
        
    return {
        "rail_breakdown": rail_counts,
        "revenue_trend": {
            "labels": labels,
            "data": revenue_trend
        }
    }

@router.post("/trigger-billing")
async def trigger_billing_now(session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """
    Manually fire the billing cycle for this tenant's due subscriptions right now.
    Demo helper — don't wait 5 minutes for the scheduler.
    """
    from app.services.scheduler import run_billing_cycle
    processed = await run_billing_cycle(tenant_id=tenant.id)
    return {"message": "Billing cycle triggered", "subscriptions_processed": processed}

@router.post("/reconcile-pending")
async def reconcile_pending_attempts(session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """
    Hackathon helper: Manually trigger reconciliation for all pending billing attempts 
    for this tenant, bypassing the 30-minute wait time.
    """
    from app.services.nomba import NombaClient
    from app.models.plan import Plan
    from app.services.billing import _mark_attempt_success
    
    stmt = select(BillingAttempt).where(
        BillingAttempt.tenant_id == tenant.id,
        BillingAttempt.status == "pending"
    )
    pending_attempts = session.exec(stmt).all()
    
    results = {"success": 0, "failed": 0, "errors": 0}
    
    nomba = NombaClient(tenant, session)
    for attempt in pending_attempts:
        try:
            res = await nomba.fetch_transaction_status(attempt.merchant_tx_ref)

            status_msg = res.get("status", "").lower()
            response_code = res.get("responseCode", "")

            # Nomba signals success via event_type=payment_success; on the status
            # endpoint responseCode "00" or status "success"/"completed" means paid.
            # Empty responseCode on sandbox is normal for a completed payment.
            is_success = (
                response_code in ("00", "200")
                or status_msg in ("success", "completed", "successful")
            )

            if is_success:
                subscription = session.get(Subscription, attempt.subscription_id)
                plan = session.get(Plan, subscription.plan_id)
                _mark_attempt_success(session, attempt, subscription, plan)
                results["success"] += 1
            else:
                # Nomba confirmed the payment is not yet successful — mark failed
                attempt.status = "failed"
                attempt.error_code = response_code or "NOT_PAID"
                attempt.error_message = f"Reconciled: status={status_msg}, code={response_code}"
                attempt.completed_at = datetime.utcnow()
                session.add(attempt)
                results["failed"] += 1
            session.commit()

        except Exception as e:
            # API lookup itself failed (network, wrong path, etc.)
            # DO NOT mark the attempt failed — leave it pending so it can be retried.
            logger.error(f"Reconcile lookup error for {attempt.merchant_tx_ref}: {e}")
            results["errors"] += 1

    return {"message": "Manual reconciliation complete", "details": results, "total_processed": len(pending_attempts)}
