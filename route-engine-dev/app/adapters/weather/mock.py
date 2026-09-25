"""Mock weather adapter for development and testing."""

from datetime import datetime, timezone
from typing import Optional

from app.adapters.weather.base import WeatherAdapter
from app.models.marine_conditions import WeatherConditions
from app.models.provider import ProviderStatus


class MockWeatherAdapter(WeatherAdapter):
    """Deterministic mock adapter providing test meteorological conditions."""

    def __init__(
        self,
        wind_speed_knots: float = 14.5,
        wind_direction_degrees: float = 45.0,
        wind_gust_knots: float = 18.0,
        air_temperature_c: float = 27.5,
        visibility_km: float = 12.0,
        pressure_hpa: float = 1012.0,
        precipitation_mm_h: float = 0.0,
        cloud_cover_percent: float = 25.0,
        confidence: float = 0.92,
    ) -> None:
        self.wind_speed_knots = wind_speed_knots
        self.wind_direction_degrees = wind_direction_degrees
        self.wind_gust_knots = wind_gust_knots
        self.air_temperature_c = air_temperature_c
        self.visibility_km = visibility_km
        self.pressure_hpa = pressure_hpa
        self.precipitation_mm_h = precipitation_mm_h
        self.cloud_cover_percent = cloud_cover_percent
        self.confidence = confidence

    @property
    def provider_name(self) -> str:
        return "mock"

    def get_provider_status(self) -> ProviderStatus:
        return ProviderStatus.MOCK

    def get_conditions(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[WeatherConditions]:
        """Return deterministic mock weather conditions."""
        ts = timestamp or datetime.now(timezone.utc)
        return WeatherConditions(
            timestamp=ts,
            source="mock",
            source_version="mock-v1",
            confidence=self.confidence,
            wind_speed_knots=self.wind_speed_knots,
            wind_direction_degrees=self.wind_direction_degrees,
            wind_gust_knots=self.wind_gust_knots,
            air_temperature_c=self.air_temperature_c,
            visibility_km=self.visibility_km,
            pressure_hpa=self.pressure_hpa,
            precipitation_mm_h=self.precipitation_mm_h,
            cloud_cover_percent=self.cloud_cover_percent,
            metadata={
                "requested_lat": latitude,
                "requested_lon": longitude,
                "adapter": "MockWeatherAdapter",
            },
        )
