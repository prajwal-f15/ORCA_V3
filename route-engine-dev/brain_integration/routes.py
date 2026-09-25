"""FastAPI test endpoint router for Brain Route Engine integration."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from brain_integration.route_engine_tool import (
    DEFAULT_ROUTE_ENGINE_URL,
    RouteEngineError,
    call_route_engine_api,
)

router = APIRouter(tags=["Brain Route Engine Test"])


class CoordinateInput(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


class VesselInput(BaseModel):
    speed_knots: float = Field(default=8.5, gt=0.0)


class BrainRouteEngineTestRequest(BaseModel):
    """Optional request payload for the test endpoint; defaults to benchmark coordinates."""

    start: CoordinateInput = Field(
        default=CoordinateInput(latitude=18.5204, longitude=72.8567),
        description="Starting coordinate",
    )
    destination: CoordinateInput = Field(
        default=CoordinateInput(latitude=18.6500, longitude=72.9000),
        description="Destination coordinate",
    )
    vessel: VesselInput = Field(
        default=VesselInput(speed_knots=8.5),
        description="Vessel operational speed",
    )
    objective: str = Field(
        default="safe_and_efficient",
        description="Routing objective profile",
    )


@router.post(
    "/test/route-engine",
    summary="Test Route Engine Integration",
    description="Invokes the standalone Route Engine API at http://127.0.0.1:8000/route and returns the response.",
    status_code=status.HTTP_200_OK,
)
async def test_route_engine_endpoint(
    request: Optional[BrainRouteEngineTestRequest] = None,
) -> Dict[str, Any]:
    """Test endpoint in Brain backend that delegates to call_route_engine_api."""
    req = request or BrainRouteEngineTestRequest()
    try:
        response_data = call_route_engine_api(
            start_latitude=req.start.latitude,
            start_longitude=req.start.longitude,
            dest_latitude=req.destination.latitude,
            dest_longitude=req.destination.longitude,
            speed_knots=req.vessel.speed_knots,
            objective=req.objective,
        )
        return response_data
    except RouteEngineError as err:
        status_code = err.status_code if err.status_code and err.status_code >= 400 else 503
        raise HTTPException(
            status_code=status_code,
            detail={"error": "RouteEngineIntegrationError", "message": err.message, "details": err.details},
        ) from err
