"""Models for dynamic candidate route generation, evaluation, optimization, and scoring."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.models.marine_conditions import MarineConditionsSnapshot
from app.models.request import Coordinate


class RoutingObjective(str, Enum):
    """Supported routing optimization objectives."""

    SAFE_AND_EFFICIENT = "safe_and_efficient"
    NEAREST_DESTINATION = "nearest_destination"
    FASTEST_ARRIVAL = "fastest_arrival"
    LOWEST_FUEL = "lowest_fuel"
    HIGHEST_POTENTIAL = "highest_potential"


class ObjectiveWeights(BaseModel):
    """Configurable scoring weights for a routing optimization profile."""

    distance_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    eta_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    ocean_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    weather_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    constraint_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    vessel_weight: float = Field(default=0.05, ge=0.0, le=1.0)
    fuel_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    potential_weight: float = Field(default=0.0, ge=0.0, le=1.0)


class CandidateScoringBreakdown(BaseModel):
    """Detailed scoring components for an evaluated candidate route."""

    distance_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Efficiency score based on voyage distance (0 to 100)",
    )
    eta_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Efficiency score based on voyage duration (0 to 100)",
    )
    ocean_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Penalty deducted for unfavorable ocean currents or wave height (0 to 100)",
    )
    weather_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Penalty deducted for high winds, gusts, or poor visibility (0 to 100)",
    )
    constraint_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Penalty deducted for restricted marine zones or shallow water (0 to 100)",
    )
    vessel_score: float = Field(
        default=100.0,
        ge=0.0,
        le=100.0,
        description="Vessel operational compatibility score (0 to 100)",
    )
    fuel_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Fuel efficiency rating score (0 to 100) or None if unavailable",
    )
    potential_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Fishing/PFZ potential score (0 to 100) or None if unavailable",
    )
    composite_base_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Weighted base score before penalties",
    )
    final_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Final normalized route score in [0.0, 100.0]",
    )


class CandidateRoute(BaseModel):
    """A generated candidate voyage route with geometric waypoints and evaluation metrics."""

    candidate_id: str = Field(
        ...,
        description="Identifier of the candidate route (e.g. 'candidate-direct', 'candidate-starboard-1')",
    )
    variant_name: str = Field(
        ...,
        description="Geometric variation profile name (e.g. 'direct_geodesic', 'starboard_offset', 'port_offset')",
    )
    waypoints: List[Coordinate] = Field(
        ...,
        description="Ordered sequence of geographic coordinates for this candidate path",
    )
    distance_km: float = Field(
        ...,
        ge=0.0,
        description="Total computed distance in kilometers",
    )
    distance_nm: float = Field(
        ...,
        ge=0.0,
        description="Total computed distance in nautical miles",
    )
    estimated_time_minutes: float = Field(
        ...,
        ge=0.0,
        description="Estimated voyage duration in minutes",
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Evaluated route score (0 to 100)",
    )
    scoring_breakdown: Optional[CandidateScoringBreakdown] = Field(
        default=None,
        description="Itemized score contributions and penalties",
    )
    ocean_status: str = Field(
        default="pending",
        description="Ocean data assessment status ('evaluated', 'mock', 'unavailable', 'pending')",
    )
    weather_status: str = Field(
        default="pending",
        description="Weather data assessment status ('evaluated', 'mock', 'unavailable', 'pending')",
    )
    constraint_status: str = Field(
        default="pending",
        description="Marine constraint clearance status ('cleared', 'warning', 'restricted_detected', 'pending')",
    )
    fuel_status: str = Field(
        default="unavailable",
        description="Fuel data assessment status ('available', 'estimated', 'unavailable')",
    )
    pfz_status: str = Field(
        default="not_required",
        description="PFZ data assessment status ('available', 'mock', 'unavailable', 'not_required')",
    )
    evaluation_details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Evaluation diagnostics, warnings, and generator metadata",
    )


class DynamicRouteEvaluationSummary(BaseModel):
    """Aggregate summary of multi-candidate dynamic routing evaluation."""

    candidate_count: int = Field(
        ...,
        ge=1,
        description="Total number of candidate routes generated and evaluated",
    )
    selected_candidate: str = Field(
        ...,
        description="ID of the selected highest-scoring candidate route",
    )
    selected_variant: str = Field(
        ...,
        description="Variant name of the selected candidate route",
    )
    objective: str = Field(
        default="safe_and_efficient",
        description="Active optimization objective profile",
    )
    scoring: Dict[str, float] = Field(
        ...,
        description="Scoring breakdown of the selected winning candidate",
    )
    all_candidates: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Summary of all evaluated candidate routes for comparison",
    )
    pfz_integration: str = Field(
        default="not_required",
        description="PFZ integration status ('available', 'mock', 'unavailable', 'not_required')",
    )
    fuel_integration: str = Field(
        default="unavailable",
        description="Fuel data integration status ('available', 'estimated', 'unavailable')",
    )
    generator_mode: str = Field(
        default="deterministic_geometric_variation",
        description="Generator implementation mode (testing / mock)",
    )
    safety_governor_notice: str = Field(
        default="Route scoring evaluates navigation efficiency and environmental context. Final safety clearance remains strictly with the Safety Governor.",
        description="Safety boundary disclaimer",
    )
