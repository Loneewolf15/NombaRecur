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
    start_scheduler()
    yield
    # Shutdown
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

@app.get("/")
def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        return {"message": "Frontend not built yet."}
    return FileResponse(index_path)
