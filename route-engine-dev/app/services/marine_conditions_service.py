"""Orchestration service combining Ocean and Weather conditions into a normalized snapshot."""

import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.marine_conditions import (
    MarineConditionsSnapshot,
    OceanConditions,
    WeatherConditions,
)
from app.models.request import Coordinate
from app.services.ocean_service import OceanService
from app.services.weather_service import WeatherService

logger = logging.getLogger(__name__)


class MarineConditionsService:
    """Orchestrates oceanographic and meteorological feeds into unified environmental snapshots.

    IMPORTANT SAFETY NOTICE:
    This service is solely an aggregation/normalization pipeline.
    It does NOT make navigation safety decisions or compute ALLOW/WARN/REJECT verdicts.
    All safety validation is strictly reserved for the Safety Governor.
    """

    def __init__(
        self,
        ocean_service: Optional[OceanService] = None,
        weather_service: Optional[WeatherService] = None,
        ocean_adapter: Optional[Any] = None,
        weather_adapter: Optional[Any] = None,
    ) -> None:
        if ocean_service is not None:
            self.ocean_service = ocean_service
        elif ocean_adapter is not None:
            self.ocean_service = OceanService(adapter=ocean_adapter)
        else:
            self.ocean_service = OceanService()

        if weather_service is not None:
            self.weather_service = weather_service
        elif weather_adapter is not None:
            self.weather_service = WeatherService(adapter=weather_adapter)
        else:
            self.weather_service = WeatherService()

    def get_snapshot(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> MarineConditionsSnapshot:
        """Fetch unified ocean + weather environmental snapshot for a geographic coordinate.

        Args:
            latitude: Target latitude in decimal degrees.
            longitude: Target longitude in decimal degrees.
            timestamp: Optional UTC timestamp for assessment.

        Returns:
            Normalized MarineConditionsSnapshot containing ocean, weather, and status summary.
        """
        eval_time = timestamp or datetime.now(timezone.utc)
        coord = Coordinate(latitude=latitude, longitude=longitude)

        ocean: Optional[OceanConditions] = self.ocean_service.get_ocean_conditions(
            latitude=latitude,
            longitude=longitude,
            timestamp=eval_time,
        )

        weather: Optional[WeatherConditions] = self.weather_service.get_weather_conditions(
            latitude=latitude,
            longitude=longitude,
            timestamp=eval_time,
        )

        # Build source summary
        source_summary: dict[str, str] = {}
        if ocean:
            source_summary["ocean"] = ocean.source
        if weather:
            source_summary["weather"] = weather.source

        # Determine data availability status
        if ocean is None and weather is None:
            status = "unavailable"
        elif ocean is not None and weather is not None:
            if ocean.source == "mock" or weather.source == "mock":
                status = "mock"
            else:
                status = "available"
        else:
            status = "partial"

        return MarineConditionsSnapshot(
            position=coord,
            timestamp=eval_time,
            ocean=ocean,
            weather=weather,
            status=status,
            source_summary=source_summary,
            metadata={
                "ocean_available": ocean is not None,
                "weather_available": weather is not None,
            },
        )


def get_marine_conditions_service() -> MarineConditionsService:
    """FastAPI dependency provider for MarineConditionsService."""
    return MarineConditionsService()
