"""End-to-End Validation Suite for ORCA V3 Route Engine & Safety Governor Integration.

Validates complete architectural pipeline:
ORCA Brain -> Route Request -> Candidate Generation -> Marine/Weather Conditions ->
Route Optimization -> Selected Route -> Safety Governor Audit -> Final Decision (ALLOW/WARN/REJECT/DEGRADED)
"""

from datetime import datetime, timezone
from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient
import httpx

from app.core.config import Settings, get_settings
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
from app.models.response import RouteResponse
from app.models.safety import CheckStatus, SafetyCheckResult, SafetyDecision
from app.repositories.geography_repository import get_default_geography_repository
from app.services.dynamic_route_service import DynamicRouteService
from app.services.safety_governor_service import SafetyGovernorService
from brain_integration.route_engine_tool import call_route_engine_api


_route_engine_test_client = TestClient(app)


class LocalhostASGITransport(httpx.BaseTransport):
    """Transport that routes localhost:8000 requests in-process to the ASGI app."""

    def __init__(self) -> None:
        self.http_transport = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host in ("127.0.0.1", "localhost", "testserver") and (
            request.url.port in (8000, None)
        ):
            return _route_engine_test_client._transport.handle_request(request)
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
    return _route_engine_test_client


# ============================================================================
# 1. END-TO-END SCENARIO A — NORMAL ROUTE COMPUTATION & SAFETY AUDIT
# ============================================================================

def test_e2e_scenario_a_normal_route(client: TestClient) -> None:
    """Validate full end-to-end flow from request to candidate evaluation and safety audit."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {
            "speed_knots": 10.0,
            "draft_meters": 2.0,
            "vessel_type": "fishing_trawler",
        },
        "objective": "safe_and_efficient",
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()

    # 1. Route Engine core outputs
    assert "route_id" in data
    assert data["status"] == "computed"
    assert "summary" in data
    assert data["summary"]["distance_km"] > 0.0
    assert data["summary"]["distance_nm"] > 0.0
    assert data["summary"]["estimated_time_minutes"] > 0.0
    assert 0.0 <= data["summary"]["route_score"] <= 100.0

    # 2. Waypoints sequence
    assert "waypoints" in data
    assert len(data["waypoints"]) >= 2
    assert data["waypoints"][0]["latitude"] == 18.5204
    assert data["waypoints"][-1]["latitude"] == 18.6500

    # 3. Marine conditions (mock testing feed)
    assert "marine_conditions" in data
    assert data["marine_conditions"] is not None
    assert data["marine_conditions"]["ocean"]["source"] == "mock"
    assert data["marine_conditions"]["weather"]["source"] == "mock"

    # 4. Route Optimization Evaluation Metadata
    assert "evaluation_metadata" in data
    eval_meta = data["evaluation_metadata"]
    assert eval_meta["objective"] == "safe_and_efficient"
    assert eval_meta["candidate_count"] >= 3
    assert "selected_candidate" in eval_meta

    # 5. Safety Governor Final Authority
    assert "safety_decision" in data
    assert data["safety_decision"] in ["ALLOW", "WARN", "REJECT", "DEGRADED"]
    assert "safety_evaluation" in data
    safety_eval = data["safety_evaluation"]
    assert "checks" in safety_eval
    assert "warnings" in safety_eval
    assert "blocking_reasons" in safety_eval
    assert "data_status" in safety_eval

    # Mock testing data must be transparently surfaced as WARN
    assert data["safety_decision"] == "WARN"
    assert safety_eval["checks"]["data_quality"] == CheckStatus.WARNING.value
    assert any("mock" in w for w in safety_eval["warnings"])


# ============================================================================
# 2. END-TO-END SCENARIO B — WEATHER WARNING
# ============================================================================

def test_e2e_scenario_b_weather_warning(client: TestClient) -> None:
    """Validate that operational weather warnings produce a WARN safety verdict while computing the route."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.0, "draft_meters": 2.0},
        "objective": "safe_and_efficient",
        "environmental_conditions": {
            "source": "marine_weather_service",
            "significant_wave_height_m": 1.5,
            "current_speed_knots": 1.0,
            "wind_speed_knots": 28.0,  # Advisory threshold (>= 25.0 knots)
            "visibility_km": 10.0,
        },
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "computed"
    assert data["safety_decision"] == "WARN"

    safety_eval = data["safety_evaluation"]
    assert safety_eval["checks"]["weather"] == CheckStatus.WARNING.value
    assert any("wind" in w.lower() for w in safety_eval["warnings"])
    assert len(safety_eval["blocking_reasons"]) == 0


# ============================================================================
# 3. END-TO-END SCENARIO C — BLOCKING SAFETY CONDITION (REJECT)
# ============================================================================

def test_e2e_scenario_c_blocking_restricted_area(client: TestClient) -> None:
    """Validate that intersecting a restricted marine polygon triggers an authoritative REJECT."""
    repo = get_default_geography_repository()
    test_feature = GeoFeature(
        feature_id="restricted-e2e-naval-zone",
        feature_type=GeoFeatureType.RESTRICTED_AREA,
        name="Naval Restricted Area Bravo",
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
        payload = {
            "start": {"latitude": 18.40, "longitude": 72.85},
            "destination": {"latitude": 18.80, "longitude": 72.85},
            "vessel": {"speed_knots": 10.0, "draft_meters": 2.0},
            "objective": "safe_and_efficient",
        }
        response = client.post("/route", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["safety_decision"] == "REJECT"
        safety_eval = data["safety_evaluation"]
        assert safety_eval["checks"]["restricted_area"] == CheckStatus.BLOCK.value
        assert any("restricted" in br.lower() for br in safety_eval["blocking_reasons"])
    finally:
        repo.delete_feature("restricted-e2e-naval-zone")


def test_e2e_scenario_c_blocking_severe_environmental_conditions(client: TestClient) -> None:
    """Validate that extreme wave height (>= 4.0m) or wind speed (>= 35 knots) triggers REJECT."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.0},
        "environmental_conditions": {
            "significant_wave_height_m": 5.2,  # Exceeds critical block threshold (4.0m)
            "wind_speed_knots": 42.0,  # Exceeds critical block threshold (35.0 kts)
        },
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["safety_decision"] == "REJECT"
    safety_eval = data["safety_evaluation"]
    assert safety_eval["checks"]["ocean"] == CheckStatus.BLOCK.value
    assert safety_eval["checks"]["weather"] == CheckStatus.BLOCK.value
    assert len(safety_eval["blocking_reasons"]) >= 1


# ============================================================================
# 4. END-TO-END SCENARIO D — CRITICAL DATA MISSING (DEGRADED)
# ============================================================================

def test_e2e_scenario_d_missing_critical_marine_data() -> None:
    """Validate that missing critical environmental/ocean data results in a DEGRADED verdict."""
    safety_gov = SafetyGovernorService()
    wps = [
        Coordinate(latitude=18.5204, longitude=72.8567),
        Coordinate(latitude=18.6500, longitude=72.9000),
    ]
    vessel = Vessel(speed_knots=10.0)

    # No marine conditions snapshot provided (unverified/missing feeds)
    result = safety_gov.evaluate_route(waypoints=wps, vessel=vessel, marine_conditions=None)

    assert result.decision == SafetyDecision.DEGRADED
    assert result.checks["ocean"] == CheckStatus.UNAVAILABLE.value
    assert result.checks["weather"] == CheckStatus.UNAVAILABLE.value
    assert result.data_status["ocean"] == "unavailable"
    assert result.data_status["weather"] == "unavailable"


# ============================================================================
# 5. HIGH ROUTE SCORE CANNOT OVERRIDE SAFETY REJECT (RULE 1 & RULE 3)
# ============================================================================

def test_e2e_high_route_score_99_cannot_override_reject() -> None:
    """Validate that a near-perfect route score (99.5) is overridden by Safety Governor REJECT."""
    safety_gov = SafetyGovernorService()
    wps = [
        Coordinate(latitude=18.5204, longitude=72.8567),
        Coordinate(latitude=18.6500, longitude=72.9000),
    ]
    vessel = Vessel(speed_knots=12.0)
    # Severe hurricane weather snapshot
    marine = MarineConditionsSnapshot(
        position=wps[0],
        ocean=OceanConditions(significant_wave_height_m=5.5),
        weather=WeatherConditions(wind_speed_knots=45.0, visibility_km=0.2),
    )

    result = safety_gov.evaluate_route(
        waypoints=wps,
        vessel=vessel,
        marine_conditions=marine,
        route_score=99.5,
    )

    assert result.decision == SafetyDecision.REJECT
    assert len(result.blocking_reasons) > 0
    assert result.decision != SafetyDecision.ALLOW


# ============================================================================
# 6. BRAIN -> ROUTE ENGINE -> SAFETY GOVERNOR INTEGRATION
# ============================================================================

def test_e2e_brain_to_route_engine_to_safety_governor(client: TestClient) -> None:
    """Validate POST /test/route-engine invokes Route Engine and returns Safety Governor evaluation."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
        "objective": "safe_and_efficient",
    }
    response = client.post("/test/route-engine", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "route_id" in data
    assert "summary" in data
    assert "waypoints" in data
    assert "evaluation_metadata" in data
    assert "safety_decision" in data
    assert "safety_evaluation" in data
    assert data["safety_decision"] in ["ALLOW", "WARN", "REJECT", "DEGRADED"]
    assert "blocking_reasons" in data["safety_evaluation"]


# ============================================================================
# 7. API ENDPOINT VALIDATION (ROOT & V1)
# ============================================================================

def test_e2e_all_required_api_endpoints(client: TestClient) -> None:
    """Validate existence and successful response of all required API endpoints."""
    # 1. GET /health
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    # 2. GET /docs
    r_docs = client.get("/docs")
    assert r_docs.status_code == 200

    # 3. POST /route & POST /api/v1/route
    route_payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
    }
    r_route = client.post("/route", json=route_payload)
    assert r_route.status_code == 200

    r_route_v1 = client.post("/api/v1/route", json=route_payload)
    assert r_route_v1.status_code == 200

    # 4. POST /safety/evaluate & POST /api/v1/safety/evaluate
    safety_payload = {
        "waypoints": [
            {"latitude": 18.5204, "longitude": 72.8567},
            {"latitude": 18.6500, "longitude": 72.9000},
        ],
        "vessel": {"speed_knots": 10.0},
    }
    r_safety = client.post("/safety/evaluate", json=safety_payload)
    assert r_safety.status_code == 200
    assert "decision" in r_safety.json()

    r_safety_v1 = client.post("/api/v1/safety/evaluate", json=safety_payload)
    assert r_safety_v1.status_code == 200
    assert "decision" in r_safety_v1.json()

    # 5. POST /test/route-engine & POST /api/v1/test/route-engine
    r_brain = client.post("/test/route-engine", json=route_payload)
    assert r_brain.status_code == 200

    r_brain_v1 = client.post("/api/v1/test/route-engine", json=route_payload)
    assert r_brain_v1.status_code == 200


# ============================================================================
# 8. RESPONSE CONTRACT VALIDATION & BACKWARD COMPATIBILITY
# ============================================================================

def test_e2e_response_contract_backward_compatibility(client: TestClient) -> None:
    """Validate that POST /route response conforms strictly to RouteResponse Pydantic schema."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    # Validate against Pydantic model directly
    data = response.json()
    validated_model = RouteResponse.model_validate(data)

    # Check presence of required legacy fields
    assert validated_model.route_id is not None
    assert validated_model.status == "computed"
    assert validated_model.summary.distance_km > 0.0
    assert validated_model.constraints.safety_check == "pending"
    assert validated_model.evaluation_metadata is not None

    # Check presence of new safety governor fields
    assert validated_model.safety_decision is not None
    assert validated_model.safety_evaluation is not None
    assert "decision" in validated_model.safety_evaluation


# ============================================================================
# 9. MOCK DATA TRANSPARENCY
# ============================================================================

def test_e2e_mock_data_transparency(client: TestClient) -> None:
    """Validate that environmental mock feeds are explicitly identified and never certified as real."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["marine_conditions"]["ocean"]["source"] == "mock"
    assert data["marine_conditions"]["weather"]["source"] == "mock"
    assert data["safety_evaluation"]["data_status"]["ocean"] == "mock"
    assert data["safety_evaluation"]["data_status"]["weather"] == "mock"
    assert any("mock/testing" in w for w in data["safety_evaluation"]["warnings"])
