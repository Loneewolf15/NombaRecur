from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class BillingAttempt(SQLModel, table=True):
    """Immutable audit log of every billing attempt — the crash-recovery anchor."""
    id: str = Field(default_factory=_uuid, primary_key=True)
    subscription_id: str = Field(index=True, foreign_key="subscription.id")
    tenant_id: str = Field(index=True)

    # Amount attempted — always in kobo
    amount_kobo: int

    # Rail used: card | bank_transfer | mandate
    rail: str

    # Idempotency: merchant_tx_ref sent to Nomba
    # Format: nr_{subscription_id[:8]}_{period_start_date}_{attempt_number}
    merchant_tx_ref: str = Field(unique=True, index=True)

    # Lifecycle: pending → success | failed
    # On startup, replay all pending attempts older than 30 min (APScheduler crash recovery)
    status: str = "pending"

    # Nomba's transaction ID (populated on webhook receipt)
    nomba_transaction_id: Optional[str] = None

    # Nomba's requestId (for idempotency dedup on webhook)
    nomba_request_id: Optional[str] = None

    # Error info for failed attempts
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    attempted_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
