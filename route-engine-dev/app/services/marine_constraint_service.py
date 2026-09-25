"""Marine constraints and safety query service for ORCA Route Engine.

Provides spatial inspection for:
1. Restricted / No-Go marine zones (point-in-polygon, route segment intersection)
2. Bathymetry / sea depth soundings and depth contour queries
3. Vessel draft and under-keel clearance safety checks
"""

from typing import Any, List, Optional, Tuple
from app.models.geography import (
    CoordinateRestrictionCheckResult,
    DepthQueryResult,
    GeoFeature,
    GeoFeatureType,
    GeoNearbyFeature,
    GeometryType,
    RouteRestrictionCheckResult,
    VesselDraftSafetyResult,
)
from app.models.request import Coordinate
from app.repositories.geography_repository import (
    GeographyRepository,
    get_default_geography_repository,
)
from app.services.geo_service import GeoService


def point_in_ring(x: float, y: float, ring: List[List[float]]) -> bool:
    """Check if point (x=lon, y=lat) is inside a linear ring using standard ray casting.

    Args:
        x: Longitude in decimal degrees.
        y: Latitude in decimal degrees.
        ring: List of [longitude, latitude] coordinate pairs.

    Returns:
        True if (x, y) is inside the ring, False otherwise.
    """
    n = len(ring)
    if n < 3:
        return False
    inside = False
    p1x, p1y = ring[0][0], ring[0][1]
    for i in range(1, n + 1):
        p2x, p2y = ring[i % n][0], ring[i % n][1]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def point_in_polygon_geometry(lon: float, lat: float, rings: List[Any]) -> bool:
    """Check if (lon, lat) is inside a GeoJSON Polygon coordinates structure (outer ring + holes).

    Args:
        lon: Longitude in decimal degrees.
        lat: Latitude in decimal degrees.
        rings: Array of linear rings where rings[0] is exterior and rings[1:] are interior holes.

    Returns:
        True if point is inside exterior ring and outside all interior holes.
    """
    if not rings or not isinstance(rings, (list, tuple)):
        return False

    # Check outer ring
    outer_ring = rings[0]
    if not point_in_ring(lon, lat, outer_ring):
        return False

    # Check inner rings (holes)
    for hole in rings[1:]:
        if point_in_ring(lon, lat, hole):
            return False

    return True


def point_in_feature_geometry(lon: float, lat: float, feature: GeoFeature) -> bool:
    """Check if a coordinate point is located inside a GeoFeature's geometry."""
    geom = feature.geometry
    if not geom:
        return False

    if geom.type == GeometryType.POLYGON:
        return point_in_polygon_geometry(lon, lat, geom.coordinates)

    elif geom.type == GeometryType.MULTIPOLYGON:
        for poly_rings in geom.coordinates:
            if point_in_polygon_geometry(lon, lat, poly_rings):
                return True
        return False

    elif geom.type == GeometryType.POINT:
        coords = geom.coordinates
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            pt_lon, pt_lat = float(coords[0]), float(coords[1])
            # For point features, consider point match within ~0.001 deg (~100m)
            return abs(lon - pt_lon) < 0.001 and abs(lat - pt_lat) < 0.001

    return False


def _ccw(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> bool:
    """Counter-clockwise orientation test for 3 2D points."""
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
    d: Tuple[float, float],
) -> bool:
    """Test if line segment AB intersects line segment CD in 2D coordinates."""
    return (_ccw(a, c, d) != _ccw(b, c, d)) and (_ccw(a, b, c) != _ccw(a, b, d))


def line_intersects_ring(
    p1: Tuple[float, float], p2: Tuple[float, float], ring: List[List[float]]
) -> bool:
    """Check if line segment p1-p2 crosses any boundary segment of a linear ring."""
    n = len(ring)
    if n < 2:
        return False
    for i in range(n - 1):
        q1 = (ring[i][0], ring[i][1])
        q2 = (ring[i + 1][0], ring[i + 1][1])
        if _segments_intersect(p1, p2, q1, q2):
            return True
    return False


def line_intersects_polygon_feature(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
    feature: GeoFeature,
) -> bool:
    """Check if a route line segment between two coordinates intersects a polygon feature."""
    geom = feature.geometry
    if not geom:
        return False

    p1 = (start_lon, start_lat)
    p2 = (end_lon, end_lat)

    # 1. If start or end point is inside the polygon -> intersects
    if point_in_feature_geometry(start_lon, start_lat, feature) or point_in_feature_geometry(
        end_lon, end_lat, feature
    ):
        return True

    # 2. Check if the line segment crosses any boundary rings
    if geom.type == GeometryType.POLYGON:
        for ring in geom.coordinates:
            if line_intersects_ring(p1, p2, ring):
                return True

    elif geom.type == GeometryType.MULTIPOLYGON:
        for poly_rings in geom.coordinates:
            for ring in poly_rings:
                if line_intersects_ring(p1, p2, ring):
                    return True

    return False


class MarineConstraintService:
    """Service for querying marine constraints, bathymetry, and navigational restrictions."""

    def __init__(self, repository: Optional[GeographyRepository] = None) -> None:
        """Initialize MarineConstraintService with repository dependency.

        Args:
            repository: Geography repository instance. Defaults to shared SQLite repository.
        """
        self._repository = repository or get_default_geography_repository()

    def check_coordinate_restrictions(
        self, latitude: float, longitude: float
    ) -> CoordinateRestrictionCheckResult:
        """Check if a specific GPS coordinate lies within any restricted or no-go marine area.

        Args:
            latitude: Latitude in decimal degrees (-90 to 90).
            longitude: Longitude in decimal degrees (-180 to 180).

        Returns:
            CoordinateRestrictionCheckResult with matched restrictions and status.
        """
        if not (-90.0 <= latitude <= 90.0):
            raise ValueError(f"Latitude {latitude} out of valid range [-90.0, 90.0].")
        if not (-180.0 <= longitude <= 180.0):
            raise ValueError(f"Longitude {longitude} out of valid range [-180.0, 180.0].")

        # Query all restricted areas from geography store
        restricted_features, _ = self._repository.list_features(
            feature_type=GeoFeatureType.RESTRICTED_AREA, limit=5000, offset=0
        )

        matching: List[GeoFeature] = []
        for feat in restricted_features:
            if point_in_feature_geometry(longitude, latitude, feat):
                matching.append(feat)

        if matching:
            types = [f.restriction_type or "restricted" for f in matching]
            highest = types[0]
            names = [f.name for f in matching if f.name]
            name_str = f" ({', '.join(names)})" if names else ""
            return CoordinateRestrictionCheckResult(
                latitude=latitude,
                longitude=longitude,
                is_restricted=True,
                matching_restrictions=matching,
                highest_restriction_type=highest,
                message=f"Coordinate lies within {len(matching)} restricted marine zone(s){name_str}: {', '.join(types)}.",
            )

        return CoordinateRestrictionCheckResult(
            latitude=latitude,
            longitude=longitude,
            is_restricted=False,
            matching_restrictions=[],
            highest_restriction_type=None,
            message="Clear: No restricted or no-go marine zones intersect this coordinate.",
        )

    def check_route_segment_restrictions(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
    ) -> List[GeoFeature]:
        """Check if a line segment between two GPS coordinates intersects any restricted area.

        Args:
            start_lat: Segment start latitude.
            start_lon: Segment start longitude.
            end_lat: Segment end latitude.
            end_lon: Segment end longitude.

        Returns:
            List of intersecting restricted GeoFeature entities.
        """
        restricted_features, _ = self._repository.list_features(
            feature_type=GeoFeatureType.RESTRICTED_AREA, limit=5000, offset=0
        )

        intersecting: List[GeoFeature] = []
        for feat in restricted_features:
            if line_intersects_polygon_feature(
                start_lon, start_lat, end_lon, end_lat, feat
            ):
                intersecting.append(feat)

        return intersecting

    def check_route_restrictions(
        self,
        waypoints: List[Coordinate],
        vessel_draft_meters: Optional[float] = None,
        buffer_distance_km: float = 0.0,
    ) -> RouteRestrictionCheckResult:
        """Check an entire planned route (sequence of coordinates) against restricted areas.

        Args:
            waypoints: List of Coordinate objects forming the planned route.
            vessel_draft_meters: Optional vessel draft in meters.
            buffer_distance_km: Optional safety buffer distance in kilometers.

        Returns:
            RouteRestrictionCheckResult detailing any intersected restricted zones.
        """
        if len(waypoints) < 2:
            return RouteRestrictionCheckResult(
                has_restrictions=False,
                restricted_segments_count=0,
                intersecting_restrictions=[],
                warnings=[],
            )

        intersecting_map: dict[str, GeoFeature] = {}
        restricted_segments_count = 0
        warnings: List[str] = []

        # Check each segment
        for i in range(len(waypoints) - 1):
            p1 = waypoints[i]
            p2 = waypoints[i + 1]
            seg_hits = self.check_route_segment_restrictions(
                p1.latitude, p1.longitude, p2.latitude, p2.longitude
            )
            if seg_hits:
                restricted_segments_count += 1
                for hit in seg_hits:
                    intersecting_map[hit.feature_id] = hit
                names = [h.name or h.feature_id for h in seg_hits]
                warnings.append(
                    f"Segment {i + 1} ({p1.latitude:.4f},{p1.longitude:.4f} -> {p2.latitude:.4f},{p2.longitude:.4f}) crosses restricted area: {', '.join(names)}"
                )

        intersecting_list = list(intersecting_map.values())
        return RouteRestrictionCheckResult(
            has_restrictions=len(intersecting_list) > 0,
            restricted_segments_count=restricted_segments_count,
            intersecting_restrictions=intersecting_list,
            warnings=warnings,
        )

    def get_depth_at_coordinate(
        self,
        latitude: float,
        longitude: float,
        search_radius_km: float = 25.0,
    ) -> DepthQueryResult:
        """Query bathymetric sea depth at or near a GPS coordinate.

        Algorithm:
        1. Checks if coordinate falls within any polygon-based bathymetry depth zones.
        2. If not found, searches for nearest point soundings within search_radius_km.
        3. If no bathymetry features are available, returns confidence="none".

        Args:
            latitude: Latitude in decimal degrees (-90 to 90).
            longitude: Longitude in decimal degrees (-180 to 180).
            search_radius_km: Maximum radius in km to search for soundings.

        Returns:
            DepthQueryResult domain model.
        """
        if not (-90.0 <= latitude <= 90.0):
            raise ValueError(f"Latitude {latitude} out of valid range [-90.0, 90.0].")
        if not (-180.0 <= longitude <= 180.0):
            raise ValueError(f"Longitude {longitude} out of valid range [-180.0, 180.0].")

        # 1. Check Polygon/MultiPolygon depth zone features
        bathymetry_features, _ = self._repository.list_features(
            feature_type=GeoFeatureType.BATHYMETRY, limit=5000, offset=0
        )

        for feat in bathymetry_features:
            if feat.geometry and feat.geometry.type in (
                GeometryType.POLYGON,
                GeometryType.MULTIPOLYGON,
            ):
                if point_in_feature_geometry(longitude, latitude, feat):
                    depth = feat.depth_meters
                    return DepthQueryResult(
                        latitude=latitude,
                        longitude=longitude,
                        depth_meters=depth,
                        depth_source_feature=feat,
                        distance_to_sounding_km=0.0,
                        confidence="polygon_zone" if depth is not None else "polygon_unspecified",
                    )

        # 2. Check Point soundings within radius
        origin = Coordinate(latitude=latitude, longitude=longitude)
        point_soundings: List[Tuple[GeoFeature, float]] = []

        for feat in bathymetry_features:
            lat = feat.latitude
            lon = feat.longitude
            if lat is not None and lon is not None:
                pt_coord = Coordinate(latitude=lat, longitude=lon)
                dist_km = GeoService.haversine_distance_km(origin, pt_coord)
                if dist_km <= search_radius_km:
                    point_soundings.append((feat, dist_km))

        if point_soundings:
            # Sort by distance ascending
            point_soundings.sort(key=lambda item: item[1])
            nearest_feat, nearest_dist = point_soundings[0]
            return DepthQueryResult(
                latitude=latitude,
                longitude=longitude,
                depth_meters=nearest_feat.depth_meters,
                depth_source_feature=nearest_feat,
                distance_to_sounding_km=nearest_dist,
                confidence="exact" if nearest_dist < 0.1 else "nearest_sounding",
            )

        return DepthQueryResult(
            latitude=latitude,
            longitude=longitude,
            depth_meters=None,
            depth_source_feature=None,
            distance_to_sounding_km=None,
            confidence="none",
        )

    def validate_vessel_draft(
        self,
        latitude: float,
        longitude: float,
        vessel_draft_meters: float,
        minimum_safe_depth_meters: Optional[float] = None,
        safety_margin_meters: float = 1.0,
    ) -> VesselDraftSafetyResult:
        """Validate vessel draft and calculate under-keel clearance against sea depth.

        Formula:
            under_keel_clearance = estimated_depth_meters - vessel_draft_meters
            safe when under_keel_clearance >= safety_margin_meters

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
            vessel_draft_meters: Vessel draft (submerged depth) in meters (> 0).
            minimum_safe_depth_meters: Optional explicit minimum required depth.
            safety_margin_meters: Under-keel clearance safety buffer in meters (default 1.0m).

        Returns:
            VesselDraftSafetyResult with status and safety determination.
        """
        if vessel_draft_meters <= 0:
            raise ValueError(
                f"Vessel draft must be greater than zero, got {vessel_draft_meters}."
            )

        depth_result = self.get_depth_at_coordinate(latitude, longitude)
        required_min_depth = (
            minimum_safe_depth_meters
            if minimum_safe_depth_meters is not None
            else (vessel_draft_meters + safety_margin_meters)
        )

        if depth_result.depth_meters is None:
            # When bathymetry dataset is pending, return UNKNOWN_DEPTH with is_safe=True
            # so normal navigation is not blocked while waiting for authoritative data.
            return VesselDraftSafetyResult(
                latitude=latitude,
                longitude=longitude,
                vessel_draft_meters=vessel_draft_meters,
                minimum_safe_depth_meters=required_min_depth,
                estimated_depth_meters=None,
                under_keel_clearance_meters=None,
                is_safe=True,
                status="UNKNOWN_DEPTH",
                message="No authoritative bathymetry depth soundings available at this coordinate. Proceed with local hydrographic caution.",
            )

        estimated_depth = depth_result.depth_meters
        ukc = estimated_depth - vessel_draft_meters

        if estimated_depth < vessel_draft_meters:
            return VesselDraftSafetyResult(
                latitude=latitude,
                longitude=longitude,
                vessel_draft_meters=vessel_draft_meters,
                minimum_safe_depth_meters=required_min_depth,
                estimated_depth_meters=estimated_depth,
                under_keel_clearance_meters=ukc,
                is_safe=False,
                status="CRITICAL_DEPTH",
                message=f"CRITICAL: Vessel draft ({vessel_draft_meters:.1f}m) exceeds available water depth ({estimated_depth:.1f}m). Grounding hazard!",
            )

        if estimated_depth < required_min_depth:
            return VesselDraftSafetyResult(
                latitude=latitude,
                longitude=longitude,
                vessel_draft_meters=vessel_draft_meters,
                minimum_safe_depth_meters=required_min_depth,
                estimated_depth_meters=estimated_depth,
                under_keel_clearance_meters=ukc,
                is_safe=False,
                status="WARNING",
                message=f"WARNING: Under-keel clearance ({ukc:.1f}m) is below safety requirement ({safety_margin_meters:.1f}m). Depth: {estimated_depth:.1f}m.",
            )

        return VesselDraftSafetyResult(
            latitude=latitude,
            longitude=longitude,
            vessel_draft_meters=vessel_draft_meters,
            minimum_safe_depth_meters=required_min_depth,
            estimated_depth_meters=estimated_depth,
            under_keel_clearance_meters=ukc,
            is_safe=True,
            status="SAFE",
            message=f"Depth safe: {estimated_depth:.1f}m depth provides {ukc:.1f}m under-keel clearance for {vessel_draft_meters:.1f}m draft.",
        )

    def get_nearby_restricted_areas(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 50.0,
        limit: int = 50,
    ) -> List[GeoNearbyFeature]:
        """Find restricted marine areas near a coordinate."""
        from app.services.geography_service import GeographyService

        geo_service = GeographyService(repository=self._repository)
        return geo_service.find_nearby_features(
            latitude=latitude,
            longitude=longitude,
            feature_type=GeoFeatureType.RESTRICTED_AREA,
            radius_km=radius_km,
            limit=limit,
        )

    def get_nearby_bathymetry(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 50.0,
        limit: int = 50,
    ) -> List[GeoNearbyFeature]:
        """Find bathymetric soundings / depth points near a coordinate."""
        from app.services.geography_service import GeographyService

        geo_service = GeographyService(repository=self._repository)
        return geo_service.find_nearby_features(
            latitude=latitude,
            longitude=longitude,
            feature_type=GeoFeatureType.BATHYMETRY,
            radius_km=radius_km,
            limit=limit,
        )


def get_marine_constraint_service() -> MarineConstraintService:
    """FastAPI dependency provider for MarineConstraintService."""
    return MarineConstraintService(repository=get_default_geography_repository())
