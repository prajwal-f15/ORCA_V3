"""Unit and integration tests for Marine, Oceanographic, and Meteorological Conditions subsystem."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.ocean.base import OceanAdapter
from app.adapters.ocean.mock import MockOceanAdapter
from app.adapters.ocean import get_ocean_adapter
from app.adapters.weather.base import WeatherAdapter
from app.adapters.weather.mock import MockWeatherAdapter
from app.adapters.weather import get_weather_adapter
from app.core.config import Settings
from app.main import app
from app.models.marine_conditions import (
    MarineConditionsSnapshot,
    OceanConditions,
    WeatherConditions,
)
from app.models.request import Coordinate, RouteRequest, Vessel
from app.services.marine_conditions_service import (
    MarineConditionsService,
    get_marine_conditions_service,
)
from app.services.ocean_service import OceanService, get_ocean_service
from app.services.route_service import RouteService
from app.services.weather_service import WeatherService, get_weather_service


@pytest.fixture
def client() -> TestClient:
    """Fixture providing FastAPI TestClient."""
    return TestClient(app)


# ============================================================================
# 1. MODEL VALIDATION TESTS
# ============================================================================

def test_ocean_conditions_model_valid() -> None:
    """Verify OceanConditions instantiates with valid parameters."""
    now = datetime.now(timezone.utc)
    cond = OceanConditions(
        timestamp=now,
        source="incois_hycom",
        source_version="v2.1",
        confidence=0.88,
        current_speed_knots=1.5,
        current_direction_degrees=135.0,
        significant_wave_height_m=2.2,
        wave_period_seconds=8.0,
        wave_direction_degrees=210.0,
        sea_surface_temperature_c=28.5,
        salinity_psu=34.9,
        metadata={"grid_res_km": 5.0},
    )
    assert cond.timestamp == now
    assert cond.source == "incois_hycom"
    assert cond.confidence == 0.88
    assert cond.current_speed_knots == 1.5
    assert cond.current_direction_degrees == 135.0
    assert cond.significant_wave_height_m == 2.2
    assert cond.wave_period_seconds == 8.0
    assert cond.sea_surface_temperature_c == 28.5
    assert cond.salinity_psu == 34.9
    assert cond.metadata["grid_res_km"] == 5.0


def test_ocean_conditions_bounds_validation() -> None:
    """Verify OceanConditions enforces physical boundary constraints."""
    # Negative current speed
    with pytest.raises(ValidationError):
        OceanConditions(current_speed_knots=-0.5)

    # Invalid direction (>= 360)
    with pytest.raises(ValidationError):
        OceanConditions(current_direction_degrees=360.0)

    # Confidence out of bounds
    with pytest.raises(ValidationError):
        OceanConditions(confidence=1.5)


def test_weather_conditions_model_valid() -> None:
    """Verify WeatherConditions instantiates with valid parameters."""
    now = datetime.now(timezone.utc)
    weather = WeatherConditions(
        timestamp=now,
        source="imd_wrf",
        source_version="v4.0",
        confidence=0.92,
        wind_speed_knots=18.0,
        wind_direction_degrees=280.0,
        wind_gust_knots=24.5,
        air_temperature_c=31.2,
        visibility_km=12.0,
        pressure_hpa=1009.5,
        precipitation_mm_h=0.5,
        cloud_cover_percent=60.0,
    )
    assert weather.source == "imd_wrf"
    assert weather.wind_speed_knots == 18.0
    assert weather.wind_direction_degrees == 280.0
    assert weather.pressure_hpa == 1009.5
    assert weather.cloud_cover_percent == 60.0


def test_weather_conditions_bounds_validation() -> None:
    """Verify WeatherConditions enforces meteorological boundary limits."""
    # Negative wind speed
    with pytest.raises(ValidationError):
        WeatherConditions(wind_speed_knots=-2.0)

    # Cloud cover > 100
    with pytest.raises(ValidationError):
        WeatherConditions(cloud_cover_percent=105.0)

    # Pressure out of terrestrial range (< 800 or > 1100 hPa)
    with pytest.raises(ValidationError):
        WeatherConditions(pressure_hpa=750.0)


def test_partial_conditions_allowed() -> None:
    """Verify models allow missing/partial fields without crashing (future API flexibility)."""
    minimal_ocean = OceanConditions()
    assert minimal_ocean.source == "mock"
    assert minimal_ocean.current_speed_knots is None
    assert minimal_ocean.significant_wave_height_m is None

    minimal_weather = WeatherConditions()
    assert minimal_weather.source == "mock"
    assert minimal_weather.wind_speed_knots is None
    assert minimal_weather.visibility_km is None


def test_marine_conditions_snapshot_model() -> None:
    """Verify MarineConditionsSnapshot wraps position, ocean, weather, and status."""
    coord = Coordinate(latitude=18.52, longitude=72.85)
    ocean = OceanConditions(current_speed_knots=1.0)
    weather = WeatherConditions(wind_speed_knots=12.0)

    snapshot = MarineConditionsSnapshot(
        position=coord,
        ocean=ocean,
        weather=weather,
        status="mock",
        source_summary={"ocean": "mock", "weather": "mock"},
    )
    assert snapshot.position.latitude == 18.52
    assert snapshot.position.longitude == 72.85
    assert snapshot.ocean.current_speed_knots == 1.0
    assert snapshot.weather.wind_speed_knots == 12.0
    assert snapshot.status == "mock"


# ============================================================================
# 2. ADAPTER TESTS
# ============================================================================

def test_mock_ocean_adapter_deterministic() -> None:
    """Verify MockOceanAdapter returns deterministic values with source='mock'."""
    adapter = MockOceanAdapter(
        current_speed_knots=1.4,
        significant_wave_height_m=2.0,
        sea_surface_temperature_c=29.0,
    )
    res = adapter.get_conditions(latitude=18.5, longitude=72.8)
    assert res is not None
    assert res.source == "mock"
    assert res.current_speed_knots == 1.4
    assert res.significant_wave_height_m == 2.0
    assert res.sea_surface_temperature_c == 29.0
    assert res.metadata["adapter"] == "MockOceanAdapter"


def test_mock_weather_adapter_deterministic() -> None:
    """Verify MockWeatherAdapter returns deterministic values with source='mock'."""
    adapter = MockWeatherAdapter(
        wind_speed_knots=16.0,
        wind_direction_degrees=240.0,
        air_temperature_c=30.0,
    )
    res = adapter.get_conditions(latitude=18.5, longitude=72.8)
    assert res is not None
    assert res.source == "mock"
    assert res.wind_speed_knots == 16.0
    assert res.wind_direction_degrees == 240.0
    assert res.air_temperature_c == 30.0
    assert res.metadata["adapter"] == "MockWeatherAdapter"


# ============================================================================
# 3. SERVICE LAYER TESTS
# ============================================================================

def test_ocean_service_success() -> None:
    """Test OceanService retrieves data from adapter."""
    service = OceanService(adapter=MockOceanAdapter())
    data = service.get_ocean_conditions(latitude=18.0, longitude=72.0)
    assert data is not None
    assert data.source == "mock"


def test_ocean_service_handles_adapter_exception() -> None:
    """Test OceanService catches adapter failures and cleanly returns None."""
    class FailingOceanAdapter(OceanAdapter):
        def get_conditions(self, latitude, longitude, timestamp=None):
            raise ConnectionError("Teammate ocean API unreachable")

    service = OceanService(adapter=FailingOceanAdapter())
    data = service.get_ocean_conditions(latitude=18.0, longitude=72.0)
    assert data is None


def test_weather_service_success() -> None:
    """Test WeatherService retrieves data from adapter."""
    service = WeatherService(adapter=MockWeatherAdapter())
    data = service.get_weather_conditions(latitude=18.0, longitude=72.0)
    assert data is not None
    assert data.source == "mock"


def test_weather_service_handles_adapter_exception() -> None:
    """Test WeatherService catches adapter failures and cleanly returns None."""
    class FailingWeatherAdapter(WeatherAdapter):
        def get_conditions(self, latitude, longitude, timestamp=None):
            raise TimeoutError("Weather upstream timeout")

    service = WeatherService(adapter=FailingWeatherAdapter())
    data = service.get_weather_conditions(latitude=18.0, longitude=72.0)
    assert data is None


def test_marine_conditions_service_orchestration() -> None:
    """Test MarineConditionsService builds complete unified snapshot."""
    service = MarineConditionsService(
        ocean_service=OceanService(MockOceanAdapter()),
        weather_service=WeatherService(MockWeatherAdapter()),
    )
    snapshot = service.get_snapshot(latitude=18.5, longitude=72.8)

    assert snapshot.position.latitude == 18.5
    assert snapshot.position.longitude == 72.8
    assert snapshot.ocean is not None
    assert snapshot.weather is not None
    assert snapshot.status == "mock"
    assert snapshot.source_summary == {"ocean": "mock", "weather": "mock"}


def test_marine_conditions_service_partial_and_unavailable() -> None:
    """Test MarineConditionsService status detection for partial and unavailable feeds."""
    class NoneOceanAdapter(OceanAdapter):
        def get_conditions(self, latitude, longitude, timestamp=None):
            return None

    class NoneWeatherAdapter(WeatherAdapter):
        def get_conditions(self, latitude, longitude, timestamp=None):
            return None

    # Partial (weather only)
    partial_service = MarineConditionsService(
        ocean_service=OceanService(NoneOceanAdapter()),
        weather_service=WeatherService(MockWeatherAdapter()),
    )
    p_snap = partial_service.get_snapshot(latitude=18.5, longitude=72.8)
    assert p_snap.status == "partial"
    assert p_snap.ocean is None
    assert p_snap.weather is not None

    # Unavailable (both None)
    unavail_service = MarineConditionsService(
        ocean_service=OceanService(NoneOceanAdapter()),
        weather_service=WeatherService(NoneWeatherAdapter()),
    )
    u_snap = unavail_service.get_snapshot(latitude=18.5, longitude=72.8)
    assert u_snap.status == "unavailable"
    assert u_snap.ocean is None
    assert u_snap.weather is None


def test_marine_conditions_service_real_status_when_not_mock() -> None:
    """Test status is 'available' when non-mock data feeds are used."""
    class RealOceanAdapter(OceanAdapter):
        def get_conditions(self, latitude, longitude, timestamp=None):
            return OceanConditions(source="incois_hycom", current_speed_knots=1.1)

    class RealWeatherAdapter(WeatherAdapter):
        def get_conditions(self, latitude, longitude, timestamp=None):
            return WeatherConditions(source="imd_wrf", wind_speed_knots=12.0)

    service = MarineConditionsService(
        ocean_service=OceanService(RealOceanAdapter()),
        weather_service=WeatherService(RealWeatherAdapter()),
    )
    snap = service.get_snapshot(latitude=18.5, longitude=72.8)
    assert snap.status == "available"
    assert snap.source_summary == {"ocean": "incois_hycom", "weather": "imd_wrf"}


# ============================================================================
# 4. CONFIGURATION & FACTORY TESTS
# ============================================================================

def test_adapter_factories() -> None:
    """Test get_ocean_adapter and get_weather_adapter factories."""
    ocean_adapter = get_ocean_adapter()
    assert isinstance(ocean_adapter, MockOceanAdapter)

    weather_adapter = get_weather_adapter()
    assert isinstance(weather_adapter, MockWeatherAdapter)


# ============================================================================
# 5. API ENDPOINT TESTS
# ============================================================================

def test_api_get_marine_conditions(client: TestClient) -> None:
    """Test GET /marine/conditions returns 200 and valid snapshot payload."""
    response = client.get("/marine/conditions?latitude=18.52&longitude=72.85")
    assert response.status_code == 200

    data = response.json()
    assert data["position"]["latitude"] == 18.52
    assert data["position"]["longitude"] == 72.85
    assert data["status"] in ["mock", "available"]
    assert "ocean" in data
    assert "weather" in data
    assert data["ocean"]["source"] == "mock"
    assert data["weather"]["source"] == "mock"


def test_api_v1_get_marine_conditions(client: TestClient) -> None:
    """Test GET /api/v1/marine/conditions versioned endpoint returns 200."""
    response = client.get("/api/v1/marine/conditions?latitude=15.49&longitude=73.82")
    assert response.status_code == 200
    data = response.json()
    assert data["position"]["latitude"] == 15.49
    assert data["position"]["longitude"] == 73.82


def test_api_get_marine_conditions_invalid_coordinates(client: TestClient) -> None:
    """Test validation errors on out-of-range coordinates."""
    response = client.get("/marine/conditions?latitude=95.0&longitude=72.85")
    assert response.status_code == 422


# ============================================================================
# 6. ROUTE ENGINE INTEGRATION TESTS
# ============================================================================

def test_route_calculation_with_environmental_conditions(client: TestClient) -> None:
    """Verify Route calculation accepts optional environmental conditions context."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 14.5},
        "environmental_conditions": {
            "position": {"latitude": 18.9220, "longitude": 72.8347},
            "ocean": {
                "source": "mock",
                "current_speed_knots": 1.5,
                "current_direction_degrees": 180.0,
                "significant_wave_height_m": 1.2,
            },
            "weather": {
                "source": "mock",
                "wind_speed_knots": 12.0,
                "wind_direction_degrees": 270.0,
            },
            "status": "mock",
        },
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "marine_conditions" in data
    assert data["marine_conditions"] is not None
    assert data["marine_conditions"]["ocean"]["current_speed_knots"] == 1.5
    assert data["constraints"]["weather_check"] == "evaluated"
    assert data["constraints"]["safety_check"] == "pending"  # Safety Governor remains authority


def test_existing_route_calculation_without_conditions_unbroken(client: TestClient) -> None:
    """Ensure standard route calculation without environmental conditions remains 100% backward compatible."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 14.5},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "computed"
    assert data["constraints"]["weather_check"] == "pending"
    assert data["constraints"]["safety_check"] == "pending"
