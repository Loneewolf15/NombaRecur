from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from app.database import get_session
from app.models.tenant import Tenant
from app.models.plan import Plan
from app.dependencies import get_current_tenant

router = APIRouter()

@router.get("/")
def list_plans(session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """List all plans for the current tenant."""
    plans = session.exec(select(Plan).where(Plan.tenant_id == tenant.id)).all()
    return plans

class PlanCreate(BaseModel):
    name: str
    amount_kobo: int
    interval: str = "monthly"

@router.post("/")
def create_plan(data: PlanCreate, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """
    Create a new subscription plan (e.g. Pro, Starter).
    """
    plan = Plan(
        tenant_id=tenant.id,
        name=data.name,
        amount_kobo=data.amount_kobo,
        interval=data.interval
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan

@router.delete("/{plan_id}")
def delete_plan(plan_id: str, session: Session = Depends(get_session), tenant: Tenant = Depends(get_current_tenant)):
    """Deletes a plan if no active subscriptions are tied to it."""
    from fastapi import HTTPException
    plan = session.get(Plan, plan_id)
    if not plan or plan.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Plan not found")
        
    session.delete(plan)
    session.commit()
    return {"message": "Plan deleted successfully"}
