from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SafetyDecision(str, Enum):
    """Core deterministic safety decisions."""

    ALLOW = "ALLOW"
    WARN = "WARN"
    REJECT = "REJECT"
    DEGRADED = "DEGRADED"


class SafetyStatus(str, Enum):
    """Safety status descriptions."""

    TRIP_NOT_RECOMMENDED = "TRIP_NOT_RECOMMENDED"
    ROUTE_NOT_ALLOWED = "ROUTE_NOT_ALLOWED"
    INVALID_LOCATION = "INVALID_LOCATION"
    SAFETY_DATA_UNAVAILABLE = "SAFETY_DATA_UNAVAILABLE"
    CAUTION_REQUIRED = "CAUTION_REQUIRED"
    SAFETY_CHECK_PASSED = "SAFETY_CHECK_PASSED"


class SafetyReasonCode(str, Enum):
    """Deterministic safety reason codes."""

    INVALID_COORDINATES = "INVALID_COORDINATES"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"
    EXTREME_WEATHER = "EXTREME_WEATHER"
    HIGH_MARINE_RISK = "HIGH_MARINE_RISK"
    CRITICAL_DATA_MISSING = "CRITICAL_DATA_MISSING"
    MODERATE_MARINE_RISK = "MODERATE_MARINE_RISK"
    NO_BLOCKING_CONDITION = "NO_BLOCKING_CONDITION"


class LocationCoordinate(BaseModel):
    """Geographic coordinate representation."""

    latitude: Optional[float] = Field(default=None, description="Latitude in decimal degrees (-90 to 90)")
    longitude: Optional[float] = Field(default=None, description="Longitude in decimal degrees (-180 to 180)")


class WeatherCondition(BaseModel):
    """Weather condition flags."""

    extreme: bool = Field(default=False, description="Flag indicating extreme weather/cyclone/storm advisory")


class SafetyCheckRequest(BaseModel):
    """Input payload for deterministic safety evaluation."""

    request_id: Optional[str] = Field(default=None, description="Traceability request UUID")
    location: Optional[LocationCoordinate] = Field(default=None, description="Voyage or waypoint coordinates")
    marine_risk: Optional[float] = Field(default=None, description="Marine risk score (0-100), or None if unknown")
    weather: Optional[WeatherCondition] = Field(default=None, description="Weather conditions data")
    restricted_zone: bool = Field(default=False, description="Flag indicating if route or spot intersects a restricted maritime zone")
    critical_data_missing: bool = Field(default=False, description="Flag indicating essential sensor/forecast data is missing")
    require_marine_risk: bool = Field(default=False, description="Flag indicating that marine risk evaluation is mandatory for this check")


class SafetyCheckResponse(BaseModel):
    """Structured response from the Safety Governor."""

    request_id: str = Field(..., description="Traceable request identifier")
    decision: SafetyDecision = Field(..., description="Deterministic decision: ALLOW, WARN, REJECT, or DEGRADED")
    status: str = Field(..., description="High-level status code")
    reason_code: str = Field(..., description="Machine-readable root reason code")
    reasons: List[str] = Field(default_factory=list, description="List of concise, machine-readable reason strings")
    warnings: List[str] = Field(default_factory=list, description="List of non-blocking warning strings")
