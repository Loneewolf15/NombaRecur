from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class Plan(SQLModel, table=True):
    """A subscription plan offered by a tenant."""
    id: str = Field(default_factory=_uuid, primary_key=True)
    tenant_id: str = Field(index=True, foreign_key="tenant.id")

    name: str                           # e.g. "Starter", "Pro"
    amount_kobo: int                    # price in kobo — e.g. 250000 = ₦2,500
    currency: str = "NGN"
    interval: str = "monthly"          # monthly | yearly | weekly

    # Grace period after failed charge before suspension
    grace_period_days: int = 3
    # Max charge attempts before subscription is cancelled
    max_retries: int = 3

    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
