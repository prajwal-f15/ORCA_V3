"""Mock oceanographic adapter for development and testing."""

from datetime import datetime, timezone
from typing import Optional

from app.adapters.ocean.base import OceanAdapter
from app.models.marine_conditions import OceanConditions
from app.models.provider import ProviderStatus


class MockOceanAdapter(OceanAdapter):
    """Deterministic mock adapter providing test oceanographic conditions."""

    def __init__(
        self,
        current_speed_knots: float = 1.2,
        current_direction_degrees: float = 140.0,
        significant_wave_height_m: float = 1.8,
        wave_period_seconds: float = 7.5,
        wave_direction_degrees: float = 220.0,
        sea_surface_temperature_c: float = 28.2,
        salinity_psu: float = 35.1,
        confidence: float = 0.90,
    ) -> None:
        self.current_speed_knots = current_speed_knots
        self.current_direction_degrees = current_direction_degrees
        self.significant_wave_height_m = significant_wave_height_m
        self.wave_period_seconds = wave_period_seconds
        self.wave_direction_degrees = wave_direction_degrees
        self.sea_surface_temperature_c = sea_surface_temperature_c
        self.salinity_psu = salinity_psu
        self.confidence = confidence

    @property
    def provider_name(self) -> str:
        """Name of the provider."""
        return "mock"

    def get_provider_status(self) -> ProviderStatus:
        """Mock provider is always operational in MOCK mode."""
        return ProviderStatus.MOCK

    def get_conditions(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[OceanConditions]:
        """Return deterministic mock ocean conditions."""
        ts = timestamp or datetime.now(timezone.utc)
        return OceanConditions(
            timestamp=ts,
            source="mock",
            source_version="mock-v1",
            confidence=self.confidence,
            current_speed_knots=self.current_speed_knots,
            current_direction_degrees=self.current_direction_degrees,
            significant_wave_height_m=self.significant_wave_height_m,
            wave_period_seconds=self.wave_period_seconds,
            wave_direction_degrees=self.wave_direction_degrees,
            sea_surface_temperature_c=self.sea_surface_temperature_c,
            salinity_psu=self.salinity_psu,
            metadata={
                "requested_lat": latitude,
                "requested_lon": longitude,
                "adapter": "MockOceanAdapter",
            },
        )
