from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import create_db_and_tables
from app.routers import health, tenants, plans, customers, subscriptions, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    # TODO: on startup, replay any BillingAttempt where status='pending'
    #       and attempted_at < (now - 30 min) — APScheduler crash recovery
    yield
    # Shutdown (nothing to clean up yet)


app = FastAPI(
    title="NombaRecur",
    description="Recurring billing infrastructure for Nigerian SaaS, powered by Nomba.",
    version="1.0.0",
    lifespan=lifespan,
)

# Routers
app.include_router(health.router)
app.include_router(tenants.router, prefix="/v1/tenants", tags=["Tenants"])
app.include_router(plans.router, prefix="/v1/plans", tags=["Plans"])
app.include_router(customers.router, prefix="/v1/customers", tags=["Customers"])
app.include_router(subscriptions.router, prefix="/v1/subscriptions", tags=["Subscriptions"])
app.include_router(webhooks.router, prefix="/v1/webhooks", tags=["Webhooks"])
