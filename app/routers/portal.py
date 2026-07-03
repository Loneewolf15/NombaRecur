from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime

from app.database import get_session
from app.models.customer import Customer
from app.models.subscription import Subscription
from app.models.plan import Plan
from app.models.tenant import Tenant

router = APIRouter()

@router.get("/subscriptions")
def get_customer_subscriptions(email: str, session: Session = Depends(get_session)):
    """Fetch all subscriptions for a customer by email across all tenants (for hackathon demo)."""
    # 1. Find all customers with this email
    customers = session.exec(select(Customer).where(Customer.email == email)).all()
    if not customers:
        return []

    customer_ids = [c.id for c in customers]
    
    # 2. Find subscriptions
    subs = session.exec(select(Subscription).where(Subscription.customer_id.in_(customer_ids))).all()
    
    res = []
    for s in subs:
        plan = session.get(Plan, s.plan_id)
        tenant = session.get(Tenant, s.tenant_id)
        res.append({
            "id": s.id,
            "tenant_name": tenant.name if tenant else "Unknown Business",
            "plan_name": plan.name if plan else "Unknown Plan",
            "amount_kobo": plan.amount_kobo if plan else 0,
            "status": s.status,
            "next_billing_at": s.next_billing_at.isoformat()
        })
    return res

@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(subscription_id: str, email: str, session: Session = Depends(get_session)):
    """Cancel a subscription from the portal."""
    sub = session.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
        
    # Verify the email matches
    customer = session.get(Customer, sub.customer_id)
    if not customer or customer.email != email:
        raise HTTPException(status_code=403, detail="Unauthorized")
        
    if sub.status == "canceled":
        return {"message": "Already canceled", "status": "canceled"}
        
    sub.status = "canceled"
    sub.canceled_at = datetime.utcnow()
    session.add(sub)
    session.commit()
    return {"message": "Subscription canceled successfully", "status": "canceled"}
