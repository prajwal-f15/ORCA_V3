"""Response schemas for ORCA Route Engine."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.models.request import Coordinate


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(default="ok", description="Service operational status")
    service: str = Field(default="orca-route-engine", description="Service identifier")


class ServiceInfoResponse(BaseModel):
    """Service information root response model."""

    name: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    environment: str = Field(..., description="Running environment")
    docs_url: str = Field(..., description="Interactive API documentation URL")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional service metadata")


class RouteSummary(BaseModel):
    """Summary metrics of calculated route."""

    distance_km: float = Field(
        ...,
        ge=0.0,
        description="Total computed route distance in kilometers (>= 0)",
        examples=[45.2],
    )
    distance_nm: float = Field(
        ...,
        ge=0.0,
        description="Total computed route distance in nautical miles (>= 0)",
        examples=[24.4],
    )
    estimated_time_minutes: float = Field(
        ...,
        ge=0.0,
        description="Estimated duration of the voyage in minutes (>= 0)",
        examples=[117.0],
    )
    route_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Overall route efficiency/safety score between 0 and 100",
        examples=[92.5],
    )


class RouteConstraints(BaseModel):
    """Status of safety and environmental constraint evaluations."""

    safety_check: str = Field(
        ...,
        description="Safety verification status (e.g. 'passed', 'warning')",
        examples=["passed"],
    )
    weather_check: str = Field(
        ...,
        description="Weather feasibility status (e.g. 'passed', 'advisory')",
        examples=["passed"],
    )
    restricted_area_check: str = Field(
        ...,
        description="Restricted zone and marine boundary clearance status (e.g. 'cleared', 'avoided')",
        examples=["cleared"],
    )


class RouteResponse(BaseModel):
    """Full response payload for route calculation."""

    route_id: str = Field(
        ...,
        description="Unique identifier for the generated route",
        examples=["route-mock-12345"],
    )
    status: str = Field(
        ...,
        description="Execution status of the route calculation (e.g. 'success', 'computed')",
        examples=["success"],
    )
    summary: RouteSummary = Field(
        ...,
        description="Aggregated distance, duration, and score summary",
    )
    waypoints: List[Coordinate] = Field(
        ...,
        description="Ordered sequence of geographic coordinates forming the route path",
    )
    constraints: RouteConstraints = Field(
        ...,
        description="Constraint validation results",
    )
    marine_conditions: Optional[Any] = Field(
        default=None,
        description="Optional environmental marine conditions attached to response",
    )
    evaluation_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dynamic route evaluation and candidate scoring metadata",
    )
    safety_decision: Optional[str] = Field(
        default=None,
        description="Final authoritative safety clearance verdict from Safety Governor (ALLOW, WARN, REJECT, DEGRADED)",
        examples=["ALLOW"],
    )
    safety_evaluation: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed Safety Governor evaluation report, itemized checks, warnings, and blocking conditions",
    )


class NavigationState(BaseModel):
    """Live spatial navigation state metrics for an active vessel voyage."""

    current_position: Coordinate = Field(
        ...,
        description="Current live GPS position of the vessel",
    )
    destination: Coordinate = Field(
        ...,
        description="Target destination coordinate of the voyage",
    )
    remaining_distance_km: float = Field(
        ...,
        ge=0.0,
        description="Remaining great-circle distance to destination in kilometers",
    )
    remaining_distance_nm: float = Field(
        ...,
        ge=0.0,
        description="Remaining distance to destination in nautical miles",
    )
    estimated_time_remaining_minutes: float = Field(
        ...,
        ge=0.0,
        description="Estimated time remaining to reach destination in minutes",
    )
    bearing_degrees: float = Field(
        ...,
        ge=0.0,
        lt=360.0,
        description="Initial great-circle bearing from current position toward destination (0 to 359.99°)",
    )
    progress_percent: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Voyage completion percentage (0.0 to 100.0%)",
    )
    next_waypoint: Optional[Coordinate] = Field(
        default=None,
        description="Immediate next target waypoint along the planned path, or None if arrived/no waypoints",
    )
    total_waypoints: int = Field(
        default=0,
        ge=0,
        description="Total count of planned waypoints for this voyage",
    )
    status: str = Field(
        ...,
        description="Navigation lifecycle status ('not_started', 'navigating', 'arrived')",
    )
