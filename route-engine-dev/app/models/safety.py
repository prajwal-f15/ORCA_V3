"""Safety Governor domain models and evaluation schema for ORCA V3."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.models.marine_conditions import MarineConditionsSnapshot
from app.models.request import Coordinate, Vessel


class SafetyDecision(str, Enum):
    """Final navigational safety decisions issued exclusively by the Safety Governor."""

    ALLOW = "ALLOW"
    WARN = "WARN"
    REJECT = "REJECT"
    DEGRADED = "DEGRADED"


class CheckStatus(str, Enum):
    """Individual safety check outcome statuses."""

    PASS = "PASS"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    UNAVAILABLE = "UNAVAILABLE"


class SafetyCheckResult(BaseModel):
    """Structured result of Safety Governor comprehensive route clearance evaluation."""

    decision: SafetyDecision = Field(
        ...,
        description="Final authoritative safety verdict: ALLOW, WARN, REJECT, or DEGRADED",
        examples=[SafetyDecision.ALLOW],
    )
    reason: str = Field(
        ...,
        description="Summary explanation of the primary safety decision",
        examples=["All required safety checks passed successfully."],
    )
    checks: Dict[str, str] = Field(
        default_factory=dict,
        description="Itemized check outcomes for restricted_area, bathymetry, ocean, weather, and data_quality",
        examples=[{"restricted_area": "PASS", "bathymetry": "PASS", "ocean": "PASS", "weather": "PASS", "data_quality": "PASS"}],
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-blocking advisory warnings identified during safety evaluation",
    )
    blocking_reasons: List[str] = Field(
        default_factory=list,
        description="Critical safety violations necessitating route REJECT verdict",
    )
    data_status: Dict[str, str] = Field(
        default_factory=dict,
        description="Status assessment of safety inputs (available, mock, unavailable, stale)",
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the safety governor evaluation",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional diagnostic context, evaluated thresholds, and vessel safety margins",
    )


class SafetyEvaluationRequest(BaseModel):
    """Payload for standalone Safety Governor route evaluation endpoint."""

    waypoints: List[Coordinate] = Field(
        ...,
        min_length=2,
        description="Ordered sequence of route waypoints to be checked for safety",
    )
    vessel: Vessel = Field(
        ...,
        description="Vessel specifications, draft, and operational limits",
    )
    marine_conditions: Optional[MarineConditionsSnapshot] = Field(
        default=None,
        description="Optional environmental snapshot (currents, waves, wind, visibility)",
    )
    route_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Calculated route efficiency score from Route Engine (cannot override Safety Governor)",
    )
    objective: Optional[str] = Field(
        default="safe_and_efficient",
        description="Routing objective profile requested by vessel operator",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional evaluation parameters and situational flags",
    )
