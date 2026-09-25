"""Normalized models for marine, oceanographic, and meteorological environmental conditions."""

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field
from app.models.request import Coordinate


class OceanConditions(BaseModel):
    """Normalized oceanographic conditions (currents, waves, sea surface temperature)."""

    timestamp: Optional[datetime] = Field(
        default=None,
        description="Observation or forecast timestamp for ocean conditions",
    )
    source: str = Field(
        default="mock",
        description="Source provider or model origin (e.g. 'mock', 'incois_hycom', 'teammate_api')",
    )
    source_version: Optional[str] = Field(
        default=None,
        description="Model or API version identifier",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model or observation confidence level (0.0 to 1.0)",
    )
    current_speed_knots: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Ocean surface current drift speed in knots",
        examples=[1.2],
    )
    current_direction_degrees: Optional[float] = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description="Direction toward which current flows in degrees (0 to 359.9)",
        examples=[140.0],
    )
    significant_wave_height_m: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Significant wave height (Hs) in meters",
        examples=[1.8],
    )
    wave_period_seconds: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Dominant wave period in seconds",
        examples=[7.5],
    )
    wave_direction_degrees: Optional[float] = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description="Direction from which waves arrive in degrees (0 to 359.9)",
        examples=[220.0],
    )
    sea_surface_temperature_c: Optional[float] = Field(
        default=None,
        description="Sea Surface Temperature (SST) in degrees Celsius",
        examples=[28.2],
    )
    salinity_psu: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Practical Salinity Units (PSU)",
        examples=[35.1],
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional source properties preserved from provider API",
    )


class WeatherConditions(BaseModel):
    """Normalized meteorological and atmospheric conditions (wind, air temperature, visibility)."""

    timestamp: Optional[datetime] = Field(
        default=None,
        description="Observation or forecast timestamp for weather conditions",
    )
    source: str = Field(
        default="mock",
        description="Source provider or model origin (e.g. 'mock', 'imd_gfs', 'teammate_api')",
    )
    source_version: Optional[str] = Field(
        default=None,
        description="Model or API version identifier",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model or observation confidence level (0.0 to 1.0)",
    )
    wind_speed_knots: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Sustained wind speed in knots at 10m elevation",
        examples=[14.5],
    )
    wind_direction_degrees: Optional[float] = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description="Direction from which wind blows in degrees (0 to 359.9)",
        examples=[270.0],
    )
    wind_gust_knots: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Peak wind gust speed in knots",
        examples=[22.0],
    )
    air_temperature_c: Optional[float] = Field(
        default=None,
        description="Surface ambient air temperature in degrees Celsius",
        examples=[29.5],
    )
    visibility_km: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Horizontal atmospheric visibility in kilometers",
        examples=[10.0],
    )
    pressure_hpa: Optional[float] = Field(
        default=None,
        ge=800.0,
        le=1100.0,
        description="Atmospheric mean sea-level pressure in hectopascals (hPa)",
        examples=[1012.0],
    )
    precipitation_mm_h: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Precipitation rate in millimeters per hour (mm/h)",
        examples=[0.0],
    )
    cloud_cover_percent: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Total cloud coverage percentage (0 to 100)",
        examples=[40.0],
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional source properties preserved from provider API",
    )


class MarineConditionsSnapshot(BaseModel):
    """Normalized environmental conditions snapshot for a geographic point or route segment."""

    position: Coordinate = Field(
        ...,
        description="Geographic coordinate of the conditions assessment",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Snapshot capture or evaluation timestamp in UTC",
    )
    ocean: Optional[OceanConditions] = Field(
        default=None,
        description="Normalized oceanographic conditions (currents, waves, SST)",
    )
    weather: Optional[WeatherConditions] = Field(
        default=None,
        description="Normalized meteorological conditions (wind, visibility, temperature)",
    )
    status: str = Field(
        default="available",
        description="Data availability status: 'available', 'partial', 'unavailable', or 'mock'",
    )
    source_summary: dict[str, str] = Field(
        default_factory=dict,
        description="Summary of data sources for ocean and weather feeds",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional environmental context or diagnostics",
    )
