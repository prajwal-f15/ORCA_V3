"""Abstract base adapter interface for weather/meteorological data feeds."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.models.marine_conditions import WeatherConditions
from app.models.provider import ProviderStatus


class WeatherAdapter(ABC):
    """Abstract interface for external/internal meteorological condition data providers."""

    @property
    def provider_name(self) -> str:
        """Name of the meteorological data provider."""
        return "weather_adapter"

    def get_provider_status(self) -> ProviderStatus:
        """Query operational availability status of the weather provider."""
        return ProviderStatus.AVAILABLE

    @abstractmethod
    def get_conditions(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[WeatherConditions]:
        """Fetch normalized meteorological conditions for a specific coordinate and time.

        Args:
            latitude: Target latitude in decimal degrees.
            longitude: Target longitude in decimal degrees.
            timestamp: Optional target timestamp in UTC.

        Returns:
            Normalized WeatherConditions model or None if data is unavailable.
        """
        pass
