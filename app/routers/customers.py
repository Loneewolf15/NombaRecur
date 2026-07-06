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


class MandateEnroll(BaseModel):
    account_number: str
    bank_code: str
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
                logger.info(f"Nomba VA API Response for customer {customer_id}: {va}")
                # Nomba returns the data inside a 'data' wrapper
                customer.va_account_number = va.get("data", {}).get("bankAccountNumber") or va.get("bankAccountNumber")
                customer.va_account_ref = va.get("data", {}).get("accountRef") or va.get("accountRef")
                session.add(customer)
                session.commit()
                logger.info(f"VA provisioned for customer {customer_id}: {customer.va_account_number}")
                # Notify customer with their VA card email
                try:
                    from app.services.email import send_va_card_email
                    send_va_card_email(customer.email, customer.name, customer.va_account_number)
                except Exception as email_err:
                    logger.warning(f"VA card email failed for {customer_id}: {email_err}")
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

@router.post("/{customer_id}/enroll-mandate")
def enroll_direct_debit(
    customer_id: str,
    data: MandateEnroll,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    tenant: Tenant = Depends(get_current_tenant)
):
    """
    Enroll a customer's bank account in a direct debit mandate.
    Requires: account_number, bank_code, phone
    """
    from fastapi import HTTPException
    import asyncio
    from app.services.nomba import NombaClient

    customer = session.get(Customer, customer_id)
    if not customer or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Customer not found")

    account_number = data.account_number.strip()
    bank_code = data.bank_code.strip()
    phone = (data.phone or customer.phone or "").strip()

    async def _run():
        with Session(engine) as s:
            cust = s.get(Customer, customer_id)
            t = s.get(Tenant, tenant.id)
            if not cust or not t:
                return {"error": "Not found"}
            nomba = NombaClient(t, s)
            try:
                result = await nomba.create_mandate(
                    customer_account_number=account_number,
                    bank_code=bank_code,
                    customer_name=cust.name or cust.email,
                    customer_phone=phone,
                    customer_email=cust.email,
                    merchant_reference=f"mandate_{cust.id[:8]}"
                )
                mandate_id = result.get("mandateId") or result.get("id") or result.get("merchantReference")
                cust.mandate_id = mandate_id
                cust.mandate_status = "ACTIVE"
                s.add(cust)
                s.commit()
                logger.info(f"Mandate created for customer {customer_id}: {mandate_id}")
                return {"mandate_id": mandate_id}
            except Exception as e:
                logger.error(f"Mandate creation failed for {customer_id}: {e}")
                return {"error": str(e)}

    result = asyncio.run(_run())
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"message": "Direct debit mandate enrolled", "mandate_id": result.get("mandate_id"), "customer_id": customer_id}


@router.delete("/{customer_id}")
def delete_customer(customer_id: str, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    from fastapi import HTTPException
    from app.models.subscription import Subscription
    from app.models.billing_attempt import BillingAttempt

    customer = session.get(Customer, customer_id)
    if not customer or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Customer not found")
        
    # Delete associated subscriptions and their billing attempts first 
    # to avoid PostgreSQL foreign key constraint violations
    subscriptions = session.exec(select(Subscription).where(Subscription.customer_id == customer_id)).all()
    for sub in subscriptions:
        attempts = session.exec(select(BillingAttempt).where(BillingAttempt.subscription_id == sub.id)).all()
        for attempt in attempts:
            session.delete(attempt)
        session.delete(sub)
        
    session.delete(customer)
    
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to delete customer {customer_id}: {e}")
        raise HTTPException(status_code=400, detail="Failed to delete customer due to constraint violation")
        
    return {"message": "Customer deleted successfully"}
