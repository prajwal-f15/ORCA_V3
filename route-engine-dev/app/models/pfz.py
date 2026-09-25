"""Potential Fishing Zone (PFZ) domain models and schemas for ORCA Route Engine."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field, model_validator
from app.models.geography import GeoGeometry, GeometryType
from app.models.request import Coordinate, Vessel


class PFZDatasetStatus(str, Enum):
    """Lifecycle and availability status of the PFZ data feed."""

    AVAILABLE = "available"
    PENDING = "pending"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class PFZFreshness(str, Enum):
    """Freshness status of the latest PFZ advisory."""

    FRESH = "fresh"
    STALE = "stale"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class PFZZone(BaseModel):
    """Potential Fishing Zone entity representing an authoritative advisory area or sounding."""

    pfz_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the PFZ zone",
        examples=["in_pfz_guj_001"],
    )
    dataset_id: Optional[str] = Field(
        default="india_pfz",
        description="Dataset identifier to which this zone belongs",
    )
    name: Optional[str] = Field(
        default=None,
        description="Human-readable sector name or advisory title",
        examples=["Veraval Offshore PFZ Sector A"],
    )
    geometry_type: str = Field(
        default="",
        description="Geometry type (Point, Polygon, MultiPolygon)",
    )
    geometry: GeoGeometry = Field(
        ...,
        description="GeoJSON-compatible geometry definition",
    )
    centroid: Optional[Coordinate] = Field(
        default=None,
        description="Computed or authoritative center coordinate of the zone",
    )
    source: str = Field(
        default="INCOIS",
        description="Authoritative source or advisory provider",
        examples=["INCOIS"],
    )
    source_url: Optional[str] = Field(
        default="https://incois.gov.in/geoportal/MFASPFZ/index.html",
        description="Source geoportal or API URL",
    )
    source_updated_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when source advisory was generated",
    )
    valid_from: Optional[datetime] = Field(
        default=None,
        description="Start time of advisory validity window",
    )
    valid_until: Optional[datetime] = Field(
        default=None,
        description="Expiry time of advisory validity window",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Statistical or model confidence level (0.0 to 1.0)",
        examples=[0.85],
    )
    suitability_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Authoritative fish potential / suitability score (0 to 100)",
        examples=[82.0],
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Original metadata properties from source advisory",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls, data: Any) -> Any:
        """Allow initializing with either 'id' or 'pfz_id'."""
        if isinstance(data, dict):
            if "pfz_id" not in data and "id" in data:
                data["pfz_id"] = data["id"]
        return data

    @model_validator(mode="after")
    def synchronize_geometry_and_centroid(self) -> "PFZZone":
        """Synchronize geometry_type and compute fallback centroid if missing."""
        if self.geometry:
            if not self.geometry_type:
                self.geometry_type = self.geometry.type.value

            if self.centroid is None:
                coords = self.geometry.coordinates
                if self.geometry.type == GeometryType.POINT:
                    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                        self.centroid = Coordinate(
                            longitude=float(coords[0]), latitude=float(coords[1])
                        )
                elif self.geometry.type in (GeometryType.POLYGON, GeometryType.MULTIPOLYGON):
                    # Compute simple bounding centroid from coordinates
                    flat_pts = self._extract_flat_coords(self.geometry.type, coords)
                    if flat_pts:
                        avg_lon = sum(p[0] for p in flat_pts) / len(flat_pts)
                        avg_lat = sum(p[1] for p in flat_pts) / len(flat_pts)
                        self.centroid = Coordinate(
                            longitude=round(avg_lon, 6), latitude=round(avg_lat, 6)
                        )
        return self

    @staticmethod
    def _extract_flat_coords(g_type: GeometryType, coords: Any) -> List[List[float]]:
        flat: List[List[float]] = []
        if g_type == GeometryType.POLYGON:
            for ring in coords:
                if isinstance(ring, (list, tuple)):
                    for pt in ring:
                        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                            flat.append([float(pt[0]), float(pt[1])])
        elif g_type == GeometryType.MULTIPOLYGON:
            for poly in coords:
                if isinstance(poly, (list, tuple)):
                    for ring in poly:
                        if isinstance(ring, (list, tuple)):
                            for pt in ring:
                                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                                    flat.append([float(pt[0]), float(pt[1])])
        return flat

    @property
    def id(self) -> str:
        """Compatibility alias for pfz_id."""
        return self.pfz_id

    @property
    def latitude(self) -> Optional[float]:
        """Latitude of centroid or coordinate."""
        if self.centroid:
            return self.centroid.latitude
        return None

    @property
    def longitude(self) -> Optional[float]:
        """Longitude of centroid or coordinate."""
        if self.centroid:
            return self.centroid.longitude
        return None

    @property
    def species(self) -> Optional[str]:
        """Target pelagic species mentioned in advisory."""
        for key in ("species", "target_species", "SPECIES", "fish_species", "fish_type"):
            if key in self.properties and self.properties[key] is not None:
                return str(self.properties[key])
        return None

    @property
    def sst_celsius(self) -> Optional[float]:
        """Sea Surface Temperature in Celsius if present."""
        for key in ("sst", "SST", "sst_celsius", "sea_surface_temp", "temperature"):
            if key in self.properties and self.properties[key] is not None:
                try:
                    return float(self.properties[key])
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def chlorophyll_mg_m3(self) -> Optional[float]:
        """Chlorophyll-a concentration in mg/m^3 if present."""
        for key in ("chlorophyll", "chl_a", "CHLA", "chlorophyll_a", "chl"):
            if key in self.properties and self.properties[key] is not None:
                try:
                    return float(self.properties[key])
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def depth_range(self) -> Optional[str]:
        """Water depth range information."""
        for key in ("depth_range", "depth", "water_depth", "sounding_range"):
            if key in self.properties and self.properties[key] is not None:
                return str(self.properties[key])
        return None


class PFZObservation(BaseModel):
    """Point or grid cell prediction observation from oceanographic models."""

    observation_id: str = Field(..., min_length=1)
    timestamp: datetime = Field(...)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    fish_potential_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    species: Optional[str] = None
    sst_celsius: Optional[float] = None
    chlorophyll_mg_m3: Optional[float] = None
    source: str = "INCOIS"
    model_version: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class PFZNearbyZone(BaseModel):
    """PFZ zone with relative distance, bearing, and target navigation point."""

    zone: PFZZone
    distance_km: float = Field(..., ge=0.0, description="Great-circle distance in kilometers")
    distance_nm: float = Field(..., ge=0.0, description="Great-circle distance in nautical miles")
    bearing_degrees: float = Field(
        ..., ge=0.0, lt=360.0, description="Initial bearing in degrees from vessel"
    )
    destination: Coordinate = Field(..., description="Navigation target coordinate for this zone")


class PFZRouteTargetRequest(BaseModel):
    """Input payload to request ranked PFZ candidate destinations from a vessel position."""

    current_position: Coordinate = Field(
        ..., description="Current live GPS position of the vessel"
    )
    radius_km: float = Field(
        default=100.0,
        gt=0.0,
        le=2000.0,
        description="Search radius around vessel position in kilometers",
        examples=[100.0],
    )
    vessel: Optional[Vessel] = Field(
        default=None, description="Optional vessel configuration and speed"
    )
    objective: str = Field(
        default="balanced",
        description="Optimization preference: 'balanced', 'highest_potential', 'nearest_distance', or 'high_confidence'",
        examples=["balanced"],
    )
    minimum_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional minimum required confidence filter (0.0 - 1.0)",
    )
    limit: int = Field(
        default=5, ge=1, le=50, description="Maximum number of candidate destinations to return"
    )


class PFZRouteTarget(BaseModel):
    """Ranked PFZ candidate destination formatted for Route Engine path planning."""

    pfz_id: str
    name: Optional[str] = None
    destination: Coordinate
    distance_km: float
    distance_nm: float
    bearing_degrees: float
    suitability_score: Optional[float] = None
    confidence: Optional[float] = None
    ranking_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Composite deterministic ranking score (0 to 100) based on suitability, confidence, and distance",
    )
    estimated_travel_time_minutes: Optional[float] = None
    source: str = "INCOIS"
    valid_until: Optional[datetime] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class PFZRouteTargetResponse(BaseModel):
    """Response containing ranked PFZ destination targets for the Route Engine."""

    origin: Coordinate
    total_candidates: int
    targets: List[PFZRouteTarget]
    dataset_status: PFZDatasetStatus = PFZDatasetStatus.PENDING
    scoring_formula: str = (
        "ranking_score = (w_suitability * suitability) + (w_confidence * confidence) + (w_distance * distance_factor)"
    )


class PFZStatus(BaseModel):
    """Operational status and data freshness report of the PFZ advisory feed."""

    source: str = "INCOIS"
    source_url: Optional[str] = "https://incois.gov.in/geoportal/MFASPFZ/index.html"
    last_updated: Optional[datetime] = None
    freshness: PFZFreshness = PFZFreshness.PENDING
    dataset_status: PFZDatasetStatus = PFZDatasetStatus.PENDING
    feature_count: int = 0
    model_version: Optional[str] = None
    message: str = "PFZ advisory data: Pending official dataset ingestion"


class PFZZoneListResponse(BaseModel):
    """Paginated list response for registered PFZ zones."""

    zones: List[PFZZone]
    total: int
    limit: int
    offset: int


class PFZNearbyResponse(BaseModel):
    """Response containing nearby PFZ zones within a search radius."""

    origin_latitude: float
    origin_longitude: float
    radius_km: float
    total: int
    zones: List[PFZNearbyZone]
