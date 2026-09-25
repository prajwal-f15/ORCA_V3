"""Return navigation service for vessel return-to-start and return-to-harbour routing."""

from datetime import datetime, timezone
from typing import Optional
from app.core.config import get_settings
from app.models.request import Coordinate
from app.models.trip import (
    ReturnMode,
    ReturnNavigationState,
    ReturnStatus,
    ReturnTripRequest,
)
from app.repositories.trip_repository import TripRecord
from app.services.geo_service import GeoService
from app.services.navigation_service import NavigationService


class ReturnNavigationNotActiveError(Exception):
    """Raised when an operation is performed on a trip with no active return navigation."""

    pass


class ReturnService:
    """Service computing return navigation kinematics, bearing, ETA, progress, and arrival."""

    def __init__(self, navigation_service: Optional[NavigationService] = None) -> None:
        """Initialize ReturnService with NavigationService dependency."""
        self._navigation_service = navigation_service or NavigationService()
        self._settings = get_settings()

    def start_return(
        self,
        trip: TripRecord,
        request: ReturnTripRequest,
        arrival_threshold_nm: Optional[float] = None,
    ) -> ReturnNavigationState:
        """Initialize return voyage navigation toward start or harbour coordinate.

        Args:
            trip: Active TripRecord domain entity.
            request: Validated ReturnTripRequest specifying mode and optional harbour coordinate.
            arrival_threshold_nm: Optional proximity arrival threshold in NM.

        Returns:
            ReturnNavigationState toward the determined return destination.
        """
        mode = request.mode if isinstance(request.mode, ReturnMode) else ReturnMode(request.mode)
        if mode == ReturnMode.START:
            return_destination = Coordinate(
                latitude=trip.start_position.latitude,
                longitude=trip.start_position.longitude,
            )
        elif mode == ReturnMode.HARBOUR:
            if request.harbour is None:
                raise ValueError("Harbour coordinate is required when return mode is 'harbour'.")
            return_destination = Coordinate(
                latitude=request.harbour.latitude,
                longitude=request.harbour.longitude,
            )
        else:
            raise ValueError(f"Unsupported return mode '{mode}'.")

        threshold_nm = (
            arrival_threshold_nm
            if arrival_threshold_nm is not None
            else trip.arrival_threshold_nm
        )

        return_origin = Coordinate(
            latitude=trip.current_position.latitude,
            longitude=trip.current_position.longitude,
        )

        # Calculate initial return metrics
        rem_km = GeoService.haversine_distance_km(trip.current_position, return_destination)
        rem_nm = GeoService.km_to_nautical_miles(rem_km)
        bearing = GeoService.initial_bearing_degrees(trip.current_position, return_destination)

        now_utc = datetime.now(timezone.utc)
        if rem_nm <= threshold_nm or rem_km == 0.0:
            status = ReturnStatus.RETURN_ARRIVED.value
            progress = 100.0
            eta_minutes = 0.0
            completed_at = now_utc
            rem_km = 0.0
            rem_nm = 0.0
        else:
            status = ReturnStatus.RETURNING.value
            progress = 0.0
            eta_minutes = GeoService.calculate_eta_minutes(rem_nm, trip.vessel.speed_knots)
            completed_at = None

        # Update TripRecord return state
        trip.return_mode = mode.value
        trip.return_destination = return_destination
        trip.return_origin_position = return_origin
        trip.return_status = status
        trip.return_started_at = now_utc
        trip.return_completed_at = completed_at

        return ReturnNavigationState(
            trip_id=trip.trip_id,
            return_mode=mode.value,
            return_destination=return_destination,
            current_position=trip.current_position,
            remaining_distance_km=round(rem_km, 4),
            remaining_distance_nm=round(rem_nm, 4),
            estimated_time_remaining_minutes=round(eta_minutes, 2),
            bearing_degrees=round(bearing, 2),
            progress_percent=round(progress, 2),
            status=status,
        )

    def calculate_return_state(
        self,
        trip: TripRecord,
        current_position: Optional[Coordinate] = None,
        arrival_threshold_nm: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> ReturnNavigationState:
        """Compute updated live return navigation metrics from vessel GPS position.

        Args:
            trip: TripRecord with active return navigation.
            current_position: Optional latest GPS coordinate (defaults to trip.current_position).
            arrival_threshold_nm: Proximity threshold in nautical miles.
            timestamp: Update timestamp.

        Returns:
            Updated ReturnNavigationState.
        """
        if not trip.return_mode or not trip.return_destination:
            raise ReturnNavigationNotActiveError(
                f"Return navigation is not active for trip '{trip.trip_id}'."
            )

        pos = current_position or trip.current_position
        dest = trip.return_destination
        threshold_nm = (
            arrival_threshold_nm
            if arrival_threshold_nm is not None
            else trip.arrival_threshold_nm
        )

        rem_km = GeoService.haversine_distance_km(pos, dest)
        rem_nm = GeoService.km_to_nautical_miles(rem_km)
        bearing = GeoService.initial_bearing_degrees(pos, dest)

        # Calculate progress from return origin position to return destination
        if trip.return_origin_position:
            total_return_km = GeoService.haversine_distance_km(trip.return_origin_position, dest)
        else:
            total_return_km = rem_km

        now_utc = timestamp or datetime.now(timezone.utc)
        if rem_nm <= threshold_nm or total_return_km == 0.0:
            status = ReturnStatus.RETURN_ARRIVED.value
            progress = 100.0
            eta_minutes = 0.0
            rem_km = 0.0
            rem_nm = 0.0
            if trip.return_completed_at is None:
                trip.return_completed_at = now_utc
        else:
            status = ReturnStatus.RETURNING.value
            if total_return_km > 0.0:
                raw_progress = ((total_return_km - rem_km) / total_return_km) * 100.0
                progress = max(0.0, min(100.0, raw_progress))
            else:
                progress = 100.0
            eta_minutes = GeoService.calculate_eta_minutes(rem_nm, trip.vessel.speed_knots)

        trip.return_status = status

        return ReturnNavigationState(
            trip_id=trip.trip_id,
            return_mode=trip.return_mode,
            return_destination=dest,
            current_position=pos,
            remaining_distance_km=round(rem_km, 4),
            remaining_distance_nm=round(rem_nm, 4),
            estimated_time_remaining_minutes=round(eta_minutes, 2),
            bearing_degrees=round(bearing, 2),
            progress_percent=round(progress, 2),
            status=status,
        )

    def cancel_return(self, trip: TripRecord) -> None:
        """Cancel active return navigation on a trip without affecting base voyage parameters."""
        trip.return_mode = None
        trip.return_destination = None
        trip.return_status = None
        trip.return_started_at = None
        trip.return_completed_at = None
        trip.return_origin_position = None
