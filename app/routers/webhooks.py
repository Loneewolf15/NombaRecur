from fastapi import APIRouter, Request, HTTPException, Depends
from sqlmodel import Session, select
import hmac
import hashlib
import base64
import json
import logging
from datetime import datetime

from app.database import get_session
from app.config import settings
from app.models.billing_attempt import BillingAttempt
from app.models.subscription import Subscription
from app.models.plan import Plan
from app.services.billing import _mark_attempt_success

logger = logging.getLogger(__name__)

router = APIRouter()

def verify_nomba_signature(payload: bytes, signature: str, time_stamp: str) -> bool:
    """
    Verifies the HMAC-SHA256 signature from Nomba.
    Uses the officially documented base64_encode(hash) logic.
    """
    if not signature or not time_stamp:
        return False
        
    try:
        # Parse the JSON payload to reconstruct the hashing string exactly as Nomba does
        data_json = json.loads(payload.decode('utf-8'))
        
        event_type = data_json.get("event_type", "")
        request_id = data_json.get("requestId", "")
        
        data_obj = data_json.get("data", {})
        merchant = data_obj.get("merchant", {})
        transaction = data_obj.get("transaction", {})
        
        user_id = merchant.get("userId", "")
        wallet_id = merchant.get("walletId", "")
        
        transaction_id = transaction.get("transactionId", "")
        transaction_type = transaction.get("type", "")
        transaction_time = transaction.get("time", "")
        response_code = transaction.get("responseCode", "")
        
        if response_code == "null" or response_code is None:
            response_code = ""
            
        hashing_payload = f"{event_type}:{request_id}:{user_id}:{wallet_id}:{transaction_id}:{transaction_type}:{transaction_time}:{response_code}:{time_stamp}"

        logger.debug(f"Reconstructed webhook hash payload: {hashing_payload}")
        
        # Calculate HMAC SHA256 bytes
        digest_bytes = hmac.new(
            settings.nomba_webhook_secret.encode('utf-8'),
            hashing_payload.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        # Base64 encode the bytes
        computed_sig = base64.b64encode(digest_bytes).decode('utf-8')
        
        return hmac.compare_digest(signature, computed_sig)
    except Exception as e:
        logger.error(f"Error validating webhook signature: {e}")
        return False

from fastapi.responses import HTMLResponse
from app.models.tenant import Tenant
from app.services.nomba import NombaClient

@router.get("/nomba", response_class=HTMLResponse)
async def nomba_callback_get(orderId: str = None, orderReference: str = None, session: Session = Depends(get_session)):
    """
    Handle the browser redirect from Nomba after a successful checkout.
    Since webhooks require global configuration in the Nomba Dashboard, 
    we synchronously verify the transaction here as a robust fallback.
    """
    message = "Payment Successful!"
    detail = "Your subscription is now active. You may close this window or return to the dashboard."

    if orderReference:
        attempt = session.exec(select(BillingAttempt).where(BillingAttempt.merchant_tx_ref == orderReference)).first()
        if attempt and attempt.status != "success":
            tenant = session.get(Tenant, attempt.tenant_id)
            if tenant:
                try:
                    nomba = NombaClient(tenant, session)
                    txn_data = await nomba.fetch_transaction_status(orderReference)
                    
                    # Synthesize the webhook data structure so we can reuse our logic
                    txn_data["merchantTxRef"] = orderReference
                    
                    # Ensure tokenKey can be found if it's returned by fetch_transaction_status
                    tokenized_data = txn_data.get("tokenizedCardData") or txn_data.get("tokenizedCard") or {}
                    if not tokenized_data and "tokenKey" in txn_data:
                        tokenized_data = {"tokenKey": txn_data.get("tokenKey")}
                        
                    webhook_data = {
                        "data": {
                            "transaction": txn_data,
                            "tokenizedCardData": tokenized_data
                        }
                    }
                    await _handle_payment_success(webhook_data, session)
                    logger.info(f"Synchronously verified and completed attempt {orderReference}")
                except Exception as e:
                    logger.error(f"Error synchronously verifying transaction {orderReference}: {e}")
                    message = "Payment Pending Verification"
                    detail = "We are still waiting for confirmation from the bank. Please check your email later."

    return f"""
    <html>
        <head><title>{message}</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1 style="color: #10b981;">{message}</h1>
            <p>{detail}</p>
        </body>
    </html>
    """

@router.post("/nomba")
async def nomba_webhook(request: Request, session: Session = Depends(get_session)):
    """
    Endpoint to receive webhooks from Nomba.
    Must return 200 fast to avoid the 5x retry policy.
    """
    # 1. Get raw body and headers
    payload = await request.body()
    signature = request.headers.get("nomba-signature")
    time_stamp = request.headers.get("nomba-timestamp")
    
    # 2. Verify Signature
    if not verify_nomba_signature(payload, signature, time_stamp):
        logger.warning(f"Invalid webhook signature received. Sig: {signature}")
        # In a real app we might return 400, but returning 200 stops Nomba from retrying bad payloads
        return {"status": "ignored", "reason": "invalid_signature"}
        
    try:
        data = json.loads(payload.decode('utf-8'))
    except json.JSONDecodeError:
        return {"status": "error", "reason": "invalid_json"}
        
    event_type = data.get("event_type")
    logger.info(f"Received Nomba webhook: {event_type}")

    if event_type == "payment_success":
        await _handle_payment_success(data, session)
    elif event_type in ("bank_transfer", "virtual_account_credit", "transfer_successful"):
        await _handle_va_credit(data, session)

    return {"status": "success"}

async def _handle_payment_success(data: dict, session: Session):
    """
    Process a successful payment (either Card or Virtual Account transfer).
    Matches it back to our BillingAttempt using merchantTxRef.
    """
    transaction = data.get("data", {}).get("transaction", {})
    # For checkout, the merchant tx ref is usually in the order object or transaction object
    # In sandbox checkout webhook, it's often transaction.merchantTxRef
    merchant_tx_ref = transaction.get("merchantTxRef")
    
    if not merchant_tx_ref:
        # Might be in order object
        order = data.get("data", {}).get("order", {})
        merchant_tx_ref = order.get("orderReference")
        
    if not merchant_tx_ref:
        logger.warning("No merchantTxRef found in payment_success webhook.")
        return
        
    logger.info(f"Processing payment_success for ref: {merchant_tx_ref}")
    
    # Find the billing attempt
    stmt = select(BillingAttempt).where(BillingAttempt.merchant_tx_ref == merchant_tx_ref)
    attempt = session.exec(stmt).first()
    
    if not attempt:
        logger.warning(f"No billing attempt found for ref {merchant_tx_ref}")
        return
        
    if attempt.status == "success":
        logger.info(f"Attempt {merchant_tx_ref} already marked as success. Idempotent hit.")
        return
        
    # Mark it successful
    subscription = session.get(Subscription, attempt.subscription_id)
    plan = session.get(Plan, subscription.plan_id)
    
    if subscription and plan:
        # event_type == "payment_success" is itself the success signal.
        # responseCode is empty string "" in real Nomba payloads for successful checkout —
        # do NOT gate success on responseCode == "00".
        _mark_attempt_success(session, attempt, subscription, plan)

        attempt.nomba_transaction_id = transaction.get("transactionId")
        attempt.nomba_request_id = data.get("requestId")
        session.add(attempt)
        
        # Real Nomba webhook puts tokenKey at data.tokenizedCardData.tokenKey
        # (confirmed from live payload — NOT inside transaction)
        tokenized_card_data = data.get("data", {}).get("tokenizedCardData", {})
        token_key = tokenized_card_data.get("tokenKey")
        # Fallbacks for older/alternate payload shapes
        if not token_key:
            token_key = transaction.get("tokenizedCard", {}).get("tokenKey")
        if not token_key:
            token_key = transaction.get("tokenKey")
            
        if token_key:
            from app.models.customer import Customer
            from app.utils.crypto import encrypt_val
            customer = session.get(Customer, subscription.customer_id)
            if customer:
                customer.nomba_token_key_enc = encrypt_val(token_key)
                session.add(customer)
                logger.info(f"Saved new tokenized card for customer {customer.id}")
                
                # Check for Verve card which requires per-transaction OTP
                card_type = tokenized_card_data.get("cardType", "")
                if not card_type:
                    card_type = transaction.get("cardIssuer", "")
                    
                if card_type.lower() == "verve":
                    logger.warning(f"Verve card enrolled for {customer.id}. Tagging subscription {subscription.id} as active_manual_only.")
                    subscription.status = "active_manual_only"
                    session.add(subscription)
                
        session.commit()
        logger.info(f"Successfully processed webhook for subscription {subscription.id}")
        # Success email is now sent inside _mark_attempt_success, so no duplicate call here.
    else:
        logger.error(f"Missing subscription or plan for attempt {attempt.id}")


async def _handle_va_credit(data: dict, session: Session):
    """
    Handle an incoming bank transfer to a customer's dedicated Virtual Account.
    Matches the destination account number to a customer and auto-renews their
    active subscription — no checkout link required.
    """
    from app.models.customer import Customer
    from app.models.plan import Plan
    from app.models.billing_attempt import BillingAttempt
    from app.services.billing import _create_billing_attempt, _mark_attempt_success

    transaction = data.get("data", {}).get("transaction", {})
    destination_account = transaction.get("destinationAccount") or transaction.get("accountNumber")
    amount_naira = transaction.get("amount")

    if not destination_account:
        logger.warning("VA credit webhook missing destination account number")
        return

    # Find the customer who owns this VA
    customer = session.exec(
        select(Customer).where(Customer.va_account_number == destination_account)
    ).first()

    if not customer:
        logger.warning(f"No customer found for VA account {destination_account}")
        return

    # Find their active or past_due subscription
    subscription = session.exec(
        select(Subscription).where(
            Subscription.customer_id == customer.id,
            Subscription.status.in_(["active", "past_due", "trialing"])
        )
    ).first()

    if not subscription:
        logger.warning(f"No active subscription for customer {customer.id} on VA credit")
        return

    plan = session.get(Plan, subscription.plan_id)
    tenant = session.get(Tenant, subscription.tenant_id)

    if not plan or not tenant:
        return

    # Convert amount to kobo for comparison
    try:
        paid_kobo = int(float(amount_naira) * 100)
    except (TypeError, ValueError):
        paid_kobo = 0

    if paid_kobo < plan.amount_kobo:
        logger.warning(
            f"VA credit of ₦{amount_naira} insufficient for plan {plan.name} "
            f"(₦{plan.amount_kobo / 100:.2f}). Ignoring."
        )
        return

    # Create a billing attempt record for this VA payment
    attempt = _create_billing_attempt(session, subscription, tenant, plan.amount_kobo, "virtual_account")
    attempt.nomba_transaction_id = transaction.get("transactionId")
    attempt.nomba_request_id = data.get("requestId")
    session.add(attempt)
    session.commit()

    _mark_attempt_success(session, attempt, subscription, plan)
    # Success email is sent inside _mark_attempt_success.
    logger.info(f"VA credit auto-renewed subscription {subscription.id} for customer {customer.id}")
