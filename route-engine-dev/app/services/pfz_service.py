"""PFZ business logic service for Indian marine Potential Fishing Zone advisories and Route Engine integration."""

from typing import List, Optional, Tuple
from app.models.pfz import (
    PFZDatasetStatus,
    PFZNearbyZone,
    PFZObservation,
    PFZRouteTarget,
    PFZRouteTargetRequest,
    PFZRouteTargetResponse,
    PFZStatus,
    PFZZone,
)
from app.models.request import Coordinate
from app.repositories.pfz_repository import (
    PFZRepository,
    get_default_pfz_repository,
)
from app.services.geo_service import GeoService


class PFZZoneNotFoundError(Exception):
    """Raised when a requested pfz_id is not found in the repository."""

    pass


class PFZService:
    """Service orchestrating Potential Fishing Zone queries, ranking, and Route Engine destination targeting."""

    def __init__(
        self,
        repository: Optional[PFZRepository] = None,
        adapter: Optional[Any] = None,
    ) -> None:
        """Initialize PFZService with repository and adapter dependencies.

        Args:
            repository: Underlying spatial PFZ repository. Defaults to shared SQLite repository.
            adapter: Upstream PFZ provider adapter.
        """
        self._repository = repository or get_default_pfz_repository()
        self._adapter = adapter

    def get_feed_status(self) -> PFZStatus:
        """Query operational status from adapter if configured, else repository."""
        if self._adapter is not None:
            return self._adapter.get_feed_status()
        return self._repository.get_status()

    def save_zone(self, zone: PFZZone) -> PFZZone:
        """Persist or update a PFZ zone."""
        return self._repository.save_zone(zone)

    def get_zone(self, pfz_id: str) -> PFZZone:
        """Retrieve a PFZ zone by ID.

        Raises:
            PFZZoneNotFoundError: If zone does not exist.
        """
        zone = self._repository.get_zone(pfz_id)
        if zone is None:
            raise PFZZoneNotFoundError(f"PFZ zone with ID '{pfz_id}' was not found.")
        return zone

    def list_zones(
        self,
        limit: int = 50,
        offset: int = 0,
        min_confidence: Optional[float] = None,
        valid_only: bool = False,
    ) -> Tuple[List[PFZZone], int]:
        """List registered PFZ zones with optional confidence and validity filters."""
        return self._repository.list_zones(
            limit=limit,
            offset=offset,
            min_confidence=min_confidence,
            valid_only=valid_only,
        )

    def delete_zone(self, pfz_id: str) -> bool:
        """Delete a PFZ zone by ID.

        Raises:
            PFZZoneNotFoundError: If zone does not exist.
        """
        deleted = self._repository.delete_zone(pfz_id)
        if not deleted:
            raise PFZZoneNotFoundError(f"PFZ zone with ID '{pfz_id}' was not found.")
        return True

    def find_nearby_zones(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 100.0,
        limit: int = 50,
        min_confidence: Optional[float] = None,
    ) -> List[PFZNearbyZone]:
        """Find PFZ zones within a search radius from a reference GPS coordinate.

        Args:
            latitude: Reference latitude (-90 to 90).
            longitude: Reference longitude (-180 to 180).
            radius_km: Search radius in kilometers (> 0).
            limit: Maximum results to return (> 0).
            min_confidence: Optional confidence filter (0.0 to 1.0).

        Returns:
            List of PFZNearbyZone items sorted by distance ascending.
        """
        if not (-90.0 <= latitude <= 90.0):
            raise ValueError(f"Latitude {latitude} out of valid range [-90.0, 90.0].")
        if not (-180.0 <= longitude <= 180.0):
            raise ValueError(f"Longitude {longitude} out of valid range [-180.0, 180.0].")
        if radius_km <= 0:
            raise ValueError(f"Radius must be greater than zero, got {radius_km}.")
        if limit <= 0:
            raise ValueError(f"Limit must be greater than zero, got {limit}.")

        zones, _ = self._repository.list_zones(
            limit=1000, offset=0, min_confidence=min_confidence, valid_only=False
        )

        origin = Coordinate(latitude=latitude, longitude=longitude)
        nearby_list: List[PFZNearbyZone] = []

        for z in zones:
            dest_coord = z.centroid
            if dest_coord is None:
                continue

            dist_km = GeoService.haversine_distance_km(origin, dest_coord)
            if dist_km <= radius_km:
                dist_nm = GeoService.km_to_nautical_miles(dist_km)
                bearing = GeoService.initial_bearing_degrees(origin, dest_coord)

                nearby_list.append(
                    PFZNearbyZone(
                        zone=z,
                        distance_km=dist_km,
                        distance_nm=dist_nm,
                        bearing_degrees=bearing,
                        destination=dest_coord,
                    )
                )

        nearby_list.sort(key=lambda item: item.distance_km)
        return nearby_list[:limit]

    def get_best_pfz_targets(
        self, request: PFZRouteTargetRequest
    ) -> PFZRouteTargetResponse:
        """Evaluate and rank potential fishing zones as candidate destinations for the Route Engine.

        Scoring Formula:
            S = w_suitability * suitability_score + w_confidence * (confidence * 100) + w_distance * distance_score

            Where:
            - distance_score = max(0, 100 * (1 - distance_km / radius_km))
            - Weights depend deterministically on request.objective:
              * 'balanced' (default): w_s = 0.45, w_c = 0.25, w_d = 0.30
              * 'highest_potential':  w_s = 0.70, w_c = 0.20, w_d = 0.10
              * 'nearest_distance':   w_s = 0.20, w_c = 0.10, w_d = 0.70
              * 'high_confidence':    w_s = 0.30, w_c = 0.60, w_d = 0.10

        Args:
            request: PFZRouteTargetRequest containing vessel position, radius, vessel speed, and objective.

        Returns:
            PFZRouteTargetResponse with ranked candidate destinations.
        """
        origin = request.current_position
        status = self.get_pfz_status()

        nearby_zones = self.find_nearby_zones(
            latitude=origin.latitude,
            longitude=origin.longitude,
            radius_km=request.radius_km,
            limit=500,
            min_confidence=request.minimum_confidence,
        )

        if not nearby_zones:
            return PFZRouteTargetResponse(
                origin=origin,
                total_candidates=0,
                targets=[],
                dataset_status=status.dataset_status,
                scoring_formula=(
                    "ranking_score = (w_suitability * suitability) + (w_confidence * (confidence * 100)) + (w_distance * distance_factor)"
                ),
            )

        # Determine weighting profile
        obj = (request.objective or "balanced").lower()
        if obj == "highest_potential":
            ws, wc, wd = 0.70, 0.20, 0.10
        elif obj == "nearest_distance":
            ws, wc, wd = 0.20, 0.10, 0.70
        elif obj == "high_confidence":
            ws, wc, wd = 0.30, 0.60, 0.10
        else:  # 'balanced'
            ws, wc, wd = 0.45, 0.25, 0.30

        vessel_speed = request.vessel.speed_knots if request.vessel else None

        candidates: List[PFZRouteTarget] = []
        for item in nearby_zones:
            z = item.zone
            dist_km = item.distance_km
            dist_nm = item.distance_nm

            # Base components
            suitability = z.suitability_score if z.suitability_score is not None else 50.0
            confidence_val = (z.confidence * 100.0) if z.confidence is not None else 50.0
            dist_factor = max(0.0, 100.0 * (1.0 - (dist_km / request.radius_km)))

            # Composite ranking score (0 to 100)
            composite_score = (ws * suitability) + (wc * confidence_val) + (wd * dist_factor)
            composite_score = max(0.0, min(100.0, composite_score))

            # Estimated travel time in minutes
            eta_mins = None
            if vessel_speed and vessel_speed > 0:
                eta_mins = round((dist_nm / vessel_speed) * 60.0, 1)

            candidates.append(
                PFZRouteTarget(
                    pfz_id=z.pfz_id,
                    name=z.name,
                    destination=item.destination,
                    distance_km=round(dist_km, 2),
                    distance_nm=round(dist_nm, 2),
                    bearing_degrees=round(item.bearing_degrees, 1),
                    suitability_score=z.suitability_score,
                    confidence=z.confidence,
                    ranking_score=round(composite_score, 1),
                    estimated_travel_time_minutes=eta_mins,
                    source=z.source,
                    valid_until=z.valid_until,
                    properties=z.properties,
                )
            )

        # Sort strictly by ranking_score descending (best destination first)
        candidates.sort(key=lambda t: t.ranking_score, reverse=True)
        top_targets = candidates[: request.limit]

        return PFZRouteTargetResponse(
            origin=origin,
            total_candidates=len(candidates),
            targets=top_targets,
            dataset_status=status.dataset_status,
            scoring_formula=(
                f"ranking_score = ({ws:.2f} * suitability) + ({wc:.2f} * confidence_100) + ({wd:.2f} * distance_factor)"
            ),
        )

    def get_pfz_status(self) -> PFZStatus:
        """Query operational dataset status and advisory freshness."""
        return self._repository.get_status()

    def save_observation(self, observation: PFZObservation) -> PFZObservation:
        """Persist a single prediction observation."""
        return self._repository.save_observation(observation)

    def get_observations(
        self, limit: int = 100, offset: int = 0
    ) -> List[PFZObservation]:
        """Retrieve prediction observations."""
        return self._repository.get_observations(limit=limit, offset=offset)


def get_pfz_service() -> PFZService:
    """FastAPI dependency provider for PFZService."""
    return PFZService(repository=get_default_pfz_repository())
