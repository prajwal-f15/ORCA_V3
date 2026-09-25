"""Real/teammate PFZ adapter placeholder and contract readiness implementation."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from app.adapters.pfz.base import PFZAdapter
from app.models.pfz import PFZDatasetStatus, PFZFreshness, PFZObservation, PFZStatus, PFZZone
from app.models.provider import (
    ProviderConnectionError,
    ProviderNotConfiguredError,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


class RealPFZAdapter(PFZAdapter):
    """Adapter for live external / teammate PFZ prediction APIs.

    Requires explicit endpoint and credentials configuration.
    Fails explicitly with ProviderNotConfiguredError when unconfigured.
    """

    def __init__(
        self,
        provider_name: str = "teammate_api",
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._provider_name = provider_name
        self.api_url = api_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def get_provider_status(self) -> ProviderStatus:
        """Evaluate configuration state of the real PFZ provider."""
        if not self.api_url:
            return ProviderStatus.NOT_CONFIGURED
        return ProviderStatus.AVAILABLE

    def fetch_active_zones(self) -> List[PFZZone]:
        """Fetch active potential fishing zones from upstream teammate API.

        Raises:
            ProviderNotConfiguredError: If API endpoint is not configured.
            ProviderConnectionError: If network request fails.
        """
        if not self.api_url:
            raise ProviderNotConfiguredError(
                f"Real PFZ provider '{self._provider_name}' is not configured. Set PFZ_API_URL in environment/config.",
                provider=self._provider_name,
            )

        logger.info("Connecting to real PFZ provider '%s' at %s", self._provider_name, self.api_url)
        raise ProviderConnectionError(
            f"Real PFZ provider '{self._provider_name}' endpoint '{self.api_url}' connection pending teammate provider contract integration.",
            provider=self._provider_name,
        )

    def fetch_latest_observations(self) -> List[PFZObservation]:
        """Fetch latest prediction observations from teammate API."""
        if not self.api_url:
            raise ProviderNotConfiguredError(
                f"Real PFZ provider '{self._provider_name}' is not configured. Set PFZ_API_URL in environment/config.",
                provider=self._provider_name,
            )
        raise ProviderConnectionError(
            f"Real PFZ provider '{self._provider_name}' endpoint '{self.api_url}' connection pending teammate provider contract integration.",
            provider=self._provider_name,
        )

    def get_feed_status(self) -> PFZStatus:
        """Query operational status of the teammate PFZ feed."""
        if not self.api_url:
            return PFZStatus(
                source=self._provider_name,
                source_url=None,
                last_updated=None,
                freshness=PFZFreshness.PENDING,
                dataset_status=PFZDatasetStatus.PENDING,
                feature_count=0,
                model_version=None,
                message=f"PFZ provider '{self._provider_name}' is not configured with a live API endpoint.",
            )
        return PFZStatus(
            source=self._provider_name,
            source_url=self.api_url,
            last_updated=datetime.now(timezone.utc),
            freshness=PFZFreshness.FRESH,
            dataset_status=PFZDatasetStatus.AVAILABLE,
            feature_count=0,
            model_version="teammate-v1",
            message=f"PFZ provider '{self._provider_name}' configured at {self.api_url}",
        )
