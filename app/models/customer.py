from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class Customer(SQLModel, table=True):
    """A subscriber (end customer) of a tenant."""
    id: str = Field(default_factory=_uuid, primary_key=True)
    tenant_id: str = Field(index=True, foreign_key="tenant.id")

    # Customer identity (as provided by the tenant)
    external_id: str = Field(index=True)  # tenant's own user ID
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None

    # Nomba tokenized card key (received from webhook after first checkout)
    # Stored encrypted — used for recurring charges (Rail 1)
    nomba_token_key_enc: Optional[str] = None

    # Virtual Account NUBAN assigned during dunning (Rail 2)
    va_account_number: Optional[str] = None
    va_account_ref: Optional[str] = None

    # Direct Debit mandate ID (Rail 3 — production only)
    mandate_id: Optional[str] = None
    mandate_status: Optional[str] = None   # ACTIVE | SUSPENDED | DELETED

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        # Composite unique: one external_id per tenant
        # Enforced at the application layer — SQLite doesn't support multi-col unique easily
        pass
