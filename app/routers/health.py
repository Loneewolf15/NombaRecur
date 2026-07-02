from fastapi import APIRouter
from datetime import datetime

router = APIRouter()


@router.get("/health", tags=["Health"])
def health_check():
    """
    Judges hit this first. Must return 200.
    Also useful for Railway health check probe.
    """
    return {
        "status": "ok",
        "service": "NombaRecur",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "environment": "sandbox",
    }
