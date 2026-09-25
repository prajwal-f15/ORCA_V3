"""Weather service handling meteorological conditions retrieval and normalization."""

import logging
from datetime import datetime
from typing import Optional

from app.adapters.weather.base import WeatherAdapter
from app.adapters.weather import get_weather_adapter
from app.models.marine_conditions import WeatherConditions

logger = logging.getLogger(__name__)


class WeatherService:
    """Service providing wind, atmospheric pressure, visibility, and weather data.

    NOTE: WeatherService never makes final navigational safety decisions.
    All safety constraints remain strictly with the Safety Governor.
    """

    def __init__(self, adapter: Optional[WeatherAdapter] = None) -> None:
        self.adapter = adapter or get_weather_adapter()

    def get_weather_conditions(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[WeatherConditions]:
        """Fetch and validate normalized weather conditions.

        Args:
            latitude: Target latitude in decimal degrees.
            longitude: Target longitude in decimal degrees.
            timestamp: Optional UTC timestamp for assessment.

        Returns:
            Normalized WeatherConditions instance or None if unavailable/error occurs.
        """
        try:
            conditions = self.adapter.get_conditions(
                latitude=latitude,
                longitude=longitude,
                timestamp=timestamp,
            )
            if conditions is not None and not isinstance(conditions, WeatherConditions):
                logger.warning("Adapter returned non-WeatherConditions object; discarding.")
                return None
            return conditions
        except Exception as exc:
            logger.error(
                "Error retrieving weather conditions for (%f, %f): %s",
                latitude,
                longitude,
                exc,
                exc_info=True,
            )
            return None


def get_weather_service() -> WeatherService:
    """FastAPI dependency provider for WeatherService."""
    return WeatherService()
