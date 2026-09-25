"""Provider status and health aggregation service."""

from datetime import datetime, timezone
import logging
from typing import Dict, Optional

from app.adapters.ocean import get_ocean_adapter
from app.adapters.pfz import get_pfz_adapter
from app.adapters.weather import get_weather_adapter
from app.core.config import Settings, get_settings
from app.models.provider import (
    FreshnessStatus,
    ProviderHealthInfo,
    ProviderStatus,
    SystemProvidersStatusResponse,
)
from app.repositories.geography_repository import get_default_geography_repository

logger = logging.getLogger(__name__)


class ProviderStatusService:
    """Service that queries operational readiness and status of all data providers without leaking secrets."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def get_system_status(self) -> SystemProvidersStatusResponse:
        """Collect sanitized operational status across Ocean, Weather, PFZ, and Geography domains."""
        providers: Dict[str, ProviderHealthInfo] = {}

        # 1. Ocean Provider Status
        try:
            ocean_adapter = get_ocean_adapter(self.settings)
            status = ocean_adapter.get_provider_status()
            providers["ocean"] = ProviderHealthInfo(
                provider_name=ocean_adapter.provider_name,
                provider_type="ocean",
                status=status,
                is_mock=(status == ProviderStatus.MOCK),
                endpoint_configured=bool(self.settings.OCEAN_API_URL),
                freshness=FreshnessStatus.MOCK if status == ProviderStatus.MOCK else FreshnessStatus.FRESH,
                message=f"Ocean provider '{ocean_adapter.provider_name}' in {status.value} state",
            )
        except Exception as exc:
            providers["ocean"] = ProviderHealthInfo(
                provider_name="unknown",
                provider_type="ocean",
                status=ProviderStatus.ERROR,
                is_mock=False,
                endpoint_configured=False,
                message=f"Error checking ocean provider: {exc}",
            )

        # 2. Weather Provider Status
        try:
            weather_adapter = get_weather_adapter(self.settings)
            status = weather_adapter.get_provider_status()
            providers["weather"] = ProviderHealthInfo(
                provider_name=weather_adapter.provider_name,
                provider_type="weather",
                status=status,
                is_mock=(status == ProviderStatus.MOCK),
                endpoint_configured=bool(self.settings.WEATHER_API_URL),
                freshness=FreshnessStatus.MOCK if status == ProviderStatus.MOCK else FreshnessStatus.FRESH,
                message=f"Weather provider '{weather_adapter.provider_name}' in {status.value} state",
            )
        except Exception as exc:
            providers["weather"] = ProviderHealthInfo(
                provider_name="unknown",
                provider_type="weather",
                status=ProviderStatus.ERROR,
                is_mock=False,
                endpoint_configured=False,
                message=f"Error checking weather provider: {exc}",
            )

        # 3. PFZ Provider Status
        try:
            pfz_adapter = get_pfz_adapter(self.settings)
            status = pfz_adapter.get_provider_status()
            feed_status = pfz_adapter.get_feed_status()
            providers["pfz"] = ProviderHealthInfo(
                provider_name=pfz_adapter.provider_name,
                provider_type="pfz",
                status=status,
                is_mock=False,
                endpoint_configured=bool(self.settings.PFZ_API_URL),
                freshness=FreshnessStatus(feed_status.freshness.value),
                last_successful_update=feed_status.last_updated,
                message=feed_status.message,
            )
        except Exception as exc:
            providers["pfz"] = ProviderHealthInfo(
                provider_name="unknown",
                provider_type="pfz",
                status=ProviderStatus.ERROR,
                is_mock=False,
                endpoint_configured=False,
                message=f"Error checking PFZ provider: {exc}",
            )

        # 4. Geography Spatial Repository Status
        try:
            repo = get_default_geography_repository()
            features = repo.list_features(limit=1)
            providers["geography"] = ProviderHealthInfo(
                provider_name="sqlite_geography_repository",
                provider_type="geography",
                status=ProviderStatus.AVAILABLE,
                is_mock=False,
                endpoint_configured=True,
                freshness=FreshnessStatus.FRESH,
                message="Spatial SQLite repository connected and operational",
            )
        except Exception as exc:
            providers["geography"] = ProviderHealthInfo(
                provider_name="sqlite_geography_repository",
                provider_type="geography",
                status=ProviderStatus.ERROR,
                is_mock=False,
                endpoint_configured=False,
                message=f"Spatial database error: {exc}",
            )

        # Compute overall system readiness
        has_error = any(p.status == ProviderStatus.ERROR for p in providers.values())
        overall = "operational" if not has_error else "degraded"

        return SystemProvidersStatusResponse(
            service=self.settings.PROJECT_NAME,
            overall_status=overall,
            providers=providers,
            timestamp=datetime.now(timezone.utc),
        )


def get_provider_status_service() -> ProviderStatusService:
    """FastAPI dependency provider."""
    return ProviderStatusService()
