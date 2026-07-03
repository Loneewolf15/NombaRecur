from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlmodel import Session, select
import bcrypt
from app.database import get_session
from app.models.tenant import Tenant

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str, hashed_key: str) -> bool:
    return bcrypt.checkpw(api_key.encode('utf-8'), hashed_key.encode('utf-8'))

def get_current_tenant(api_key: str = Security(api_key_header), session: Session = Depends(get_session)) -> Tenant:
    # In a real system, you might cache this or encode tenant_id in the api key (e.g. "tenant_123_apikey")
    # For simplicity, we just query all tenants and check (only doing this because it's a hackathon demo!)
    # A better way is: api_key = "tenantId_randomString", split by _ to get tenant_id.
    
    parts = api_key.split("_", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Invalid API Key format. Expected format: {tenant_id}_{secret}")
        
    tenant_id, secret = parts
    
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API Key")
        
    if not verify_api_key(secret, tenant.api_key_hash):
        raise HTTPException(status_code=401, detail="Invalid API Key")
        
    return tenant
