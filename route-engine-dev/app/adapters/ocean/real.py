"""Real/live oceanographic adapter placeholder and contract readiness implementation."""

from datetime import datetime, timezone
import logging
from typing import Optional

from app.adapters.ocean.base import OceanAdapter
from app.adapters.resilience import ResponseValidator, execute_with_resilience
from app.models.marine_conditions import OceanConditions
from app.models.provider import (
    ProviderConnectionError,
    ProviderNotConfiguredError,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


class RealOceanAdapter(OceanAdapter):
    """Adapter for live external Ocean providers (e.g. INCOIS-HYCOM or teammate API).

    Requires explicit endpoint and credentials configuration.
    Fails explicitly with ProviderNotConfiguredError when unconfigured rather than returning fake data.
    """

    def __init__(
        self,
        provider_name: str = "incois",
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self._provider_name = provider_name
        self.api_url = api_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def get_provider_status(self) -> ProviderStatus:
        """Evaluate configuration state of the real ocean provider."""
        if not self.api_url:
            return ProviderStatus.NOT_CONFIGURED
        return ProviderStatus.AVAILABLE

    def get_conditions(
        self,
        latitude: float,
        longitude: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[OceanConditions]:
        """Fetch real oceanographic conditions with resilience, timeout, and response validation.

        Raises:
            ProviderNotConfiguredError: If API endpoint/URL is not configured.
            ProviderConnectionError / ProviderTimeoutError: If live request fails.
        """
        if not self.api_url:
            raise ProviderNotConfiguredError(
                f"Real Ocean provider '{self._provider_name}' is not configured. Set OCEAN_API_URL in environment/config.",
                provider=self._provider_name,
            )

        def _fetch():
            logger.info(
                "Connecting to real ocean provider '%s' at %s for (%f, %f)",
                self._provider_name,
                self.api_url,
                latitude,
                longitude,
            )
            # Pending real contract implementation
            raise ProviderConnectionError(
                f"Real Ocean provider '{self._provider_name}' endpoint '{self.api_url}' connection pending official provider contract integration.",
                provider=self._provider_name,
            )

        return execute_with_resilience(
            func=_fetch,
            provider_name=self._provider_name,
            timeout_seconds=self.timeout_seconds,
        )
