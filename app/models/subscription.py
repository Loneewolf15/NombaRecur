from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class Subscription(SQLModel, table=True):
    """A customer's active subscription to a plan."""
    id: str = Field(default_factory=_uuid, primary_key=True)
    tenant_id: str = Field(index=True, foreign_key="tenant.id")
    customer_id: str = Field(index=True, foreign_key="customer.id")
    plan_id: str = Field(foreign_key="plan.id")

    # State machine: trialing → active → past_due → canceled
    status: str = "trialing"

    # Billing cycle
    current_period_start: datetime
    current_period_end: datetime
    next_billing_at: datetime

    # Retry tracking
    retry_count: int = 0

    # Checkout link for VA recovery (Rail 2 dunning — regenerated fresh each time)
    # Stored here temporarily so the webhook can match it back to this subscription
    pending_checkout_order_ref: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    canceled_at: Optional[datetime] = None
