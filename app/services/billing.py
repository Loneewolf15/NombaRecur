from datetime import datetime, timedelta
import logging
from sqlmodel import Session, select, func
from app.models.tenant import Tenant
from app.models.subscription import Subscription
from app.models.plan import Plan
from app.models.customer import Customer
from app.models.billing_attempt import BillingAttempt
from app.services.nomba import NombaClient, NombaAPIError
from app.services.email import send_dunning_email, send_payment_success_email, send_payment_failed_email
from app.config import settings

logger = logging.getLogger(__name__)

async def process_subscription_renewal(session: Session, subscription_id: str):
    """
    Core state machine for renewing a subscription. 
    Implements the 3-rail fallback logic.
    """
    # SQLite does not support SELECT FOR UPDATE; concurrency is guarded by the
    # pending-attempt check below (idempotency anchor).
    subscription = session.get(Subscription, subscription_id)
    if not subscription or subscription.status not in ("active", "past_due"):
        return

    plan = session.get(Plan, subscription.plan_id)
    customer = session.get(Customer, subscription.customer_id)
    tenant = session.get(Tenant, subscription.tenant_id)

    if not plan or not customer or not tenant:
        logger.error(f"Missing relations for subscription {subscription_id}")
        return

    nomba = NombaClient(tenant, session)

    # 1. Check if we already have a pending attempt. If so, don't overlap.
    stmt = select(BillingAttempt).where(
        BillingAttempt.subscription_id == subscription.id,
        BillingAttempt.status == "pending"
    )
    pending_attempt = session.exec(stmt).first()
    if pending_attempt:
        logger.info(f"Subscription {subscription_id} has pending attempt {pending_attempt.id}. Skipping.")
        return

    # Determine amount
    amount_kobo = plan.amount_kobo
    
    # -------------------------------------------------------------------------
    # RAIL 1: Tokenized Card (Preferred)
    # -------------------------------------------------------------------------
    if customer.nomba_token_key_enc:
        logger.info(f"Attempting Rail 1 (Card) for {subscription_id}")
        attempt = _create_billing_attempt(session, subscription, tenant, amount_kobo, "card")
        try:
            # We must pass the exact callback_url the tenant has configured
            callback_url = tenant.webhook_url or f"{settings.app_base_url}/v1/webhooks/nomba"
            
            # Note: Nomba tokenized card payment returns success immediately in sandbox for valid tokens, 
            # or triggers webhook? Docs say it returns {"status": True, "message": "Approved"}
            from app.utils.crypto import decrypt_val
            res = await nomba.charge_tokenized_card(
                token_key=decrypt_val(customer.nomba_token_key_enc),
                order_reference=attempt.merchant_tx_ref,
                amount_kobo=amount_kobo,
                customer_email=customer.email,
                customer_id=customer.external_id,
                callback_url=callback_url
            )
            
            # If successful synchronously (docs imply this for tokenized cards)
            status_val = res.get("status")
            if status_val == True or (isinstance(status_val, str) and status_val.lower() in ("success", "approved", "successful")):
                _mark_attempt_success(session, attempt, subscription, plan)
                return
            else:
                # Synchronous failure
                logger.warning(f"Rail 1 returned non-success status: {status_val}")
                _mark_attempt_failed(session, attempt, "FAILED", f"Status: {status_val}")
        except NombaAPIError as e:
            logger.warning(f"Rail 1 failed for {subscription_id}: {e}")
            _mark_attempt_failed(session, attempt, e.code, e.description)
        except Exception as e:
            logger.error(f"Rail 1 unexpected error for {subscription_id}: {e}")
            _mark_attempt_failed(session, attempt, "UNKNOWN", str(e))

    # -------------------------------------------------------------------------
    # RAIL 2: Direct Debit (Mandate)
    # -------------------------------------------------------------------------
    if customer.mandate_id and customer.mandate_status == "Active":
        logger.info(f"Attempting Rail 2 (Mandate) for {subscription_id}")
        attempt = _create_billing_attempt(session, subscription, tenant, amount_kobo, "mandate")
        try:
            res = await nomba.debit_mandate(
                mandate_id=customer.mandate_id,
                amount_kobo=amount_kobo
            )
            
            # Nomba returns a code 00 if the debit instruction was successful.
            code = res.get("code")
            status_msg = res.get("status")
            if isinstance(status_msg, str):
                status_msg = status_msg.lower()
                
            if code in ("00", "200") or status_msg == "success" or res.get("status") == True:
                _mark_attempt_success(session, attempt, subscription, plan)
                return
        except NombaAPIError as e:
            logger.warning(f"Rail 2 (Mandate) failed for {subscription_id}: {e}")
            _mark_attempt_failed(session, attempt, e.code, e.description)
        except Exception as e:
            logger.error(f"Rail 2 (Mandate) unexpected error for {subscription_id}: {e}")
            _mark_attempt_failed(session, attempt, "UNKNOWN", str(e))

    # -------------------------------------------------------------------------
    # RAIL 3: Virtual Account Dunning / Manual Checkout
    # Check if max retries exceeded — cancel instead of dunning indefinitely
    # -------------------------------------------------------------------------
    if subscription.retry_count >= plan.max_retries:
        logger.warning(f"Subscription {subscription_id} exceeded max retries ({plan.max_retries}). Canceling.")
        subscription.status = "canceled"
        subscription.canceled_at = datetime.utcnow()
        session.add(subscription)
        session.commit()
        # Notify the customer that their subscription has been canceled
        try:
            amount_naira = f"{plan.amount_kobo / 100:,.2f}"
            send_payment_failed_email(
                customer_email=customer.email,
                customer_name=customer.name,
                amount_naira=amount_naira,
                plan_name=plan.name,
            )
        except Exception as e:
            logger.warning(f"Failed to send cancellation email for subscription {subscription_id}: {e}")
        return

    logger.info(f"Attempting Rail 3 (Virtual Account Dunning) for {subscription_id}")
    subscription.status = "past_due"
    session.add(subscription)
    session.commit()

    attempt = _create_billing_attempt(session, subscription, tenant, amount_kobo, "checkout_dunning")
    try:
        callback_url = tenant.webhook_url or f"{settings.app_base_url}/v1/webhooks/nomba"
        res = await nomba.create_checkout_order(
            order_reference=attempt.merchant_tx_ref,
            amount_kobo=amount_kobo,
            customer_email=customer.email,
            customer_id=customer.external_id,
            callback_url=callback_url,
            tokenize_card=True # Give them a chance to save a new card!
        )
        
        checkout_link = res.get("checkoutLink")
        subscription.pending_checkout_order_ref = attempt.merchant_tx_ref
        session.add(subscription)
        session.commit()
        
        # Notify the customer to complete payment manually
        amount_naira = f"{amount_kobo / 100:,.2f}"
        send_dunning_email(
            customer_email=customer.email,
            customer_name=customer.name,
            checkout_link=checkout_link,
            amount_naira=amount_naira,
            plan_name=plan.name,
        )
        logger.info(f"Generated dunning checkout link for {subscription_id}: {checkout_link}")
        
        # We leave the attempt as "pending" until the webhook fires!
        return
        
    except NombaAPIError as e:
        logger.warning(f"Rail 3 failed for {subscription_id}: {e}")
        _mark_attempt_failed(session, attempt, e.code, e.description)
    except Exception as e:
        logger.error(f"Rail 3 unexpected error for {subscription_id}: {e}")
        _mark_attempt_failed(session, attempt, "UNKNOWN", str(e))


def _create_billing_attempt(session: Session, subscription: Subscription, tenant: Tenant, amount_kobo: int, rail: str) -> BillingAttempt:
    period_start_str = subscription.current_period_start.strftime("%Y%m%d")
    short_id = subscription.id[:8]
    prefix = f"nr_{short_id}_{period_start_str}_"

    # Count how many attempts already exist for this period to avoid collisions
    # when retry_count has been reset by a prior successful _mark_attempt_success.
    existing_count = session.exec(
        select(func.count(BillingAttempt.id)).where(
            BillingAttempt.subscription_id == subscription.id,
            BillingAttempt.merchant_tx_ref.startswith(prefix)
        )
    ).one()
    attempt_num = existing_count + 1

    merchant_tx_ref = f"{prefix}{attempt_num}"
    
    attempt = BillingAttempt(
        subscription_id=subscription.id,
        tenant_id=tenant.id,
        amount_kobo=amount_kobo,
        rail=rail,
        merchant_tx_ref=merchant_tx_ref
    )
    session.add(attempt)
    
    subscription.retry_count += 1
    session.add(subscription)
    
    session.commit()
    session.refresh(attempt)
    return attempt

def _mark_attempt_success(session: Session, attempt: BillingAttempt, subscription: Subscription, plan: Plan):
    attempt.status = "success"
    attempt.completed_at = datetime.utcnow()
    session.add(attempt)

    subscription.status = "active"
    subscription.retry_count = 0
    subscription.current_period_start = datetime.utcnow()

    # Calculate next billing
    if plan.interval == "monthly":
        subscription.current_period_end = subscription.current_period_start + timedelta(days=30)
    elif plan.interval == "yearly":
        subscription.current_period_end = subscription.current_period_start + timedelta(days=365)
    elif plan.interval == "weekly":
        subscription.current_period_end = subscription.current_period_start + timedelta(days=7)
    elif plan.interval == "daily":
        subscription.current_period_end = subscription.current_period_start + timedelta(days=1)
    elif plan.interval == "1_minute":
        subscription.current_period_end = subscription.current_period_start + timedelta(minutes=1)
    elif plan.interval == "4_minutes":
        subscription.current_period_end = subscription.current_period_start + timedelta(minutes=4)
    elif plan.interval == "5_minutes":
        subscription.current_period_end = subscription.current_period_start + timedelta(minutes=5)
    else:
        # fallback
        subscription.current_period_end = subscription.current_period_start + timedelta(days=30)

    subscription.next_billing_at = subscription.current_period_end
    session.add(subscription)

    session.commit()
    logger.info(f"Subscription {subscription.id} renewed successfully.")

    # Send payment confirmation to the customer.
    # This is the single source of truth for "payment succeeded" — covers Rail 1
    # (card token), Rail 2 (direct debit), scheduler reconciliation, and webhook
    # paths alike. The webhook handler previously did this itself; it will now hit
    # the idempotency guard (attempt.status == "success" already set) before it
    # can call _mark_attempt_success a second time, so no duplicate emails.
    try:
        customer = session.get(Customer, subscription.customer_id)
        if customer:
            amount_naira = f"{attempt.amount_kobo / 100:,.2f}"
            next_billing_date = subscription.next_billing_at.strftime("%d %b %Y")
            send_payment_success_email(
                customer_email=customer.email,
                customer_name=customer.name,
                amount_naira=amount_naira,
                plan_name=plan.name,
                next_billing_date=next_billing_date,
            )
    except Exception as e:
        # Never let an email failure roll back a successful payment
        logger.warning(f"Failed to send payment success email for subscription {subscription.id}: {e}")

def _mark_attempt_failed(session: Session, attempt: BillingAttempt, code: str, msg: str):
    attempt.status = "failed"
    attempt.error_code = code
    attempt.error_message = msg
    attempt.completed_at = datetime.utcnow()
    session.add(attempt)
    session.commit()
