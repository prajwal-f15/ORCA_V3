"""Oceanographic service handling ocean conditions retrieval and normalization."""

import logging
from datetime import datetime
from typing import Optional

from app.adapters.ocean.base import OceanAdapter
from app.adapters.ocean import get_ocean_adapter
from app.models.marine_conditions import OceanConditions

logger = logging.getLogger(__name__)


class OceanService:
    """Service providing ocean current, wave, and sea temperature data.

    NOTE: OceanService never makes final navigational safety decisions.
    All safety constraints remain strictly with the Safety Governor.
    """

    def __init__(self, adapter: Optional[OceanAdapter] = None) -> None:
        self.adapter = adapter or get_ocean_adapter()

    def get_ocean_conditions(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[OceanConditions]:
        """Fetch and validate normalized oceanographic conditions.

        Args:
            latitude: Target latitude in decimal degrees.
            longitude: Target longitude in decimal degrees.
            timestamp: Optional UTC timestamp for assessment.

        Returns:
            Normalized OceanConditions instance or None if unavailable/error occurs.
        """
        try:
            conditions = self.adapter.get_conditions(
                latitude=latitude,
                longitude=longitude,
                timestamp=timestamp,
            )
            if conditions is not None and not isinstance(conditions, OceanConditions):
                logger.warning("Adapter returned non-OceanConditions object; discarding.")
                return None
            return conditions
        except Exception as exc:
            logger.error(
                "Error retrieving ocean conditions for (%f, %f): %s",
                latitude,
                longitude,
                exc,
                exc_info=True,
            )
            return None


def get_ocean_service() -> OceanService:
    """FastAPI dependency provider for OceanService."""
    return OceanService()
