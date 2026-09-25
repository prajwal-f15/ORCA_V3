"""Geographic calculation module for maritime distance, bearing, and ETA computation."""

import math
from typing import Tuple
from app.models.request import Coordinate

# Earth mean radius in kilometers (WGS-84 spherical approximation)
EARTH_RADIUS_KM: float = 6371.0

# Standard conversion: 1 nautical mile = 1.852 kilometers
KM_PER_NAUTICAL_MILE: float = 1.852


class GeoService:
    """Service providing geodesic and maritime kinematic calculations."""

    @staticmethod
    def haversine_distance_km(coord1: Coordinate, coord2: Coordinate) -> float:
        """Calculate great-circle distance between two GPS coordinates using Haversine formula.

        Args:
            coord1: Origin Coordinate (latitude, longitude).
            coord2: Destination Coordinate (latitude, longitude).

        Returns:
            Great-circle distance in kilometers (rounded to 4 decimal places).
        """
        # Identical coordinates check
        if (
            math.isclose(coord1.latitude, coord2.latitude, abs_tol=1e-9)
            and math.isclose(coord1.longitude, coord2.longitude, abs_tol=1e-9)
        ):
            return 0.0

        lat1_rad = math.radians(coord1.latitude)
        lon1_rad = math.radians(coord1.longitude)
        lat2_rad = math.radians(coord2.latitude)
        lon2_rad = math.radians(coord2.longitude)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
        )
        # Numerical safeguard for floating-point inaccuracies
        c = 2.0 * math.atan2(math.sqrt(min(1.0, max(0.0, a))), math.sqrt(1.0 - min(1.0, max(0.0, a))))

        distance_km = EARTH_RADIUS_KM * c
        return round(distance_km, 4)

    @staticmethod
    def km_to_nautical_miles(distance_km: float) -> float:
        """Convert kilometers to nautical miles using standard 1 NM = 1.852 km.

        Args:
            distance_km: Distance in kilometers.

        Returns:
            Distance in nautical miles (rounded to 4 decimal places).
        """
        if distance_km <= 0.0:
            return 0.0
        return round(distance_km / KM_PER_NAUTICAL_MILE, 4)

    @staticmethod
    def calculate_eta_minutes(distance_nm: float, speed_knots: float) -> float:
        """Calculate estimated travel time in minutes based on distance and vessel speed.

        Args:
            distance_nm: Total distance in nautical miles.
            speed_knots: Vessel speed in knots (must be > 0).

        Returns:
            Estimated travel duration in minutes (rounded to 2 decimal places).

        Raises:
            ValueError: If speed_knots is <= 0.
        """
        if speed_knots <= 0:
            raise ValueError("Vessel speed must be greater than zero knots.")

        if distance_nm <= 0.0:
            return 0.0

        time_hours = distance_nm / speed_knots
        time_minutes = time_hours * 60.0
        return round(time_minutes, 2)

    @staticmethod
    def initial_bearing_degrees(coord1: Coordinate, coord2: Coordinate) -> float:
        """Calculate initial great-circle bearing (forward azimuth) from coord1 to coord2 in degrees (0 to 359.99°).

        Args:
            coord1: Starting Coordinate (latitude, longitude).
            coord2: Destination Coordinate (latitude, longitude).

        Returns:
            Bearing in degrees normalized to [0.0, 360.0).
        """
        if (
            math.isclose(coord1.latitude, coord2.latitude, abs_tol=1e-9)
            and math.isclose(coord1.longitude, coord2.longitude, abs_tol=1e-9)
        ):
            return 0.0

        lat1_rad = math.radians(coord1.latitude)
        lat2_rad = math.radians(coord2.latitude)
        dlon_rad = math.radians(coord2.longitude - coord1.longitude)

        y = math.sin(dlon_rad) * math.cos(lat2_rad)
        x = (
            math.cos(lat1_rad) * math.sin(lat2_rad)
            - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)
        )

        bearing_rad = math.atan2(y, x)
        bearing_deg = (math.degrees(bearing_rad) + 360.0) % 360.0
        return round(bearing_deg, 2)

    @classmethod
    def calculate_metrics(
        cls,
        start: Coordinate,
        destination: Coordinate,
        speed_knots: float,
    ) -> Tuple[float, float, float]:
        """Compute full geographic metrics: distance (km, nm) and ETA in minutes.

        Args:
            start: Origin coordinate.
            destination: Destination coordinate.
            speed_knots: Speed in knots.

        Returns:
            Tuple of (distance_km, distance_nm, estimated_time_minutes).
        """
        dist_km = cls.haversine_distance_km(start, destination)
        dist_nm = cls.km_to_nautical_miles(dist_km)
        eta_minutes = cls.calculate_eta_minutes(dist_nm, speed_knots)
        return dist_km, dist_nm, eta_minutes
