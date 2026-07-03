from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from datetime import datetime, timedelta
import uuid

from app.database import get_session
from app.models.tenant import Tenant
from app.models.customer import Customer
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.billing_attempt import BillingAttempt
from app.dependencies import get_current_tenant
from app.services.nomba import NombaClient

router = APIRouter()

@router.get("/")
def list_subscriptions(status: str = None, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """List all subscriptions for the current tenant, optionally filtered by status."""
    stmt = select(Subscription).where(Subscription.tenant_id == tenant.id)
    if status:
        stmt = stmt.where(Subscription.status == status)
    return session.exec(stmt).all()

@router.get("/{subscription_id}")
def get_subscription(subscription_id: str, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """Get a single subscription by ID."""
    from fastapi import HTTPException
    sub = session.get(Subscription, subscription_id)
    if not sub or sub.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return sub

class SubscriptionCreate(BaseModel):
    customer_id: str
    plan_id: str
    callback_url: str

@router.post("/")
async def create_subscription(data: SubscriptionCreate, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """
    Subscribe a customer to a plan.
    Returns a checkout URL. The customer MUST complete this checkout to activate the subscription
    and tokenize their card for future recurring billing.
    """
    customer = session.get(Customer, data.customer_id)
    plan = session.get(Plan, data.plan_id)
    
    if not customer or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not plan or plan.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Plan not found")
        
    # Create subscription in trialing/pending state
    now = datetime.utcnow()
    sub = Subscription(
        tenant_id=tenant.id,
        customer_id=customer.id,
        plan_id=plan.id,
        status="trialing",
        current_period_start=now,
        current_period_end=now, # Will be extended upon payment success
        next_billing_at=now
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    
    # Generate the initial checkout order
    # We use a BillingAttempt to track this initial payment too
    attempt_ref = f"nr_init_{sub.id[:8]}_{int(now.timestamp())}"
    attempt = BillingAttempt(
        subscription_id=sub.id,
        tenant_id=tenant.id,
        amount_kobo=plan.amount_kobo,
        rail="card_initial",
        merchant_tx_ref=attempt_ref
    )
    session.add(attempt)
    session.commit()
    
    nomba = NombaClient(tenant, session)
    try:
        res = await nomba.create_checkout_order(
            order_reference=attempt_ref,
            amount_kobo=plan.amount_kobo,
            customer_email=customer.email,
            customer_id=customer.external_id,
            callback_url=data.callback_url,
            tokenize_card=True # CRITICAL for recurring!
        )
        return {
            "subscription_id": sub.id,
            "status": sub.status,
            "checkout_link": res.get("checkoutLink"),
            "message": "Direct the customer to this checkout link to activate the subscription."
        }
    except Exception as e:
        # Rollback or mark failed
        attempt.status = "failed"
        attempt.error_message = str(e)
        session.add(attempt)
        session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to generate checkout link: {e}")

@router.post("/{subscription_id}/cancel")
def cancel_subscription(subscription_id: str, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """Cancel an active subscription. It will not renew at the end of the current billing cycle."""
    sub = session.get(Subscription, subscription_id)
    if not sub or sub.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Subscription not found")
        
    if sub.status == "canceled":
        return {"message": "Subscription is already canceled", "status": sub.status}
        
    sub.status = "canceled"
    sub.canceled_at = datetime.utcnow()
    session.add(sub)
    session.commit()
    
    return {"message": "Subscription canceled successfully", "status": sub.status, "canceled_at": sub.canceled_at}
