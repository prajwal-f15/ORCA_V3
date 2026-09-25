"""Unit and integration tests for external adapter contracts and provider switching mechanisms."""

from datetime import datetime, timezone
import pytest

from app.adapters.ocean import MockOceanAdapter, RealOceanAdapter, get_ocean_adapter
from app.adapters.pfz import IncoisPFZAdapter, RealPFZAdapter, get_pfz_adapter
from app.adapters.weather import MockWeatherAdapter, RealWeatherAdapter, get_weather_adapter
from app.core.config import Settings
from app.models.marine_conditions import (
    MarineConditionsSnapshot,
    OceanConditions,
    WeatherConditions,
)
from app.models.provider import (
    ProviderConnectionError,
    ProviderNotConfiguredError,
    ProviderStatus,
)
from app.models.request import Coordinate, Vessel
from app.models.safety import CheckStatus, SafetyDecision
from app.services.marine_conditions_service import MarineConditionsService
from app.services.safety_governor_service import SafetyGovernorService


# ============================================================================
# 1. DEFAULT CONFIGURATION TESTS (MOCK PROVIDERS)
# ============================================================================

def test_default_settings_resolve_mock_adapters() -> None:
    """Verify default settings instantiate mock adapters in MOCK status."""
    default_settings = Settings()
    ocean_adapter = get_ocean_adapter(default_settings)
    weather_adapter = get_weather_adapter(default_settings)
    pfz_adapter = get_pfz_adapter(default_settings)

    assert isinstance(ocean_adapter, MockOceanAdapter)
    assert ocean_adapter.get_provider_status() == ProviderStatus.MOCK
    assert ocean_adapter.provider_name == "mock"

    assert isinstance(weather_adapter, MockWeatherAdapter)
    assert weather_adapter.get_provider_status() == ProviderStatus.MOCK
    assert weather_adapter.provider_name == "mock"

    assert isinstance(pfz_adapter, IncoisPFZAdapter)


def test_mock_adapters_return_frozen_internal_models() -> None:
    """Verify mock adapters return standard OceanConditions and WeatherConditions models."""
    ocean_adapter = MockOceanAdapter()
    weather_adapter = MockWeatherAdapter()

    ocean_res = ocean_adapter.get_conditions(latitude=18.52, longitude=72.85)
    weather_res = weather_adapter.get_conditions(latitude=18.52, longitude=72.85)

    assert isinstance(ocean_res, OceanConditions)
    assert ocean_res.source == "mock"
    assert ocean_res.significant_wave_height_m is not None

    assert isinstance(weather_res, WeatherConditions)
    assert weather_res.source == "mock"
    assert weather_res.wind_speed_knots is not None


# ============================================================================
# 2. REAL PROVIDER CONFIGURATION & EXPLICIT ERROR TESTS
# ============================================================================

def test_real_ocean_adapter_unconfigured_fails_explicitly() -> None:
    """Verify selecting a real ocean provider without API_URL raises ProviderNotConfiguredError."""
    settings = Settings(OCEAN_PROVIDER="incois", OCEAN_API_URL=None)
    adapter = get_ocean_adapter(settings)

    assert isinstance(adapter, RealOceanAdapter)
    assert adapter.get_provider_status() == ProviderStatus.NOT_CONFIGURED

    with pytest.raises(ProviderNotConfiguredError) as exc_info:
        adapter.get_conditions(latitude=18.52, longitude=72.85)

    assert "not configured" in str(exc_info.value).lower()
    assert exc_info.value.provider == "incois"


def test_real_weather_adapter_unconfigured_fails_explicitly() -> None:
    """Verify selecting a real weather provider without API_URL raises ProviderNotConfiguredError."""
    settings = Settings(WEATHER_PROVIDER="imd", WEATHER_API_URL=None)
    adapter = get_weather_adapter(settings)

    assert isinstance(adapter, RealWeatherAdapter)
    assert adapter.get_provider_status() == ProviderStatus.NOT_CONFIGURED

    with pytest.raises(ProviderNotConfiguredError) as exc_info:
        adapter.get_conditions(latitude=18.52, longitude=72.85)

    assert "not configured" in str(exc_info.value).lower()
    assert exc_info.value.provider == "imd"


def test_real_pfz_adapter_unconfigured_fails_explicitly() -> None:
    """Verify selecting a real PFZ provider without API_URL raises ProviderNotConfiguredError."""
    settings = Settings(PFZ_PROVIDER="teammate_api", PFZ_API_URL=None)
    adapter = get_pfz_adapter(settings)

    assert isinstance(adapter, RealPFZAdapter)
    assert adapter.get_provider_status() == ProviderStatus.NOT_CONFIGURED

    with pytest.raises(ProviderNotConfiguredError):
        adapter.fetch_active_zones()


def test_configured_real_provider_reports_available_status() -> None:
    """Verify configured real providers report AVAILABLE status."""
    ocean_adapter = RealOceanAdapter(
        provider_name="hycom",
        api_url="https://hycom.example.gov/v1/ocean",
        api_key="secret-key-123",
    )
    weather_adapter = RealWeatherAdapter(
        provider_name="wrf",
        api_url="https://wrf.example.gov/v1/meteo",
        api_key="secret-key-456",
    )

    assert ocean_adapter.get_provider_status() == ProviderStatus.AVAILABLE
    assert weather_adapter.get_provider_status() == ProviderStatus.AVAILABLE


def test_unsupported_provider_names_raise_value_error() -> None:
    """Verify configuring an unknown provider raises a clear ValueError."""
    with pytest.raises(ValueError):
        get_ocean_adapter(Settings(OCEAN_PROVIDER="invalid_ocean_provider"))

    with pytest.raises(ValueError):
        get_weather_adapter(Settings(WEATHER_PROVIDER="invalid_weather_provider"))

    with pytest.raises(ValueError):
        get_pfz_adapter(Settings(PFZ_PROVIDER="invalid_pfz_provider"))


# ============================================================================
# 3. NO SILENT FALLBACK TO MOCK ON REAL PROVIDER FAILURE
# ============================================================================

def test_real_provider_failure_does_not_silently_fallback_to_mock() -> None:
    """Verify unconfigured real provider does NOT return fake/mock data."""
    marine_svc = MarineConditionsService(
        ocean_adapter=RealOceanAdapter(api_url=None),
        weather_adapter=RealWeatherAdapter(api_url=None),
    )
    snapshot = marine_svc.get_snapshot(latitude=18.52, longitude=72.85)

    # When real providers fail/unconfigured, snapshot reflects unavailable/partial status, not mock data
    assert snapshot.status in ["unavailable", "partial"]
    assert snapshot.ocean is None
    assert snapshot.weather is None


# ============================================================================
# 4. SAFETY GOVERNOR AUDIT WITH FROZEN CONTRACTS
# ============================================================================

def test_safety_governor_evaluates_real_provider_conditions_authoritatively() -> None:
    """Verify Safety Governor evaluates real-provider structured models correctly."""
    safety_gov = SafetyGovernorService()
    wps = [Coordinate(latitude=18.52, longitude=72.85), Coordinate(latitude=18.65, longitude=72.90)]
    vessel = Vessel(speed_knots=10.0, draft_meters=2.0)

    # Conditions tagged as live verified provider
    verified_snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="incois_hycom", significant_wave_height_m=1.1, current_speed_knots=0.8),
        weather=WeatherConditions(source="imd_wrf", wind_speed_knots=10.0, visibility_km=15.0),
    )

    result = safety_gov.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=verified_snapshot)
    assert result.decision == SafetyDecision.ALLOW
    assert result.checks["ocean"] == CheckStatus.PASS.value
    assert result.checks["weather"] == CheckStatus.PASS.value
    assert result.checks["data_quality"] == CheckStatus.PASS.value
    assert len(result.blocking_reasons) == 0
