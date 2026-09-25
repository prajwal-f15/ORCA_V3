"""Request schemas for ORCA Route Engine."""

from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class Coordinate(BaseModel):
    """Geographic coordinate representation with boundary validation."""

    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees (-90 to 90)",
        examples=[18.9220],
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees (-180 to 180)",
        examples=[72.8347],
    )


class Vessel(BaseModel):
    """Vessel configuration and operational constraints."""

    speed_knots: float = Field(
        ...,
        gt=0.0,
        description="Vessel operational speed in knots (must be greater than 0)",
        examples=[12.5],
    )
    draft_meters: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Vessel static draught in meters (depth required below waterline)",
        examples=[2.5],
    )
    minimum_safe_depth_meters: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Minimum safe water column depth required by the vessel",
        examples=[3.5],
    )
    fuel_rate_liters_per_hour: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Optional vessel fuel consumption rate in liters per hour for lowest_fuel objective",
        examples=[45.0],
    )
    fuel_efficiency_nm_per_liter: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Optional vessel fuel efficiency in nautical miles per liter",
        examples=[0.35],
    )


SUPPORTED_ROUTING_OBJECTIVES = [
    "safe_and_efficient",
    "nearest_destination",
    "fastest_arrival",
    "lowest_fuel",
    "highest_potential",
]


class RouteRequest(BaseModel):
    """Input payload for maritime route calculation."""

    start: Coordinate = Field(
        ...,
        description="Starting coordinate of the voyage",
    )
    destination: Coordinate = Field(
        ...,
        description="Destination coordinate of the voyage",
    )
    vessel: Vessel = Field(
        ...,
        description="Vessel parameters and constraints",
    )
    objective: str = Field(
        default="safe_and_efficient",
        description="Routing objective profile ('safe_and_efficient', 'nearest_destination', 'fastest_arrival', 'lowest_fuel', 'highest_potential')",
        examples=["safe_and_efficient"],
    )
    environmental_conditions: Optional[Any] = Field(
        default=None,
        description="Optional environmental marine conditions context snapshot",
    )

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, v: str) -> str:
        """Validate that objective is one of the supported optimization profiles."""
        cleaned = v.strip().lower()
        if cleaned not in SUPPORTED_ROUTING_OBJECTIVES:
            raise ValueError(
                f"Unsupported routing objective: '{v}'. Supported objectives: {SUPPORTED_ROUTING_OBJECTIVES}"
            )
        return cleaned


class NavigationRequest(BaseModel):
    """Input payload for live vessel navigation state computation."""

    current_position: Coordinate = Field(
        ...,
        description="Current live GPS position of the vessel",
    )
    start: Coordinate = Field(
        ...,
        description="Origin starting coordinate of the voyage",
    )
    destination: Coordinate = Field(
        ...,
        description="Target destination coordinate of the voyage",
    )
    vessel: Vessel = Field(
        ...,
        description="Vessel operational speed and constraints",
    )
    waypoints: Optional[List[Coordinate]] = Field(
        default=None,
        description="Optional ordered sequence of planned waypoints along the route",
    )
    arrival_threshold_nm: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Optional custom arrival distance threshold in nautical miles",
    )
