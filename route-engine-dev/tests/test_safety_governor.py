"""Comprehensive unit and integration test suite for Safety Governor and Navigation Clearance."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.models.geography import (
    GeoFeature,
    GeoFeatureType,
    GeoGeometry,
    GeometryType,
)
from app.models.marine_conditions import (
    MarineConditionsSnapshot,
    OceanConditions,
    WeatherConditions,
)
from app.models.request import Coordinate, RouteRequest, Vessel
from app.models.safety import (
    CheckStatus,
    SafetyCheckResult,
    SafetyDecision,
    SafetyEvaluationRequest,
)
from app.repositories.geography_repository import get_default_geography_repository
from app.services.marine_constraint_service import MarineConstraintService
from app.services.safety_governor_service import SafetyGovernorService


@pytest.fixture
def client() -> TestClient:
    """Fixture providing FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def custom_settings() -> Settings:
    """Fixture providing explicit test thresholds."""
    return Settings(
        MAX_TEST_WAVE_HEIGHT_BLOCK_M=4.0,
        MAX_TEST_WAVE_HEIGHT_WARN_M=2.5,
        MAX_TEST_WIND_SPEED_BLOCK_KNOTS=35.0,
        MAX_TEST_WIND_SPEED_WARN_KNOTS=25.0,
        MIN_TEST_VISIBILITY_BLOCK_KM=0.5,
        MIN_TEST_VISIBILITY_WARN_KM=3.0,
        MIN_TEST_UKC_METERS=0.5,
    )


@pytest.fixture
def safety_service(custom_settings: Settings) -> SafetyGovernorService:
    """Fixture providing SafetyGovernorService with custom test settings."""
    return SafetyGovernorService(settings=custom_settings)


# ============================================================================
# 1. SAFETY DECISION STATUS TESTS (ALLOW, WARN, REJECT, DEGRADED)
# ============================================================================

def test_safety_governor_allow_when_clean_and_verified(custom_settings: Settings) -> None:
    """Verify ALLOW verdict when all checks pass with verified real-time data."""
    wps = [
        Coordinate(latitude=18.5204, longitude=72.8567),
        Coordinate(latitude=18.6500, longitude=72.9000),
    ]
    vessel = Vessel(speed_knots=10.0, draft_meters=2.0)
    snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="incois_hycom", significant_wave_height_m=1.2, current_speed_knots=1.0),
        weather=WeatherConditions(source="imd_wrf", wind_speed_knots=12.0, visibility_km=10.0),
    )
    svc = SafetyGovernorService(settings=custom_settings)
    result = svc.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=snapshot)

    assert result.decision == SafetyDecision.ALLOW
    assert len(result.blocking_reasons) == 0
    assert result.checks["restricted_area"] == CheckStatus.PASS.value
    assert result.checks["ocean"] == CheckStatus.PASS.value
    assert result.checks["weather"] == CheckStatus.PASS.value


def test_safety_governor_warn_on_mock_testing_data(safety_service: SafetyGovernorService) -> None:
    """Verify WARN verdict is assigned when environmental data is mock/testing feed."""
    wps = [
        Coordinate(latitude=18.5204, longitude=72.8567),
        Coordinate(latitude=18.6500, longitude=72.9000),
    ]
    vessel = Vessel(speed_knots=10.0, draft_meters=2.0)
    snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="mock", significant_wave_height_m=1.0),
        weather=WeatherConditions(source="mock", wind_speed_knots=10.0, visibility_km=10.0),
    )
    result = safety_service.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=snapshot)

    assert result.decision == SafetyDecision.WARN
    assert result.checks["data_quality"] == CheckStatus.WARNING.value
    assert any("mock" in w for w in result.warnings)


def test_safety_governor_reject_on_critical_wave_height(safety_service: SafetyGovernorService) -> None:
    """Verify REJECT verdict when significant wave height exceeds critical threshold."""
    wps = [
        Coordinate(latitude=18.5204, longitude=72.8567),
        Coordinate(latitude=18.6500, longitude=72.9000),
    ]
    vessel = Vessel(speed_knots=10.0)
    # 4.5m wave height > 4.0m limit
    snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="incois_hycom", significant_wave_height_m=4.5),
        weather=WeatherConditions(source="imd_wrf", wind_speed_knots=12.0),
    )
    result = safety_service.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=snapshot)

    assert result.decision == SafetyDecision.REJECT
    assert result.checks["ocean"] == CheckStatus.BLOCK.value
    assert any("wave height" in br.lower() for br in result.blocking_reasons)


def test_safety_governor_reject_on_critical_wind_speed(safety_service: SafetyGovernorService) -> None:
    """Verify REJECT verdict when sustained wind speed exceeds critical limit."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    vessel = Vessel(speed_knots=10.0)
    # 40 kt wind > 35 kt limit
    snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="incois_hycom", significant_wave_height_m=1.0),
        weather=WeatherConditions(source="imd_wrf", wind_speed_knots=40.0),
    )
    result = safety_service.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=snapshot)

    assert result.decision == SafetyDecision.REJECT
    assert result.checks["weather"] == CheckStatus.BLOCK.value
    assert any("wind speed" in br.lower() for br in result.blocking_reasons)


def test_safety_governor_reject_on_critical_low_visibility(safety_service: SafetyGovernorService) -> None:
    """Verify REJECT verdict when horizontal visibility drops below critical limit (dense fog)."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    vessel = Vessel(speed_knots=10.0)
    # 0.2 km visibility < 0.5 km limit
    snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="incois_hycom", significant_wave_height_m=1.0),
        weather=WeatherConditions(source="imd_wrf", wind_speed_knots=10.0, visibility_km=0.2),
    )
    result = safety_service.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=snapshot)

    assert result.decision == SafetyDecision.REJECT
    assert result.checks["weather"] == CheckStatus.BLOCK.value
    assert any("visibility" in br.lower() for br in result.blocking_reasons)


def test_safety_governor_degraded_when_critical_data_missing(safety_service: SafetyGovernorService) -> None:
    """Verify DEGRADED verdict when critical ocean/weather feeds are unavailable."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    vessel = Vessel(speed_knots=10.0)
    # No marine conditions snapshot provided
    result = safety_service.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=None)

    assert result.decision == SafetyDecision.DEGRADED
    assert result.checks["ocean"] == CheckStatus.UNAVAILABLE.value
    assert result.checks["weather"] == CheckStatus.UNAVAILABLE.value


# ============================================================================
# 2. RESTRICTED AREA & BATHYMETRY DEPTH CHECKS
# ============================================================================

def test_safety_governor_reject_on_restricted_area_intersection(
    safety_service: SafetyGovernorService,
) -> None:
    """Verify route intersecting a confirmed restricted zone produces REJECT verdict."""
    repo = get_default_geography_repository()
    # Register a restricted test polygon
    test_feature = GeoFeature(
        feature_id="restricted-test-zone-1",
        feature_type=GeoFeatureType.RESTRICTED_AREA,
        name="Naval Artillery Test Range Alpha",
        restriction_type="prohibited",
        geometry=GeoGeometry(
            type=GeometryType.POLYGON,
            coordinates=[
                [
                    [72.80, 18.50],
                    [72.95, 18.50],
                    [72.95, 18.70],
                    [72.80, 18.70],
                    [72.80, 18.50],
                ]
            ],
        ),
    )
    repo.add_feature(test_feature)

    try:
        wps = [
            Coordinate(latitude=18.40, longitude=72.85),
            Coordinate(latitude=18.60, longitude=72.85),  # Inside zone
            Coordinate(latitude=18.80, longitude=72.85),
        ]
        vessel = Vessel(speed_knots=10.0)
        result = safety_service.evaluate_route(waypoints=wps, vessel=vessel)

        assert result.decision == SafetyDecision.REJECT
        assert result.checks["restricted_area"] == CheckStatus.BLOCK.value
        assert any("restricted" in br.lower() for br in result.blocking_reasons)
    finally:
        repo.delete_feature("restricted-test-zone-1")


# ============================================================================
# 3. STRICT DECISION PRECEDENCE & ROUTE SCORE NON-OVERRIDE
# ============================================================================

def test_route_score_99_cannot_override_safety_reject(
    safety_service: SafetyGovernorService,
) -> None:
    """Verify an optimal route with 99.5 score is still REJECTED if a blocking condition exists."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    vessel = Vessel(speed_knots=10.0)
    # Severe weather blocking condition
    snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="incois_hycom", significant_wave_height_m=1.0),
        weather=WeatherConditions(source="imd_wrf", wind_speed_knots=45.0),  # > 35 kt
    )

    result = safety_service.evaluate_route(
        waypoints=wps,
        vessel=vessel,
        marine_conditions=snapshot,
        route_score=99.5,  # High route score!
    )

    # Route score MUST NOT override the Safety Governor
    assert result.decision == SafetyDecision.REJECT
    assert len(result.blocking_reasons) > 0


def test_reject_takes_precedence_over_warnings_and_degraded(
    safety_service: SafetyGovernorService,
) -> None:
    """Verify REJECT is chosen when both blocking and warning conditions exist."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    vessel = Vessel(speed_knots=10.0)
    # Severe wind (BLOCK) + wave advisory (WARN) + mock data (WARN)
    snapshot = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(source="mock", significant_wave_height_m=2.8),  # WARN
        weather=WeatherConditions(source="mock", wind_speed_knots=40.0),  # BLOCK
    )

    result = safety_service.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=snapshot)

    assert result.decision == SafetyDecision.REJECT


# ============================================================================
# 4. API ENDPOINTS & ROUTE ENGINE INTEGRATION
# ============================================================================

def test_api_post_safety_evaluate(client: TestClient) -> None:
    """Test dedicated POST /safety/evaluate endpoint."""
    payload = {
        "waypoints": [
            {"latitude": 18.5204, "longitude": 72.8567},
            {"latitude": 18.6500, "longitude": 72.9000},
        ],
        "vessel": {"speed_knots": 10.0, "draft_meters": 2.0},
        "marine_conditions": {
            "position": {"latitude": 18.5204, "longitude": 72.8567},
            "ocean": {"source": "incois_hycom", "significant_wave_height_m": 1.5},
            "weather": {"source": "imd_wrf", "wind_speed_knots": 15.0, "visibility_km": 10.0},
            "status": "available",
        },
        "route_score": 95.0,
    }
    response = client.post("/safety/evaluate", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["decision"] in ["ALLOW", "WARN", "REJECT", "DEGRADED"]
    assert "checks" in data
    assert "warnings" in data
    assert "blocking_reasons" in data
    assert "data_status" in data


def test_api_v1_post_safety_evaluate(client: TestClient) -> None:
    """Test versioned POST /api/v1/safety/evaluate endpoint."""
    payload = {
        "waypoints": [
            {"latitude": 15.49, "longitude": 73.82},
            {"latitude": 15.60, "longitude": 73.90},
        ],
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/api/v1/safety/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "decision" in data


def test_api_post_route_includes_safety_decision_and_evaluation(client: TestClient) -> None:
    """Verify standard POST /route returns safety_decision and safety_evaluation payload."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
        "objective": "safe_and_efficient",
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "safety_decision" in data
    assert data["safety_decision"] in ["ALLOW", "WARN", "REJECT", "DEGRADED"]
    assert "safety_evaluation" in data
    assert "blocking_reasons" in data["safety_evaluation"]
    assert data["constraints"]["safety_check"] == "pending"
