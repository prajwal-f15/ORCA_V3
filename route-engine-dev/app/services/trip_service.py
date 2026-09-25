"""Trip tracking business logic service for recording and calculating vessel voyages."""

from datetime import datetime, timezone
from typing import Optional
import uuid
from app.core.config import get_settings
from app.models.request import Coordinate, NavigationRequest
from app.models.response import NavigationState
from app.models.trip import (
    ReturnCancelResponse,
    ReturnNavigationState,
    ReturnTripRequest,
    ReturnUpdateRequest,
    TripDeleteResponse,
    TripHistoryItem,
    TripHistoryResponse,
    TripResponse,
    TripStartRequest,
    TripStatus,
    TripStopRequest,
    TripSummary,
    TripTrackPoint,
    TripTrackResponse,
    TripUpdateRequest,
)
from app.repositories.trip_repository import (
    TripRecord,
    TripRepository,
    get_default_trip_repository,
)
from app.services.geo_service import GeoService
from app.services.navigation_service import NavigationService
from app.services.return_service import (
    ReturnNavigationNotActiveError,
    ReturnService,
)


class TripNotFoundError(Exception):
    """Raised when a requested trip_id is not found in the repository."""

    pass


class TripInactiveError(Exception):
    """Raised when an operation is attempted on a non-active or completed trip."""

    pass


class InvalidTimestampError(Exception):
    """Raised when a GPS update contains a timestamp earlier than previous track points."""

    pass


def ensure_utc(dt: Optional[datetime]) -> datetime:
    """Normalize datetime to UTC timezone-aware datetime."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TripService:
    """Service orchestrating vessel voyage lifecycle, track points, and navigation metrics."""

    def __init__(
        self,
        repository: Optional[TripRepository] = None,
        navigation_service: Optional[NavigationService] = None,
        return_service: Optional[ReturnService] = None,
    ) -> None:
        """Initialize TripService with repository, navigation service, and return service dependencies.

        Args:
            repository: Trip persistence repository. Defaults to shared SQLiteTripRepository.
            navigation_service: Navigation state calculator service.
            return_service: Return navigation state calculator service.
        """
        self._repository = repository or get_default_trip_repository()
        self._navigation_service = navigation_service or NavigationService()
        self._return_service = return_service or ReturnService(
            navigation_service=self._navigation_service
        )
        self._settings = get_settings()

    def start_trip(self, request: TripStartRequest) -> TripResponse:
        """Initialize a new trip, recording start parameters and initial GPS track point.

        Args:
            request: Validated TripStartRequest containing origin, destination, and vessel specs.

        Returns:
            TripResponse representing the newly created active voyage.
        """
        trip_id = f"trip_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        start_ts = ensure_utc(request.timestamp)
        arrival_threshold_nm = (
            request.arrival_threshold_nm
            if request.arrival_threshold_nm is not None
            else getattr(self._settings, "DEFAULT_ARRIVAL_THRESHOLD_NM", 0.1)
        )

        first_track_point = TripTrackPoint(
            latitude=request.start.latitude,
            longitude=request.start.longitude,
            timestamp=start_ts,
            sequence_number=0,
        )

        # Compute initial navigation state at start position
        nav_req = NavigationRequest(
            current_position=request.start,
            start=request.start,
            destination=request.destination,
            vessel=request.vessel,
            waypoints=request.waypoints,
            arrival_threshold_nm=arrival_threshold_nm,
        )
        nav_state = self._navigation_service.calculate_navigation_state(nav_req)

        trip_record = TripRecord(
            trip_id=trip_id,
            start_position=request.start,
            current_position=request.start,
            destination=request.destination,
            vessel=request.vessel,
            waypoints=request.waypoints,
            arrival_threshold_nm=arrival_threshold_nm,
            status=TripStatus.ACTIVE.value,
            track_points=[first_track_point],
            distance_travelled_km=0.0,
            start_timestamp=start_ts,
            last_timestamp=start_ts,
            navigation_state=nav_state,
        )

        self._repository.save(trip_record)
        return self._to_response(trip_record)

    def update_trip(self, trip_id: str, request: TripUpdateRequest) -> TripResponse:
        """Record a live GPS position update for an active trip.

        Args:
            trip_id: Unique identifier of the active trip.
            request: Validated TripUpdateRequest containing new coordinates and timestamp.

        Returns:
            Updated TripResponse with cumulative travelled distance, elapsed time, and NavigationState.

        Raises:
            TripNotFoundError: If trip_id does not exist.
            TripInactiveError: If trip is completed or cancelled.
            InvalidTimestampError: If update timestamp is older than the last recorded track point.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        if trip.status != TripStatus.ACTIVE.value:
            raise TripInactiveError(
                f"Trip '{trip_id}' is {trip.status} and cannot receive GPS updates."
            )

        update_ts = ensure_utc(request.timestamp)
        if update_ts < trip.last_timestamp:
            raise InvalidTimestampError(
                f"Update timestamp ({update_ts.isoformat()}) cannot be earlier than "
                f"previous track point timestamp ({trip.last_timestamp.isoformat()})."
            )

        # Calculate incremental distance between previous GPS point and new GPS point
        if trip.track_points:
            prev_point = Coordinate(
                latitude=trip.track_points[-1].latitude,
                longitude=trip.track_points[-1].longitude,
            )
        else:
            prev_point = trip.current_position
        new_point = request.current_position
        segment_km = GeoService.haversine_distance_km(prev_point, new_point)

        # Accumulate strictly segment distances
        trip.distance_travelled_km = round(trip.distance_travelled_km + segment_km, 4)
        trip.current_position = new_point
        trip.last_timestamp = update_ts
        trip.track_points.append(
            TripTrackPoint(
                latitude=new_point.latitude,
                longitude=new_point.longitude,
                timestamp=update_ts,
                sequence_number=len(trip.track_points),
            )
        )

        # Recompute live navigation state for updated position
        nav_req = NavigationRequest(
            current_position=new_point,
            start=trip.start_position,
            destination=trip.destination,
            vessel=trip.vessel,
            waypoints=trip.waypoints,
            arrival_threshold_nm=trip.arrival_threshold_nm,
        )
        trip.navigation_state = self._navigation_service.calculate_navigation_state(nav_req)

        # If return navigation is active, update return navigation state as well
        if trip.return_status is not None and trip.return_destination is not None:
            self._return_service.calculate_return_state(
                trip=trip,
                current_position=new_point,
                timestamp=update_ts,
            )

        self._repository.save(trip)
        return self._to_response(trip)

    def stop_trip(
        self, trip_id: str, request: Optional[TripStopRequest] = None
    ) -> TripResponse:
        """Stop and mark a voyage as completed.

        Args:
            trip_id: Unique identifier of the trip.
            request: Optional final coordinate and completion timestamp.

        Returns:
            TripResponse with status 'completed'.

        Raises:
            TripNotFoundError: If trip_id does not exist.
            TripInactiveError: If trip is already completed or cancelled.
            InvalidTimestampError: If stop timestamp is older than previous track points.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        if trip.status == TripStatus.COMPLETED.value:
            raise TripInactiveError(f"Trip '{trip_id}' is already completed.")

        stop_ts = ensure_utc(request.timestamp if request else None)
        if stop_ts < trip.last_timestamp:
            raise InvalidTimestampError(
                f"Stop timestamp ({stop_ts.isoformat()}) cannot be earlier than "
                f"previous track point timestamp ({trip.last_timestamp.isoformat()})."
            )

        if request and request.current_position is not None:
            final_point = request.current_position
            prev_point = Coordinate(
                latitude=trip.track_points[-1].latitude,
                longitude=trip.track_points[-1].longitude,
            )
            segment_km = GeoService.haversine_distance_km(prev_point, final_point)
            if segment_km > 0.0:
                trip.distance_travelled_km = round(trip.distance_travelled_km + segment_km, 4)
                trip.current_position = final_point
                trip.track_points.append(
                    TripTrackPoint(
                        latitude=final_point.latitude,
                        longitude=final_point.longitude,
                        timestamp=stop_ts,
                        sequence_number=len(trip.track_points),
                    )
                )
            trip.last_timestamp = stop_ts
        else:
            trip.last_timestamp = stop_ts

        trip.status = TripStatus.COMPLETED.value
        trip.completed_at = stop_ts

        # Compute final navigation state
        nav_req = NavigationRequest(
            current_position=trip.current_position,
            start=trip.start_position,
            destination=trip.destination,
            vessel=trip.vessel,
            waypoints=trip.waypoints,
            arrival_threshold_nm=trip.arrival_threshold_nm,
        )
        trip.navigation_state = self._navigation_service.calculate_navigation_state(nav_req)

        self._repository.save(trip)
        return self._to_response(trip)

    def get_trip(self, trip_id: str) -> TripResponse:
        """Retrieve full details of a recorded trip, including all track points.

        Args:
            trip_id: Unique identifier of the trip.

        Returns:
            TripResponse corresponding to the requested trip.

        Raises:
            TripNotFoundError: If trip_id does not exist.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")
        return self._to_response(trip)

    def get_trip_summary(self, trip_id: str) -> TripSummary:
        """Retrieve high-level summary metrics of a recorded trip.

        Args:
            trip_id: Unique identifier of the trip.

        Returns:
            TripSummary with distances, elapsed time, and count of track points.

        Raises:
            TripNotFoundError: If trip_id does not exist.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        elapsed_seconds = max(
            0.0, (trip.last_timestamp - trip.start_timestamp).total_seconds()
        )
        elapsed_minutes = round(elapsed_seconds / 60.0, 2)
        dist_nm = GeoService.km_to_nautical_miles(trip.distance_travelled_km)

        return TripSummary(
            trip_id=trip.trip_id,
            start_position=trip.start_position,
            current_position=trip.current_position,
            destination=trip.destination,
            distance_travelled_km=trip.distance_travelled_km,
            distance_travelled_nm=dist_nm,
            elapsed_time_minutes=elapsed_minutes,
            track_points_count=len(trip.track_points),
            status=trip.status,
        )

    def list_trips(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TripHistoryResponse:
        """Retrieve a paginated list of saved trips.

        Args:
            status: Optional filter by status ('active', 'completed', 'cancelled').
            limit: Maximum number of trips to return.
            offset: Number of items to skip.

        Returns:
            TripHistoryResponse with lightweight TripHistoryItems.
        """
        trip_records, total = self._repository.list_trips(
            status=status, limit=limit, offset=offset
        )
        history_items: list[TripHistoryItem] = []
        for trip in trip_records:
            elapsed_seconds = max(
                0.0, (trip.last_timestamp - trip.start_timestamp).total_seconds()
            )
            elapsed_minutes = round(elapsed_seconds / 60.0, 2)
            dist_nm = GeoService.km_to_nautical_miles(trip.distance_travelled_km)

            history_items.append(
                TripHistoryItem(
                    trip_id=trip.trip_id,
                    status=trip.status,
                    start_position=trip.start_position,
                    destination=trip.destination,
                    distance_travelled_km=trip.distance_travelled_km,
                    distance_travelled_nm=dist_nm,
                    elapsed_time_minutes=elapsed_minutes,
                    started_at=trip.start_timestamp,
                    completed_at=trip.completed_at,
                    track_points_count=len(trip.track_points),
                )
            )

        return TripHistoryResponse(
            trips=history_items,
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_trip_track(self, trip_id: str) -> TripTrackResponse:
        """Retrieve ordered GPS track points for a trip.

        Args:
            trip_id: Unique identifier of the trip.

        Returns:
            TripTrackResponse containing ordered track points list.

        Raises:
            TripNotFoundError: If trip_id does not exist.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        track_points = self._repository.get_track_points(trip_id)
        return TripTrackResponse(trip_id=trip_id, track_points=track_points)

    def delete_trip(self, trip_id: str) -> TripDeleteResponse:
        """Delete a trip and all its associated track points.

        Args:
            trip_id: Unique identifier of the trip to delete.

        Returns:
            TripDeleteResponse with deletion status.

        Raises:
            TripNotFoundError: If trip_id does not exist.
        """
        deleted = self._repository.delete(trip_id)
        if not deleted:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")
        return TripDeleteResponse(
            message=f"Trip '{trip_id}' was successfully deleted.",
            trip_id=trip_id,
        )

    # =========================================================================
    # RETURN NAVIGATION METHODS
    # =========================================================================

    def start_return(
        self, trip_id: str, request: ReturnTripRequest
    ) -> ReturnNavigationState:
        """Switch active trip into return navigation mode toward start or harbour.

        Args:
            trip_id: Unique identifier of the active trip.
            request: Validated ReturnTripRequest.

        Returns:
            ReturnNavigationState towards the return target.

        Raises:
            TripNotFoundError: If trip_id is not found.
            TripInactiveError: If trip is not in 'active' status.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        if trip.status != TripStatus.ACTIVE.value:
            raise TripInactiveError(
                f"Cannot start return navigation for trip '{trip_id}' because trip is {trip.status}."
            )

        return_state = self._return_service.start_return(trip=trip, request=request)
        self._repository.save(trip)
        return return_state

    def update_return(
        self, trip_id: str, request: ReturnUpdateRequest
    ) -> ReturnNavigationState:
        """Record GPS update during return navigation, accumulating distance and updating state.

        Args:
            trip_id: Unique identifier of the active trip.
            request: Validated ReturnUpdateRequest.

        Returns:
            Updated ReturnNavigationState.

        Raises:
            TripNotFoundError: If trip_id is not found.
            TripInactiveError: If trip is not active.
            ReturnNavigationNotActiveError: If return navigation has not been started.
            InvalidTimestampError: If update timestamp is older than last track point.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        if trip.status != TripStatus.ACTIVE.value:
            raise TripInactiveError(
                f"Trip '{trip_id}' is {trip.status} and cannot receive GPS updates."
            )

        if not trip.return_status or not trip.return_destination:
            raise ReturnNavigationNotActiveError(
                f"Return navigation is not active for trip '{trip_id}'."
            )

        update_ts = ensure_utc(request.timestamp)
        if update_ts < trip.last_timestamp:
            raise InvalidTimestampError(
                f"Update timestamp ({update_ts.isoformat()}) cannot be earlier than "
                f"previous track point timestamp ({trip.last_timestamp.isoformat()})."
            )

        if trip.track_points:
            prev_point = Coordinate(
                latitude=trip.track_points[-1].latitude,
                longitude=trip.track_points[-1].longitude,
            )
        else:
            prev_point = trip.current_position
        new_point = request.current_position
        segment_km = GeoService.haversine_distance_km(prev_point, new_point)

        # Accumulate trip distance along entire path
        trip.distance_travelled_km = round(trip.distance_travelled_km + segment_km, 4)
        trip.current_position = new_point
        trip.last_timestamp = update_ts
        trip.track_points.append(
            TripTrackPoint(
                latitude=new_point.latitude,
                longitude=new_point.longitude,
                timestamp=update_ts,
                sequence_number=len(trip.track_points),
            )
        )

        # Recompute normal navigation state
        nav_req = NavigationRequest(
            current_position=new_point,
            start=trip.start_position,
            destination=trip.destination,
            vessel=trip.vessel,
            waypoints=trip.waypoints,
            arrival_threshold_nm=trip.arrival_threshold_nm,
        )
        trip.navigation_state = self._navigation_service.calculate_navigation_state(nav_req)

        # Recompute return navigation state
        return_state = self._return_service.calculate_return_state(
            trip=trip,
            current_position=new_point,
            timestamp=update_ts,
        )

        self._repository.save(trip)
        return return_state

    def cancel_return(self, trip_id: str) -> ReturnCancelResponse:
        """Cancel active return navigation on a trip while leaving trip active.

        Args:
            trip_id: Unique identifier of the trip.

        Returns:
            ReturnCancelResponse confirmation.

        Raises:
            TripNotFoundError: If trip_id is not found.
            TripInactiveError: If trip is not active.
            ReturnNavigationNotActiveError: If return navigation is not active.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        if trip.status != TripStatus.ACTIVE.value:
            raise TripInactiveError(
                f"Trip '{trip_id}' is {trip.status} and cannot be modified."
            )

        if not trip.return_status:
            raise ReturnNavigationNotActiveError(
                f"Return navigation is not active for trip '{trip_id}'."
            )

        self._return_service.cancel_return(trip)
        self._repository.save(trip)
        return ReturnCancelResponse(
            message=f"Return navigation for trip '{trip_id}' has been cancelled.",
            trip_id=trip_id,
        )

    def get_return_state(self, trip_id: str) -> ReturnNavigationState:
        """Retrieve active return navigation state for a trip.

        Args:
            trip_id: Unique identifier of the trip.

        Returns:
            ReturnNavigationState towards the return destination.

        Raises:
            TripNotFoundError: If trip_id is not found.
            ReturnNavigationNotActiveError: If return navigation has not been started.
        """
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip with ID '{trip_id}' was not found.")

        if not trip.return_status or not trip.return_destination:
            raise ReturnNavigationNotActiveError(
                f"Return navigation has not been started for trip '{trip_id}'."
            )

        return self._return_service.calculate_return_state(trip)

    def _to_response(self, trip: TripRecord) -> TripResponse:
        """Transform internal TripRecord entity into external TripResponse DTO."""
        elapsed_seconds = max(
            0.0, (trip.last_timestamp - trip.start_timestamp).total_seconds()
        )
        elapsed_minutes = round(elapsed_seconds / 60.0, 2)
        dist_nm = GeoService.km_to_nautical_miles(trip.distance_travelled_km)

        nav_state = trip.navigation_state
        if nav_state is None:
            nav_req = NavigationRequest(
                current_position=trip.current_position,
                start=trip.start_position,
                destination=trip.destination,
                vessel=trip.vessel,
                waypoints=trip.waypoints,
                arrival_threshold_nm=trip.arrival_threshold_nm,
            )
            nav_state = self._navigation_service.calculate_navigation_state(nav_req)

        return_nav_state = None
        if trip.return_status is not None and trip.return_destination is not None:
            return_nav_state = self._return_service.calculate_return_state(trip)

        return TripResponse(
            trip_id=trip.trip_id,
            status=trip.status,
            start_position=trip.start_position,
            current_position=trip.current_position,
            destination=trip.destination,
            distance_travelled_km=trip.distance_travelled_km,
            distance_travelled_nm=dist_nm,
            elapsed_time_minutes=elapsed_minutes,
            track_points_count=len(trip.track_points),
            navigation_state=nav_state,
            track_points=trip.track_points,
            return_navigation_state=return_nav_state,
        )


def get_trip_service() -> TripService:
    """FastAPI dependency provider for TripService."""
    return TripService(
        repository=get_default_trip_repository(),
        navigation_service=NavigationService(),
        return_service=ReturnService(navigation_service=NavigationService()),
    )
