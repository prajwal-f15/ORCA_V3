"""Navigation service for calculating vessel navigation state, progress, bearing, and waypoint tracking."""

from typing import List, Optional
from app.core.config import get_settings
from app.models.request import Coordinate, NavigationRequest
from app.models.response import NavigationState
from app.services.geo_service import GeoService


class NavigationService:
    """Service providing real-time vessel navigation status and spatial metrics."""

    def __init__(self, default_arrival_threshold_nm: Optional[float] = None) -> None:
        """Initialize NavigationService with configurable arrival threshold.

        Args:
            default_arrival_threshold_nm: Configurable threshold in nautical miles.
                Defaults to setting DEFAULT_ARRIVAL_THRESHOLD_NM (0.1 NM).
        """
        settings = get_settings()
        self.default_arrival_threshold_nm = (
            default_arrival_threshold_nm
            if default_arrival_threshold_nm is not None
            else getattr(settings, "DEFAULT_ARRIVAL_THRESHOLD_NM", 0.1)
        )

    def determine_next_waypoint(
        self,
        current_position: Coordinate,
        destination: Coordinate,
        waypoints: List[Coordinate],
        arrival_threshold_nm: float,
    ) -> Optional[Coordinate]:
        """Deterministically determine the next upcoming waypoint from the planned list.

        Args:
            current_position: Current GPS coordinates of the vessel.
            destination: Final voyage destination coordinate.
            waypoints: Ordered list of route waypoints.
            arrival_threshold_nm: Threshold in NM for arrival at waypoints.

        Returns:
            Next Coordinate target along the route, or None if route is completed or waypoints empty.
        """
        if not waypoints:
            return None

        # If already arrived within destination threshold, no further waypoint
        remaining_to_dest_km = GeoService.haversine_distance_km(current_position, destination)
        remaining_to_dest_nm = GeoService.km_to_nautical_miles(remaining_to_dest_km)
        if remaining_to_dest_nm <= arrival_threshold_nm:
            return None

        # Find the waypoint closest to current position
        min_idx = 0
        min_dist_km = float("inf")
        for i, wp in enumerate(waypoints):
            dist_km = GeoService.haversine_distance_km(current_position, wp)
            if dist_km < min_dist_km:
                min_dist_km = dist_km
                min_idx = i

        min_dist_nm = GeoService.km_to_nautical_miles(min_dist_km)

        # If vessel has arrived at the closest waypoint (within threshold), advance to next
        if min_dist_nm <= arrival_threshold_nm:
            if min_idx + 1 < len(waypoints):
                return waypoints[min_idx + 1]
            return None

        # If vessel is between waypoints, check if it has passed min_idx towards min_idx + 1
        if min_idx < len(waypoints) - 1:
            next_wp = waypoints[min_idx + 1]
            dist_curr_to_next_km = GeoService.haversine_distance_km(current_position, next_wp)
            dist_closest_to_next_km = GeoService.haversine_distance_km(waypoints[min_idx], next_wp)
            if dist_curr_to_next_km < dist_closest_to_next_km:
                return next_wp

        return waypoints[min_idx]

    def calculate_navigation_state(
        self,
        request: NavigationRequest,
    ) -> NavigationState:
        """Calculate complete live navigation metrics for a given NavigationRequest.

        Args:
            request: Validated NavigationRequest.

        Returns:
            NavigationState containing spatial metrics, progress, bearing, next waypoint, and status.

        Raises:
            ValueError: If vessel speed is <= 0.
        """
        speed_knots = request.vessel.speed_knots
        if speed_knots <= 0:
            raise ValueError("Vessel speed must be greater than zero knots.")

        threshold_nm = (
            request.arrival_threshold_nm
            if request.arrival_threshold_nm is not None
            else self.default_arrival_threshold_nm
        )

        current_pos = request.current_position
        start = request.start
        dest = request.destination

        # 1. Total voyage distance from start to destination
        total_dist_km = GeoService.haversine_distance_km(start, dest)
        total_dist_nm = GeoService.km_to_nautical_miles(total_dist_km)

        # 2. Remaining distance to destination
        remaining_dist_km = GeoService.haversine_distance_km(current_pos, dest)
        remaining_dist_nm = GeoService.km_to_nautical_miles(remaining_dist_km)

        # 3. Distance from original start
        dist_from_start_km = GeoService.haversine_distance_km(current_pos, start)
        dist_from_start_nm = GeoService.km_to_nautical_miles(dist_from_start_km)

        # 4. Next waypoint determination
        next_wp = self.determine_next_waypoint(
            current_position=current_pos,
            destination=dest,
            waypoints=request.waypoints,
            arrival_threshold_nm=threshold_nm,
        )

        # 5. Bearing calculation toward next navigation target
        nav_target = next_wp if next_wp is not None else dest
        bearing = GeoService.initial_bearing_degrees(current_pos, nav_target)

        # 6. Status, Progress, and ETA calculation
        if remaining_dist_nm <= threshold_nm or total_dist_km == 0.0:
            status = "arrived"
            progress_percent = 100.0
            eta_minutes = 0.0
        else:
            if dist_from_start_nm <= threshold_nm:
                status = "not_started"
            else:
                status = "navigating"

            if total_dist_km > 0.0:
                raw_progress = ((total_dist_km - remaining_dist_km) / total_dist_km) * 100.0
                progress_percent = max(0.0, min(100.0, raw_progress))
            else:
                progress_percent = 100.0

            eta_minutes = GeoService.calculate_eta_minutes(remaining_dist_nm, speed_knots)

        return NavigationState(
            current_position=current_pos,
            destination=dest,
            remaining_distance_km=round(remaining_dist_km, 4),
            remaining_distance_nm=round(remaining_dist_nm, 4),
            estimated_time_remaining_minutes=round(eta_minutes, 2),
            bearing_degrees=round(bearing, 2),
            progress_percent=round(progress_percent, 2),
            next_waypoint=next_wp,
            total_waypoints=len(request.waypoints) if request.waypoints is not None else 0,
            status=status,
        )
