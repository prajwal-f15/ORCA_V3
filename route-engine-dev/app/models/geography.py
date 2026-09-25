"""Geographic domain models and schemas for ORCA Route Engine."""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field, model_validator
from app.models.request import Coordinate


class GeoFeatureType(str, Enum):
    """Supported geographic data domain categories for Indian marine environment."""

    COASTLINE = "coastline"
    MARINE_AREA = "marine_area"
    EEZ = "eez"
    PORT = "port"
    HARBOUR = "harbour"
    LANDING_CENTRE = "landing_centre"
    LIGHTHOUSE = "lighthouse"
    BATHYMETRY = "bathymetry"
    RESTRICTED_AREA = "restricted_area"
    PFZ = "pfz"


class GeometryType(str, Enum):
    """GeoJSON-compatible geometry types."""

    POINT = "Point"
    LINESTRING = "LineString"
    POLYGON = "Polygon"
    MULTIPOINT = "MultiPoint"
    MULTILINESTRING = "MultiLineString"
    MULTIPOLYGON = "MultiPolygon"


class GeoPoint(BaseModel):
    """Geographic point model with strict boundary validation."""

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

    def to_geojson(self) -> List[float]:
        """Return GeoJSON coordinate pair [longitude, latitude].

        NOTE: GeoJSON standard specifies [longitude, latitude] ordering.
        """
        return [self.longitude, self.latitude]

    @classmethod
    def from_geojson(cls, coords: List[float]) -> "GeoPoint":
        """Create GeoPoint from GeoJSON coordinate pair [longitude, latitude]."""
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            raise ValueError("GeoJSON coordinate must be a list of [longitude, latitude].")
        return cls(longitude=coords[0], latitude=coords[1])


class GeoBoundingBox(BaseModel):
    """Axis-aligned geographic bounding box."""

    min_latitude: float = Field(
        ..., ge=-90.0, le=90.0, description="Minimum latitude (-90 to 90)"
    )
    min_longitude: float = Field(
        ..., ge=-180.0, le=180.0, description="Minimum longitude (-180 to 180)"
    )
    max_latitude: float = Field(
        ..., ge=-90.0, le=90.0, description="Maximum latitude (-90 to 90)"
    )
    max_longitude: float = Field(
        ..., ge=-180.0, le=180.0, description="Maximum longitude (-180 to 180)"
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_box_keys(cls, data: Any) -> Any:
        """Allow initializing with min_lat/max_lat/min_lon/max_lon aliases."""
        if isinstance(data, dict):
            if "min_lat" in data and "min_latitude" not in data:
                data["min_latitude"] = data["min_lat"]
            if "max_lat" in data and "max_latitude" not in data:
                data["max_latitude"] = data["max_lat"]
            if "min_lon" in data and "min_longitude" not in data:
                data["min_longitude"] = data["min_lon"]
            if "max_lon" in data and "max_longitude" not in data:
                data["max_longitude"] = data["max_lon"]
        return data

    @property
    def min_lat(self) -> float:
        return self.min_latitude

    @property
    def max_lat(self) -> float:
        return self.max_latitude

    @property
    def min_lon(self) -> float:
        return self.min_longitude

    @property
    def max_lon(self) -> float:
        return self.max_longitude

    @model_validator(mode="after")
    def validate_bounds(self) -> "GeoBoundingBox":
        """Ensure minimum boundaries do not exceed maximum boundaries."""
        if self.min_latitude > self.max_latitude:
            raise ValueError(
                f"min_latitude ({self.min_latitude}) cannot exceed max_latitude ({self.max_latitude})."
            )
        if self.min_longitude > self.max_longitude:
            raise ValueError(
                f"min_longitude ({self.min_longitude}) cannot exceed max_longitude ({self.max_longitude})."
            )
        return self


def _validate_coordinate_pair(pair: Any) -> None:
    """Validate a single [longitude, latitude] coordinate pair."""
    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
        raise ValueError(
            f"Coordinate pair must be a 2-element sequence [longitude, latitude], got {pair}."
        )
    lon, lat = pair[0], pair[1]
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        raise ValueError(f"Coordinates must be numeric, got [{lon}, {lat}].")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"Longitude {lon} out of valid range [-180, 180].")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude {lat} out of valid range [-90, 90].")


class GeoGeometry(BaseModel):
    """GeoJSON-compatible geometry representation.

    IMPORTANT: GeoJSON coordinates follow the [longitude, latitude] convention,
    NOT [latitude, longitude].
    """

    type: GeometryType = Field(
        ...,
        description="GeoJSON geometry type (Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon)",
        examples=["Point"],
    )
    coordinates: Any = Field(
        ...,
        description="GeoJSON coordinate array following [longitude, latitude] standard",
    )

    @model_validator(mode="after")
    def validate_geometry(self) -> "GeoGeometry":
        """Validate structure and coordinate bounds according to GeoJSON geometry type."""
        geom_type = self.type
        coords = self.coordinates

        if geom_type == GeometryType.POINT:
            _validate_coordinate_pair(coords)

        elif geom_type == GeometryType.LINESTRING:
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                raise ValueError("LineString must contain at least two coordinate pairs.")
            for pt in coords:
                _validate_coordinate_pair(pt)

        elif geom_type == GeometryType.MULTIPOINT:
            if not isinstance(coords, (list, tuple)) or len(coords) < 1:
                raise ValueError("MultiPoint must contain at least one coordinate pair.")
            for pt in coords:
                _validate_coordinate_pair(pt)

        elif geom_type == GeometryType.POLYGON:
            if not isinstance(coords, (list, tuple)) or len(coords) < 1:
                raise ValueError("Polygon must contain at least one linear ring.")
            for ring in coords:
                if not isinstance(ring, (list, tuple)) or len(ring) < 3:
                    raise ValueError(
                        "Polygon linear ring must contain at least 3 coordinate pairs."
                    )
                for pt in ring:
                    _validate_coordinate_pair(pt)

        elif geom_type == GeometryType.MULTILINESTRING:
            if not isinstance(coords, (list, tuple)) or len(coords) < 1:
                raise ValueError("MultiLineString must contain at least one line sequence.")
            for line in coords:
                if not isinstance(line, (list, tuple)) or len(line) < 2:
                    raise ValueError("MultiLineString lines must contain at least two coordinates.")
                for pt in line:
                    _validate_coordinate_pair(pt)

        elif geom_type == GeometryType.MULTIPOLYGON:
            if not isinstance(coords, (list, tuple)) or len(coords) < 1:
                raise ValueError("MultiPolygon must contain at least one polygon.")
            for poly in coords:
                if not isinstance(poly, (list, tuple)) or len(poly) < 1:
                    raise ValueError("MultiPolygon components must contain at least one ring.")
                for ring in poly:
                    if not isinstance(ring, (list, tuple)) or len(ring) < 3:
                        raise ValueError(
                            "MultiPolygon ring must contain at least 3 coordinate pairs."
                        )
                    for pt in ring:
                        _validate_coordinate_pair(pt)

        return self


class GeoFeature(BaseModel):
    """Geographic feature representation representing coastal, maritime, or boundary assets."""

    feature_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the geographic feature",
        examples=["in_mum_001"],
    )
    dataset_id: Optional[str] = Field(
        default=None,
        description="Dataset identifier to which this feature belongs",
        examples=["india_ports"],
    )
    feature_type: GeoFeatureType = Field(
        ...,
        description="Classification category of the geographic feature",
        examples=["port"],
    )
    name: Optional[str] = Field(
        default=None,
        description="Human-readable name or designation",
        examples=["Mumbai Port"],
    )
    geometry_type: str = Field(
        default="",
        description="Geometry type matching GeoJSON standards (Point, Polygon, etc.)",
    )
    geometry: GeoGeometry = Field(
        ...,
        description="GeoJSON-compatible geometry definition",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata and domain properties for the feature",
    )
    source: str = Field(
        default="authoritative",
        description="Authoritative source or dataset origin",
        examples=["INCOIS"],
    )
    source_updated_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the source data was last updated",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_feature_inputs(cls, data: Any) -> Any:
        """Allow initializing with either 'id' or 'feature_id', and default source if omitted."""
        if isinstance(data, dict):
            if "feature_id" not in data and "id" in data:
                data["feature_id"] = data["id"]
            if "source" not in data:
                data["source"] = "authoritative"
        return data

    @property
    def id(self) -> str:
        """Alias for feature_id for compatibility."""
        return self.feature_id

    @property
    def latitude(self) -> Optional[float]:
        """Extract latitude in decimal degrees if geometry is a Point or from properties."""
        if self.geometry and self.geometry.type == GeometryType.POINT:
            coords = self.geometry.coordinates
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                return float(coords[1])
        for key in ("latitude", "lat", "LATITUDE", "Lat"):
            if key in self.properties and self.properties[key] is not None:
                try:
                    return float(self.properties[key])
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def longitude(self) -> Optional[float]:
        """Extract longitude in decimal degrees if geometry is a Point or from properties."""
        if self.geometry and self.geometry.type == GeometryType.POINT:
            coords = self.geometry.coordinates
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                return float(coords[0])
        for key in ("longitude", "lon", "LONGITUDE", "Lon", "lng", "Lng"):
            if key in self.properties and self.properties[key] is not None:
                try:
                    return float(self.properties[key])
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def state(self) -> Optional[str]:
        """Extract state name from properties if available."""
        for key in ("state", "State", "STATE", "state_name", "State_Name", "STATE_NAME"):
            if key in self.properties and self.properties[key] is not None:
                return str(self.properties[key])
        return None

    @property
    def district(self) -> Optional[str]:
        """Extract district name from properties if available."""
        for key in ("district", "District", "DISTRICT", "district_name", "District_Name"):
            if key in self.properties and self.properties[key] is not None:
                return str(self.properties[key])
        return None

    @property
    def code(self) -> Optional[str]:
        """Extract official port / lighthouse / identifier code if available."""
        for key in (
            "code",
            "CODE",
            "port_code",
            "Port_Code",
            "un_locode",
            "UN_LOCODE",
            "locode",
            "light_number",
            "identifier",
        ):
            if key in self.properties and self.properties[key] is not None:
                return str(self.properties[key])
        return None

    @property
    def depth_meters(self) -> Optional[float]:
        """Extract bathymetric depth / sounding in meters from properties if available."""
        for key in (
            "depth_meters",
            "depth_m",
            "depth",
            "DEPTH",
            "Depth",
            "sounding",
            "SOUNDING",
            "elevation",
            "ELEVATION",
            "contour",
            "CONTOUR",
            "val",
            "VAL",
            "z",
            "Z",
        ):
            if key in self.properties and self.properties[key] is not None:
                try:
                    val = float(self.properties[key])
                    # Bathymetry elevation is sometimes negative in DEMs (-50m), return positive depth
                    return abs(val) if val < 0 else val
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def minimum_depth_meters(self) -> Optional[float]:
        """Extract minimum depth boundary in meters if available."""
        for key in (
            "minimum_depth_meters",
            "min_depth_meters",
            "min_depth_m",
            "minimum_depth",
            "min_depth",
            "MIN_DEPTH",
            "MIN_DEPTH_M",
            "depth_min",
        ):
            if key in self.properties and self.properties[key] is not None:
                try:
                    val = float(self.properties[key])
                    return abs(val) if val < 0 else val
                except (ValueError, TypeError):
                    pass
        return self.depth_meters

    @property
    def maximum_depth_meters(self) -> Optional[float]:
        """Extract maximum depth boundary in meters if available."""
        for key in (
            "maximum_depth_meters",
            "max_depth_meters",
            "max_depth_m",
            "maximum_depth",
            "max_depth",
            "MAX_DEPTH",
            "MAX_DEPTH_M",
            "depth_max",
        ):
            if key in self.properties and self.properties[key] is not None:
                try:
                    val = float(self.properties[key])
                    return abs(val) if val < 0 else val
                except (ValueError, TypeError):
                    pass
        return self.depth_meters

    @property
    def restriction_type(self) -> Optional[str]:
        """Extract official restriction / protection classification from properties if available."""
        for key in (
            "restriction_type",
            "RESTRICTION_TYPE",
            "restriction",
            "RESTRICTION",
            "type",
            "TYPE",
            "zone_type",
            "ZONE_TYPE",
            "category",
            "CATEGORY",
            "status",
            "STATUS",
            "legal_status",
            "protection_level",
            "designation",
        ):
            if key in self.properties and self.properties[key] is not None:
                return str(self.properties[key])
        return None

    @model_validator(mode="after")
    def synchronize_geometry_type(self) -> "GeoFeature":
        """Ensure geometry_type is populated from geometry.type."""
        if not self.geometry_type and self.geometry:
            self.geometry_type = self.geometry.type.value
        return self


class GeoDataset(BaseModel):
    """Geographic dataset registration and tracking model."""

    dataset_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the dataset",
        examples=["india_coastline"],
    )
    name: str = Field(
        ...,
        description="Descriptive name of the dataset",
        examples=["India Official Coastline Boundary"],
    )
    feature_type: GeoFeatureType = Field(
        ...,
        description="Feature category contained in this dataset",
        examples=["coastline"],
    )
    source: str = Field(
        ...,
        description="Authoritative data provider or organization",
        examples=["pending"],
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Authoritative source URL (e.g. INCOIS geoportal URL)",
        examples=["https://incois.gov.in/geoportal/MFASPFZ/index.html"],
    )
    version: str = Field(
        ...,
        description="Dataset version or release identifier",
        examples=["pending"],
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of last dataset update",
    )
    feature_count: int = Field(
        default=0,
        ge=0,
        description="Number of geographic features registered under this dataset",
    )
    bounding_box: Optional[GeoBoundingBox] = Field(
        default=None,
        description="Spatial bounding box covering the dataset features",
    )

    def to_metadata(self) -> "GeoDatasetMetadata":
        """Convert full dataset model to public lightweight metadata descriptor."""
        return GeoDatasetMetadata(
            dataset_id=self.dataset_id,
            name=self.name,
            feature_type=self.feature_type.value
            if hasattr(self.feature_type, "value")
            else str(self.feature_type),
            source=self.source,
            source_url=self.source_url,
            version=self.version,
            updated_at=self.updated_at,
            feature_count=self.feature_count,
            bounding_box=self.bounding_box,
        )


class GeoDatasetMetadata(BaseModel):
    """Lightweight metadata descriptor for public dataset queries."""

    dataset_id: str
    name: str
    feature_type: str
    source: str
    source_url: Optional[str] = None
    version: str
    updated_at: Optional[datetime] = None
    feature_count: int = 0
    bounding_box: Optional[GeoBoundingBox] = None


class GeoFeatureListResponse(BaseModel):
    """Paginated list response for geographic features."""

    features: List[GeoFeature]
    total: int
    limit: int
    offset: int


class GeoDatasetListResponse(BaseModel):
    """Response containing registered geographic dataset descriptors."""

    datasets: List[GeoDatasetMetadata]
    total: int


class GeoNearbyFeature(BaseModel):
    """Geographic feature enriched with relative distance and bearing from search origin."""

    feature: GeoFeature
    distance_km: float = Field(..., ge=0.0, description="Great-circle distance in kilometers")
    distance_nm: float = Field(..., ge=0.0, description="Great-circle distance in nautical miles")
    bearing_degrees: float = Field(
        ..., ge=0.0, lt=360.0, description="Initial bearing in degrees from origin"
    )


class GeoNearbyResponse(BaseModel):
    """Response containing nearby geographic features within a given search radius."""

    origin_latitude: float
    origin_longitude: float
    radius_km: float
    total: int
    features: List[GeoNearbyFeature]


class CoordinateRestrictionCheckResult(BaseModel):
    """Safety check result for whether a specific GPS coordinate lies inside restricted/no-go zones."""

    latitude: float
    longitude: float
    is_restricted: bool
    matching_restrictions: List[GeoFeature] = Field(default_factory=list)
    highest_restriction_type: Optional[str] = None
    message: str = "Clear"


class RouteRestrictionCheckRequest(BaseModel):
    """Request payload to check a sequence of coordinates/waypoints against marine restrictions."""

    coordinates: List[Coordinate] = Field(..., min_length=2, description="Sequence of route coordinates")
    vessel_draft_meters: Optional[float] = Field(
        default=None, ge=0.0, description="Optional vessel draft for shallow water safety checks"
    )
    buffer_distance_km: float = Field(
        default=0.0, ge=0.0, description="Optional safety buffer zone around route in km"
    )


class RouteRestrictionCheckResult(BaseModel):
    """Safety check result verifying an entire planned route against restricted marine zones."""

    has_restrictions: bool
    restricted_segments_count: int = 0
    intersecting_restrictions: List[GeoFeature] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class DepthQueryResult(BaseModel):
    """Result of querying sea depth/bathymetry at or near a coordinate."""

    latitude: float
    longitude: float
    depth_meters: Optional[float] = None
    depth_source_feature: Optional[GeoFeature] = None
    distance_to_sounding_km: Optional[float] = None
    confidence: str = Field(
        default="none",
        description="Depth confidence level: exact, polygon_zone, nearest_sounding, or none",
    )


class VesselDraftSafetyResult(BaseModel):
    """Vessel draft and under-keel clearance safety validation result."""

    latitude: float
    longitude: float
    vessel_draft_meters: float
    minimum_safe_depth_meters: float
    estimated_depth_meters: Optional[float] = None
    under_keel_clearance_meters: Optional[float] = None
    is_safe: bool
    status: str = Field(
        default="UNKNOWN_DEPTH",
        description="Safety status: SAFE, CRITICAL_DEPTH, WARNING, or UNKNOWN_DEPTH",
    )
    message: str

