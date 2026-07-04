import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from sqlmodel import Session, select
from app.database import get_session, engine
from app.models.tenant import Tenant
from app.models.customer import Customer
from app.dependencies import get_current_tenant

logger = logging.getLogger(__name__)
router = APIRouter()


class CustomerCreate(BaseModel):
    external_id: str
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None


def _provision_va_background(customer_id: str, tenant_id: str):
    """
    Provisions a dedicated Virtual Account for a customer.
    Runs in a background task so it never blocks or fails the customer creation response.
    """
    import asyncio
    from app.services.nomba import NombaClient

    async def _run():
        with Session(engine) as session:
            customer = session.get(Customer, customer_id)
            tenant = session.get(Tenant, tenant_id)
            if not customer or not tenant:
                return
            try:
                import time
                nomba = NombaClient(tenant, session)
                va = await nomba.create_virtual_account(
                    account_ref=f"cust_{customer.id[:8]}_{int(time.time())}",
                    account_name=customer.name or customer.email
                )
                # Nomba returns "bankAccountNumber" (not "accountNumber") for VA creation
                customer.va_account_number = va.get("bankAccountNumber")
                customer.va_account_ref = va.get("accountRef")
                session.add(customer)
                session.commit()
                logger.info(f"VA provisioned for customer {customer_id}: {customer.va_account_number}")
            except Exception as e:
                logger.warning(f"VA provisioning failed for customer {customer_id}: {e}")

    asyncio.run(_run())


@router.get("/")
def list_customers(session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """List all customers for the current tenant."""
    return session.exec(select(Customer).where(Customer.tenant_id == tenant.id)).all()


@router.post("/")
def create_customer(
    data: CustomerCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant)
):
    """
    Register a subscriber. Returns immediately.
    VA provisioning happens in the background — poll GET /v1/customers/{id}
    to see va_account_number once it's ready.
    """
    stmt = select(Customer).where(Customer.tenant_id == tenant.id, Customer.external_id == data.external_id)
    existing = session.exec(stmt).first()
    if existing:
        return existing

    customer = Customer(
        tenant_id=tenant.id,
        external_id=data.external_id,
        email=data.email,
        name=data.name,
        phone=data.phone
    )
    session.add(customer)
    session.commit()
    session.refresh(customer)

    # Fire VA provisioning after the response is already sent — never blocks or fails the caller
    background_tasks.add_task(_provision_va_background, customer.id, tenant.id)

    return customer


@router.get("/{customer_id}")
def get_customer(customer_id: str, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """Get a single customer by ID — use this to poll for va_account_number after creation."""
    from fastapi import HTTPException
    customer = session.get(Customer, customer_id)
    if not customer or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.post("/{customer_id}/provision-va")
def retry_provision_va(customer_id: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """Retry VA provisioning for a customer that didn't get one on creation."""
    from fastapi import HTTPException
    customer = session.get(Customer, customer_id)
    if not customer or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    if customer.va_account_number:
        return {"message": "VA already provisioned", "va_account_number": customer.va_account_number}
    background_tasks.add_task(_provision_va_background, customer.id, tenant.id)
    return {"message": "VA provisioning started", "customer_id": customer_id}

@router.delete("/{customer_id}")
def delete_customer(customer_id: str, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    from fastapi import HTTPException
    customer = session.get(Customer, customer_id)
    if not customer or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    session.delete(customer)
    session.commit()
    return {"message": "Customer deleted successfully"}
