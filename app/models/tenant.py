from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class Tenant(SQLModel, table=True):
    """A business using NombaRecur to bill their subscribers."""
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)

    # API key for authenticating tenant requests to us (stored as bcrypt hash)
    api_key_hash: str

    # Nomba credentials — encrypted at rest with Fernet (AES-128-CBC)
    nomba_account_id_enc: str
    nomba_client_id_enc: str
    nomba_client_secret_enc: str

    # Cached Nomba token (encrypted) — refreshed automatically by scheduler
    nomba_access_token_enc: Optional[str] = None
    nomba_refresh_token_enc: Optional[str] = None
    nomba_token_expires_at: Optional[datetime] = None

    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
