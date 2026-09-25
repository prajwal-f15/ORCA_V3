from fastapi import APIRouter
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Health Check")
async def health_check() -> HealthResponse:
    """Check if the backend service is running and healthy."""
    return HealthResponse(status="ok")
