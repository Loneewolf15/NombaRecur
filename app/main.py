from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from app.database import create_db_and_tables
from app.routers import health, tenants, plans, customers, subscriptions, webhooks


from app.services.scheduler import start_scheduler, shutdown_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    if not os.environ.get("VERCEL"):
        start_scheduler()
    yield
    # Shutdown
    if not os.environ.get("VERCEL"):
        shutdown_scheduler()


app = FastAPI(
    title="NombaRecur API",
    description="Multi-rail recurring billing engine on top of Nomba Checkout",
    version="1.0.0",
    lifespan=lifespan
)

# Routers
app.include_router(health.router, prefix="/health", tags=["System"])
app.include_router(tenants.router, prefix="/v1/tenants", tags=["Tenants"])
app.include_router(plans.router, prefix="/v1/plans", tags=["Plans"])
app.include_router(customers.router, prefix="/v1/customers", tags=["Customers"])
app.include_router(subscriptions.router, prefix="/v1/subscriptions", tags=["Subscriptions"])
app.include_router(webhooks.router, prefix="/v1/webhooks", tags=["Webhooks"])
from app.routers import dashboard
app.include_router(dashboard.router, prefix="/v1/dashboard", tags=["Dashboard"])

# Serve frontend
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/api/cron/billing", tags=["Vercel Cron"])
async def cron_billing():
    """Triggered by Vercel Cron every 5 minutes to run the billing loop for all tenants."""
    from app.services.scheduler import run_billing_cycle
    processed = await run_billing_cycle()
    return {"message": "Billing cycle complete", "processed": processed}

@app.get("/api/cron/recovery", tags=["Vercel Cron"])
async def cron_recovery():
    """Triggered by Vercel Cron every 15 minutes to recover dropped webhooks."""
    from app.services.scheduler import run_crash_recovery
    await run_crash_recovery()
    return {"message": "Crash recovery complete"}

@app.get("/")
def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        return {"message": "Frontend not built yet."}
    return FileResponse(index_path)
