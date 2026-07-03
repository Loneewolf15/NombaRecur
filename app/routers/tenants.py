from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlmodel import Session
import bcrypt
import secrets

from app.database import get_session
from app.models.tenant import Tenant
from app.utils.crypto import encrypt_val

router = APIRouter()

_ENV_URLS = {
    "sandbox": "https://sandbox.nomba.com",
    "production": "https://api.nomba.com",
}

class TenantCreate(BaseModel):
    name: str
    email: str
    # Parent account ID — goes in the `accountId` header on every Nomba API call
    nomba_account_id: str
    # Sub-account ID — scopes transactions to this team/merchant within the parent
    nomba_sub_account_id: Optional[str] = None
    nomba_client_id: str
    nomba_client_secret: str
    webhook_url: str = ""
    env: str = "sandbox"

@router.post("/", response_model=dict)
def register_tenant(data: TenantCreate, session: Session = Depends(get_session)):
    """
    Registers a new SaaS business on NombaRecur.
    Returns the API Key that must be used for subsequent requests.
    """
    from sqlmodel import select

    existing = session.exec(select(Tenant).where(Tenant.email == data.email)).first()
    raw_secret = secrets.token_urlsafe(32)

    env = data.env if data.env in _ENV_URLS else "sandbox"
    base_url = _ENV_URLS[env]

    if existing:
        existing.api_key_hash = bcrypt.hashpw(raw_secret.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        existing.nomba_account_id_enc = encrypt_val(data.nomba_account_id)
        existing.nomba_sub_account_id_enc = encrypt_val(data.nomba_sub_account_id) if data.nomba_sub_account_id else None
        existing.nomba_client_id_enc = encrypt_val(data.nomba_client_id)
        existing.nomba_client_secret_enc = encrypt_val(data.nomba_client_secret)
        existing.env = env
        existing.nomba_base_url = base_url
        if data.webhook_url:
            existing.webhook_url = data.webhook_url
        session.add(existing)
        session.commit()
        return {
            "id": existing.id,
            "name": existing.name,
            "env": existing.env,
            "api_key": f"{existing.id}_{raw_secret}",
            "message": "Tenant updated securely."
        }

    tenant = Tenant(
        name=data.name,
        email=data.email,
        api_key_hash=bcrypt.hashpw(raw_secret.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
        nomba_account_id_enc=encrypt_val(data.nomba_account_id),
        nomba_sub_account_id_enc=encrypt_val(data.nomba_sub_account_id) if data.nomba_sub_account_id else None,
        nomba_client_id_enc=encrypt_val(data.nomba_client_id),
        nomba_client_secret_enc=encrypt_val(data.nomba_client_secret),
        webhook_url=data.webhook_url,
        env=env,
        nomba_base_url=base_url,
    )

    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    return {
        "id": tenant.id,
        "name": tenant.name,
        "env": tenant.env,
        "api_key": f"{tenant.id}_{raw_secret}",
        "message": "Store this API key securely. It will not be shown again."
    }
