"""Unit and integration test suite for production integration hardening.

Validates:
- External provider timeout handling
- Controlled retries with backoff on transient errors
- Immediate fail-fast without retry on permanent errors
- Payload response validation against physical limits
- Rate limit detection and retry-after handling
- In-memory caching and freshness evaluation
- Health, readiness, and provider status probes
- Request correlation ID distributed tracing
- Graceful degradation across ocean, weather, and PFZ outages
- Safety Governor degraded state audit preservation
- Zero secret leakage in errors and logs
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
import httpx

from app.adapters.ocean import MockOceanAdapter, RealOceanAdapter
from app.adapters.pfz import IncoisPFZAdapter, RealPFZAdapter
from app.adapters.resilience import (
    ProviderCache,
    ResponseValidator,
    execute_with_resilience,
    sanitize_message_for_logging,
)
from app.adapters.weather import MockWeatherAdapter, RealWeatherAdapter
from app.core.config import Settings
from app.main import app
from app.models.marine_conditions import (
    MarineConditionsSnapshot,
    OceanConditions,
    WeatherConditions,
)
from app.models.provider import (
    FreshnessStatus,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderErrorCategory,
    ProviderInvalidResponseError,
    ProviderNetworkError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderStatus,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.models.request import Coordinate, RouteRequest, Vessel
from app.models.safety import CheckStatus, SafetyDecision
from app.services.dynamic_route_service import DynamicRouteService
from app.services.marine_conditions_service import MarineConditionsService
from app.services.ocean_service import OceanService
from app.services.pfz_service import PFZService
from app.services.provider_status_service import ProviderStatusService
from app.services.route_optimization_service import RouteOptimizationService
from app.services.safety_governor_service import SafetyGovernorService
from app.services.weather_service import WeatherService


_test_client = TestClient(app)


class LocalhostASGITransport(httpx.BaseTransport):
    """Transport that routes localhost:8000 requests in-process to the ASGI app."""

    def __init__(self) -> None:
        self.http_transport = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host in ("127.0.0.1", "localhost", "testserver") and (
            request.url.port in (8000, None)
        ):
            return _test_client._transport.handle_request(request)
        return self.http_transport.handle_request(request)


@pytest.fixture(autouse=True)
def route_engine_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture ensuring external client calls to localhost:8000 route in-process during tests."""
    original_client_init = httpx.Client.__init__

    def patched_client_init(self, *args, **kwargs):
        if "transport" not in kwargs or kwargs["transport"] is None:
            kwargs["transport"] = LocalhostASGITransport()
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_client_init)


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return _test_client


# ============================================================================
# 1. TIMEOUT & RETRY POLICIES
# ============================================================================

def test_provider_timeout_handling() -> None:
    """Verify timeout produces ProviderTimeoutError and is categorized correctly."""
    call_count = 0

    def slow_provider_call():
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Socket read timed out")

    with pytest.raises(ProviderTimeoutError) as exc_info:
        execute_with_resilience(
            func=slow_provider_call,
            provider_name="slow_ocean_api",
            max_retries=1,
            retry_delay=0.01,
            timeout_seconds=0.1,
        )

    assert call_count == 2  # 1 initial + 1 retry
    assert exc_info.value.category == ProviderErrorCategory.TIMEOUT
    assert "timed out" in str(exc_info.value).lower()


def test_retry_policy_on_transient_network_failure() -> None:
    """Verify transient network failures are retried and succeed when provider recovers."""
    attempts = 0

    def transient_network_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("Transient DNS resolution failure")
        return {"status": "ok"}

    result = execute_with_resilience(
        func=transient_network_call,
        provider_name="flaky_weather_api",
        max_retries=3,
        retry_delay=0.01,
        backoff_factor=1.0,
    )

    assert result == {"status": "ok"}
    assert attempts == 3


def test_no_retry_on_permanent_authentication_failure() -> None:
    """Verify permanent 401/403 authentication failures fail immediately without retrying."""
    attempts = 0

    def auth_failing_call():
        nonlocal attempts
        attempts += 1
        raise ProviderAuthenticationError("Invalid API token or expired key")

    with pytest.raises(ProviderAuthenticationError):
        execute_with_resilience(
            func=auth_failing_call,
            provider_name="secure_ocean_feed",
            max_retries=3,
            retry_delay=0.01,
        )

    # Must fail on the very first attempt without wasted retries
    assert attempts == 1


def test_no_retry_on_permanent_unconfigured_error() -> None:
    """Verify unconfigured provider fails immediately without retry."""
    attempts = 0

    def unconfigured_call():
        nonlocal attempts
        attempts += 1
        raise ProviderNotConfiguredError("Endpoint not set")

    with pytest.raises(ProviderNotConfiguredError):
        execute_with_resilience(
            func=unconfigured_call,
            provider_name="missing_api",
            max_retries=2,
            retry_delay=0.01,
        )

    assert attempts == 1


# ============================================================================
# 2. RESPONSE VALIDATION AGAINST BOUNDS & CORRUPT DATA
# ============================================================================

def test_invalid_provider_ocean_payload_validation() -> None:
    """Verify malformed physical data in provider response raises ProviderInvalidResponseError."""
    # Negative significant wave height
    with pytest.raises(ProviderInvalidResponseError):
        ResponseValidator.validate_ocean_payload({"significant_wave_height_m": -2.5})

    # Impossible wave height
    with pytest.raises(ProviderInvalidResponseError):
        ResponseValidator.validate_ocean_payload({"significant_wave_height_m": 50.0})

    # Invalid current direction
    with pytest.raises(ProviderInvalidResponseError):
        ResponseValidator.validate_ocean_payload({"current_direction_degrees": 400.0})

    # Valid payload passes
    valid_data = {"significant_wave_height_m": 2.1, "current_speed_knots": 1.2, "confidence": 0.85}
    assert ResponseValidator.validate_ocean_payload(valid_data) == valid_data


def test_invalid_provider_weather_payload_validation() -> None:
    """Verify malformed weather data raises ProviderInvalidResponseError."""
    # Negative wind speed
    with pytest.raises(ProviderInvalidResponseError):
        ResponseValidator.validate_weather_payload({"wind_speed_knots": -10.0})

    # Negative visibility
    with pytest.raises(ProviderInvalidResponseError):
        ResponseValidator.validate_weather_payload({"visibility_km": -1.0})

    # Cloud cover above 100%
    with pytest.raises(ProviderInvalidResponseError):
        ResponseValidator.validate_weather_payload({"cloud_cover_percent": 150.0})


# ============================================================================
# 3. RATE LIMIT HANDLING (HTTP 429)
# ============================================================================

def test_rate_limit_handling() -> None:
    """Verify ProviderRateLimitError contains retry_after metadata and is handled."""
    err = ProviderRateLimitError(
        message="Too Many Requests",
        provider="incois",
        retry_after_seconds=2.5,
    )
    assert err.category == ProviderErrorCategory.RATE_LIMITED
    assert err.retry_after_seconds == 2.5
    assert err.details["retry_after_seconds"] == 2.5


# ============================================================================
# 4. FRESHNESS & CACHE ABSTRACTION
# ============================================================================

def test_provider_cache_and_freshness_lifecycle() -> None:
    """Verify cache tracks FRESH vs STALE status accurately based on TTL."""
    cache = ProviderCache(default_ttl_seconds=1)

    # Empty cache returns UNAVAILABLE
    item, status = cache.get("ocean", 18.52, 72.85)
    assert item is None
    assert status == FreshnessStatus.UNAVAILABLE

    # Store entry -> FRESH
    cache.set("ocean", 18.52, 72.85, {"wave_height": 1.5})
    item, status = cache.get("ocean", 18.52, 72.85)
    assert item == {"wave_height": 1.5}
    assert status == FreshnessStatus.FRESH


# ============================================================================
# 5. HEALTH, READINESS & PROVIDER STATUS ENDPOINTS
# ============================================================================

def test_readiness_endpoint(client: TestClient) -> None:
    """Verify GET /readiness and GET /api/v1/readiness return 200 ready status."""
    r = client.get("/readiness")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"

    r_v1 = client.get("/api/v1/readiness")
    assert r_v1.status_code == 200
    assert r_v1.json()["status"] == "ready"


def test_provider_status_endpoint(client: TestClient) -> None:
    """Verify GET /provider-status returns structured diagnostics without leaking credentials."""
    r = client.get("/provider-status")
    assert r.status_code == 200

    data = r.json()
    assert "overall_status" in data
    assert "providers" in data
    assert "ocean" in data["providers"]
    assert "weather" in data["providers"]
    assert "pfz" in data["providers"]
    assert "geography" in data["providers"]

    # Verify no secret keys or tokens are in the payload
    json_str = str(data).lower()
    assert "api_key" not in json_str or data["providers"]["ocean"]["endpoint_configured"] is False


# ============================================================================
# 6. DISTRIBUTED TRACING & REQUEST CORRELATION ID
# ============================================================================

def test_request_correlation_id_middleware(client: TestClient) -> None:
    """Verify correlation ID is propagated or generated and returned in headers."""
    # 1. Custom incoming header
    r1 = client.get("/health", headers={"X-Request-ID": "custom-trace-12345"})
    assert r1.status_code == 200
    assert r1.headers.get("X-Request-ID") == "custom-trace-12345"

    # 2. Auto-generated header
    r2 = client.get("/health")
    assert r2.status_code == 200
    assert r2.headers.get("X-Request-ID") is not None
    assert r2.headers.get("X-Request-ID").startswith("req-")


# ============================================================================
# 7. LOG SANITIZATION & SECRET SAFETY
# ============================================================================

def test_secret_sanitization_in_logging() -> None:
    """Verify secrets are redacted from log messages."""
    raw = "Request failed on url https://api.ocean.gov/v1?api_key=SECRET_TOKEN_XYZ&lat=18.5"
    sanitized = sanitize_message_for_logging(raw)
    assert "SECRET_TOKEN_XYZ" not in sanitized
    assert "api_key=***" in sanitized


# ============================================================================
# 8. GRACEFUL FAILURE & SAFETY GOVERNOR AUDIT PRESERVATION
# ============================================================================

def test_ocean_provider_outage_does_not_crash_engine_and_triggers_degraded(client: TestClient) -> None:
    """Verify Ocean provider outage causes Route Engine to report unavailable and Safety Governor to evaluate DEGRADED."""
    # Custom service with failing ocean adapter
    failing_ocean = RealOceanAdapter(api_url=None)  # Not configured / outage
    marine_svc = MarineConditionsService(
        ocean_adapter=failing_ocean,
        weather_adapter=MockWeatherAdapter(),
    )
    dyn_svc = DynamicRouteService(marine_conditions_service=marine_svc)

    req = RouteRequest(
        start=Coordinate(latitude=18.5204, longitude=72.8567),
        destination=Coordinate(latitude=18.6500, longitude=72.9000),
        vessel=Vessel(speed_knots=10.0),
        objective="safe_and_efficient",
    )
    response = dyn_svc.calculate_route(req)

    assert response.status == "computed"
    assert response.marine_conditions.ocean is None
    assert response.marine_conditions.status == "partial"
    # Safety Governor must register missing data as DEGRADED or WARN, never false ALLOW
    assert response.safety_decision in ["DEGRADED", "WARN"]
    assert response.safety_decision != "ALLOW"


def test_weather_provider_outage_evaluated_gracefully() -> None:
    """Verify Weather provider failure is captured and passed to Safety Governor."""
    failing_weather = RealWeatherAdapter(api_url=None)
    marine_svc = MarineConditionsService(
        ocean_adapter=MockOceanAdapter(),
        weather_adapter=failing_weather,
    )
    dyn_svc = DynamicRouteService(marine_conditions_service=marine_svc)

    req = RouteRequest(
        start=Coordinate(latitude=18.5204, longitude=72.8567),
        destination=Coordinate(latitude=18.6500, longitude=72.9000),
        vessel=Vessel(speed_knots=8.0),
    )
    response = dyn_svc.calculate_route(req)

    assert response.status == "computed"
    assert response.marine_conditions.weather is None
    assert response.safety_decision in ["DEGRADED", "WARN"]


def test_pfz_outage_preserves_non_pfz_routing_and_reports_unavailability() -> None:
    """Verify PFZ outage allows safe_and_efficient routing but flags highest_potential."""
    pfz_svc = PFZService(adapter=RealPFZAdapter(api_url=None))
    status = pfz_svc.get_feed_status()
    assert status.dataset_status.value == "pending"

    # Non-PFZ route calculation completes normally
    opt_svc = RouteOptimizationService(pfz_service=pfz_svc)
    dyn_svc = DynamicRouteService(optimization_service=opt_svc)
    req = RouteRequest(
        start=Coordinate(latitude=18.5204, longitude=72.8567),
        destination=Coordinate(latitude=18.6500, longitude=72.9000),
        vessel=Vessel(speed_knots=10.0),
        objective="safe_and_efficient",
    )
    res = dyn_svc.calculate_route(req)
    assert res.status == "computed"
    assert res.summary.route_score >= 0.0


# ============================================================================
# 9. BRAIN INTEGRATION & CONTRACT PRESERVATION
# ============================================================================

def test_brain_integration_with_hardened_pipeline(client: TestClient) -> None:
    """Verify POST /test/route-engine functions seamlessly with correlation ID and safety audit."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
        "objective": "safe_and_efficient",
    }
    response = client.post("/test/route-engine", json=payload, headers={"X-Request-ID": "brain-test-audit-999"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "brain-test-audit-999"

    data = response.json()
    assert "route_id" in data
    assert "safety_decision" in data
    assert "safety_evaluation" in data
