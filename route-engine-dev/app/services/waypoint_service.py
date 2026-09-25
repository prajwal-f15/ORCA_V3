"""Waypoint generation service for deterministic path interpolation."""

from typing import List
from app.models.request import Coordinate


class WaypointGenerator:
    """Generates ordered geographic waypoints along a voyage path."""

    @staticmethod
    def generate_linear_waypoints(
        start: Coordinate,
        destination: Coordinate,
        num_intermediate: int = 3,
    ) -> List[Coordinate]:
        """Generate ordered coordinates from start to destination using linear interpolation.

        Args:
            start: Origin Coordinate.
            destination: Destination Coordinate.
            num_intermediate: Number of intermediate waypoints to generate (must be >= 0).

        Returns:
            List of Coordinates starting with start, containing num_intermediate waypoints,
            and ending with destination.

        Raises:
            ValueError: If num_intermediate is negative.
        """
        if num_intermediate < 0:
            raise ValueError("Intermediate waypoint count must be greater than or equal to 0.")

        # Always start with exact start coordinate
        waypoints: List[Coordinate] = [
            Coordinate(latitude=round(start.latitude, 6), longitude=round(start.longitude, 6))
        ]

        if num_intermediate > 0:
            total_segments = num_intermediate + 1
            lat_delta = destination.latitude - start.latitude
            lon_delta = destination.longitude - start.longitude

            for i in range(1, num_intermediate + 1):
                fraction = i / total_segments
                inter_lat = start.latitude + (fraction * lat_delta)
                inter_lon = start.longitude + (fraction * lon_delta)

                waypoints.append(
                    Coordinate(
                        latitude=round(inter_lat, 6),
                        longitude=round(inter_lon, 6),
                    )
                )

        # Always end with exact destination coordinate
        waypoints.append(
            Coordinate(latitude=round(destination.latitude, 6), longitude=round(destination.longitude, 6))
        )

        return waypoints
