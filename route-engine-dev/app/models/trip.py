"""Trip and voyage tracking models for ORCA Route Engine."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator
from app.models.request import Coordinate, Vessel
from app.models.response import NavigationState


class TripStatus(str, Enum):
    """Lifecycle statuses for a vessel voyage/trip."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReturnMode(str, Enum):
    """Destination target mode for return navigation."""

    START = "start"
    HARBOUR = "harbour"


class ReturnStatus(str, Enum):
    """Lifecycle statuses for return navigation."""

    RETURN_NOT_STARTED = "return_not_started"
    RETURNING = "returning"
    RETURN_ARRIVED = "return_arrived"


class TripTrackPoint(BaseModel):
    """Single GPS track point recorded along a voyage."""

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
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the GPS point was captured",
    )
    sequence_number: int = Field(
        default=0,
        ge=0,
        description="Zero-indexed sequence number of the track point in the voyage path",
        examples=[0],
    )


class TripStartRequest(BaseModel):
    """Input payload to start tracking a new vessel trip."""

    start: Coordinate = Field(
        ...,
        description="Origin coordinate where the trip begins",
    )
    destination: Coordinate = Field(
        ...,
        description="Final destination coordinate of the trip",
    )
    vessel: Vessel = Field(
        ...,
        description="Vessel kinematics and operational speed in knots",
    )
    waypoints: List[Coordinate] = Field(
        default_factory=list,
        description="Planned route waypoints",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional initial start timestamp (defaults to current UTC time)",
    )
    arrival_threshold_nm: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Configurable arrival proximity threshold in nautical miles",
        examples=[0.1],
    )


class TripUpdateRequest(BaseModel):
    """Input payload for a live GPS update during an active trip."""

    current_position: Coordinate = Field(
        ...,
        description="Latest recorded GPS coordinate of the vessel",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the GPS update (defaults to current UTC time)",
    )


class TripStopRequest(BaseModel):
    """Input payload to stop and complete an active trip."""

    current_position: Optional[Coordinate] = Field(
        default=None,
        description="Optional final GPS position upon stopping; uses latest position if omitted",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional completion timestamp (defaults to current UTC time)",
    )


class ReturnTripRequest(BaseModel):
    """Input payload to switch active voyage to return navigation mode."""

    mode: ReturnMode = Field(
        ...,
        description="Target return destination mode ('start' for origin, 'harbour' for custom harbour)",
        examples=["start"],
    )
    harbour: Optional[Coordinate] = Field(
        default=None,
        description="Required destination coordinates when mode is 'harbour'",
    )

    @model_validator(mode="after")
    def validate_harbour_requirement(self) -> "ReturnTripRequest":
        """Ensure harbour coordinate is provided when mode is 'harbour'."""
        if self.mode == ReturnMode.HARBOUR and self.harbour is None:
            raise ValueError("Harbour coordinate is required when return mode is 'harbour'.")
        return self


class ReturnUpdateRequest(BaseModel):
    """Input payload for a live GPS update during return navigation."""

    current_position: Coordinate = Field(
        ...,
        description="Latest recorded GPS coordinate of the vessel during return journey",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the GPS update (defaults to current UTC time)",
    )


class ReturnNavigationState(BaseModel):
    """Live return navigation status and spatial metrics of the vessel toward return target."""

    trip_id: str = Field(..., description="Unique trip identifier")
    return_mode: str = Field(..., description="Active return mode ('start' or 'harbour')")
    return_destination: Coordinate = Field(
        ..., description="Target coordinate of the return voyage"
    )
    current_position: Coordinate = Field(..., description="Current GPS coordinates of the vessel")
    remaining_distance_km: float = Field(
        ...,
        ge=0.0,
        description="Remaining great-circle distance to return destination in kilometers",
        examples=[45.2],
    )
    remaining_distance_nm: float = Field(
        ...,
        ge=0.0,
        description="Remaining distance to return destination in nautical miles",
        examples=[24.4],
    )
    estimated_time_remaining_minutes: float = Field(
        ...,
        ge=0.0,
        description="Estimated remaining travel duration to return destination in minutes",
        examples=[117.0],
    )
    bearing_degrees: float = Field(
        ...,
        ge=0.0,
        lt=360.0,
        description="Initial great-circle bearing towards return destination in degrees [0, 360)",
        examples=[184.5],
    )
    progress_percent: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Calculated return voyage completion progress percentage [0, 100]",
        examples=[45.0],
    )
    status: str = Field(
        ...,
        description="Return navigation status ('return_not_started', 'returning', 'return_arrived')",
        examples=["returning"],
    )


class ReturnCancelResponse(BaseModel):
    """Response returned upon cancelling return navigation."""

    message: str = Field(..., description="Cancellation confirmation message")
    trip_id: str = Field(..., description="ID of active trip")


class TripSummary(BaseModel):
    """High-level summary metrics of a recorded trip."""

    trip_id: str = Field(..., description="Unique trip identifier")
    start_position: Coordinate = Field(..., description="Starting coordinate of the trip")
    current_position: Coordinate = Field(..., description="Latest or final recorded coordinate")
    destination: Coordinate = Field(..., description="Target destination coordinate")
    distance_travelled_km: float = Field(
        ...,
        ge=0.0,
        description="Total cumulative distance travelled in kilometers",
        examples=[30.0],
    )
    distance_travelled_nm: float = Field(
        ...,
        ge=0.0,
        description="Total cumulative distance travelled in nautical miles",
        examples=[16.2],
    )
    elapsed_time_minutes: float = Field(
        ...,
        ge=0.0,
        description="Total elapsed trip duration in minutes",
        examples=[120.0],
    )
    track_points_count: int = Field(
        ...,
        ge=1,
        description="Total count of GPS track points recorded during the voyage",
        examples=[10],
    )
    status: str = Field(
        ...,
        description="Trip status ('active', 'completed', 'cancelled')",
        examples=["active"],
    )


class TripHistoryItem(BaseModel):
    """Lightweight trip representation for history and list views."""

    trip_id: str = Field(..., description="Unique trip identifier")
    status: str = Field(..., description="Trip status ('active', 'completed', 'cancelled')")
    start_position: Coordinate = Field(..., description="Starting coordinate of the voyage")
    destination: Coordinate = Field(..., description="Destination coordinate of the voyage")
    distance_travelled_km: float = Field(..., description="Total cumulative distance travelled in km")
    distance_travelled_nm: float = Field(..., description="Total cumulative distance travelled in NM")
    elapsed_time_minutes: float = Field(..., description="Total duration in minutes")
    started_at: datetime = Field(..., description="Timestamp when the voyage started")
    completed_at: Optional[datetime] = Field(default=None, description="Timestamp when voyage completed")
    track_points_count: int = Field(..., description="Count of GPS track points recorded")


class TripHistoryResponse(BaseModel):
    """Paginated list of recorded voyages."""

    trips: List[TripHistoryItem] = Field(..., description="List of recorded trip summaries")
    total: int = Field(..., ge=0, description="Total count of matching trips")
    limit: int = Field(..., ge=1, description="Requested page limit")
    offset: int = Field(..., ge=0, description="Requested page offset")


class TripTrackResponse(BaseModel):
    """Ordered GPS track point history for a trip."""

    trip_id: str = Field(..., description="Unique trip identifier")
    track_points: List[TripTrackPoint] = Field(
        ..., description="Ordered list of GPS track points in ascending sequence order"
    )


class TripDeleteResponse(BaseModel):
    """Response returned upon successful trip deletion."""

    message: str = Field(..., description="Confirmation message")
    trip_id: str = Field(..., description="ID of deleted trip")


class TripResponse(BaseModel):
    """Full response payload for trip tracking, including current navigation metrics."""

    trip_id: str = Field(..., description="Unique trip identifier")
    status: str = Field(
        ...,
        description="Current trip status ('active', 'completed', 'cancelled')",
        examples=["active"],
    )
    start_position: Coordinate = Field(..., description="Origin coordinate of the trip")
    current_position: Coordinate = Field(..., description="Latest recorded coordinate of the vessel")
    destination: Coordinate = Field(..., description="Final destination coordinate")
    distance_travelled_km: float = Field(
        ...,
        ge=0.0,
        description="Cumulative distance travelled in kilometers along the GPS path",
        examples=[30.0],
    )
    distance_travelled_nm: float = Field(
        ...,
        ge=0.0,
        description="Cumulative distance travelled in nautical miles along the GPS path",
        examples=[16.2],
    )
    elapsed_time_minutes: float = Field(
        ...,
        ge=0.0,
        description="Elapsed trip duration in minutes",
        examples=[120.0],
    )
    track_points_count: int = Field(
        ...,
        ge=1,
        description="Total count of GPS track points recorded",
        examples=[4],
    )
    navigation_state: NavigationState = Field(
        ...,
        description="Live navigation state computed by NavigationService",
    )
    track_points: List[TripTrackPoint] = Field(
        default_factory=list,
        description="Ordered sequence of GPS track points recorded during the voyage",
    )
    return_navigation_state: Optional[ReturnNavigationState] = Field(
        default=None,
        description="Active return navigation state if return mode has been initiated",
    )
