from fastapi import APIRouter
from app.safety.governor import safety_governor
from app.safety.schemas import SafetyCheckRequest, SafetyCheckResponse

router = APIRouter(prefix="/safety", tags=["Safety"])


@router.post(
    "/check",
    response_model=SafetyCheckResponse,
    summary="Evaluate Deterministic Safety Rules",
)
async def check_safety(request: SafetyCheckRequest) -> SafetyCheckResponse:
    """
    Evaluate deterministic maritime safety rules against voyage coordinates,
    weather conditions, marine risk scores, and restricted zone boundaries.
    """
    return safety_governor.evaluate(request)
