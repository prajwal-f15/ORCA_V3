"""Abstract base adapter interface for oceanographic data feeds."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.models.marine_conditions import OceanConditions
from app.models.provider import ProviderStatus


class OceanAdapter(ABC):
    """Abstract interface for external/internal oceanographic condition data providers."""

    @property
    def provider_name(self) -> str:
        """Name of the oceanographic data provider."""
        return "ocean_adapter"

    def get_provider_status(self) -> ProviderStatus:
        """Query operational availability status of the ocean provider."""
        return ProviderStatus.AVAILABLE

    @abstractmethod
    def get_conditions(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[OceanConditions]:
        """Fetch normalized oceanographic conditions for a specific coordinate and time.

        Args:
            latitude: Target latitude in decimal degrees.
            longitude: Target longitude in decimal degrees.
            timestamp: Optional target timestamp in UTC.

        Returns:
            Normalized OceanConditions model or None if data is unavailable.
        """
        pass
