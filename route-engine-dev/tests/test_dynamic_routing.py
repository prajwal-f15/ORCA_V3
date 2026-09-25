"""Tests for Dynamic Marine Routing, multi-candidate generation, evaluation, and scoring."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.dynamic_routing import (
    CandidateRoute,
    CandidateScoringBreakdown,
    DynamicRouteEvaluationSummary,
)
from app.models.marine_conditions import (
    MarineConditionsSnapshot,
    OceanConditions,
    WeatherConditions,
)
from app.models.request import Coordinate, RouteRequest, Vessel
from app.models.response import RouteResponse, RouteSummary
from app.services.dynamic_route_service import DynamicRouteService
from app.services.marine_conditions_service import MarineConditionsService
from app.services.route_evaluation_service import RouteEvaluationService


@pytest.fixture
def client() -> TestClient:
    """Fixture providing FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def dynamic_service() -> DynamicRouteService:
    """Fixture providing DynamicRouteService instance."""
    return DynamicRouteService()


@pytest.fixture
def evaluation_service() -> RouteEvaluationService:
    """Fixture providing RouteEvaluationService instance."""
    return RouteEvaluationService()


# ============================================================================
# 1. CANDIDATE GENERATION TESTS
# ============================================================================

def test_candidate_generation_count_and_variants(dynamic_service: DynamicRouteService) -> None:
    """Verify that multiple deterministic candidate routes are generated."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)

    candidates = dynamic_service.generate_candidates(
        start=start,
        destination=dest,
        vessel_speed_knots=10.0,
        num_intermediate=3,
    )

    assert len(candidates) == 3
    variant_names = [c.variant_name for c in candidates]
    assert "direct_geodesic" in variant_names
    assert "starboard_offset" in variant_names
    assert "port_offset" in variant_names

    for c in candidates:
        assert len(c.waypoints) == 5
        assert c.waypoints[0].latitude == round(start.latitude, 6)
        assert c.waypoints[0].longitude == round(start.longitude, 6)
        assert c.waypoints[-1].latitude == round(dest.latitude, 6)
        assert c.waypoints[-1].longitude == round(dest.longitude, 6)
        assert c.distance_km > 0.0
        assert c.distance_nm > 0.0
        assert c.estimated_time_minutes > 0.0


def test_deterministic_candidate_generation(dynamic_service: DynamicRouteService) -> None:
    """Verify that candidate generation is 100% deterministic given identical inputs."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)

    run1 = dynamic_service.generate_candidates(start, dest, 12.0, num_intermediate=3)
    run2 = dynamic_service.generate_candidates(start, dest, 12.0, num_intermediate=3)

    for c1, c2 in zip(run1, run2):
        assert c1.variant_name == c2.variant_name
        assert c1.distance_km == c2.distance_km
        assert c1.distance_nm == c2.distance_nm
        assert c1.estimated_time_minutes == c2.estimated_time_minutes
        for wp1, wp2 in zip(c1.waypoints, c2.waypoints):
            assert wp1.latitude == wp2.latitude
            assert wp1.longitude == wp2.longitude


def test_zero_distance_candidate_generation(dynamic_service: DynamicRouteService) -> None:
    """Verify that identical origin and destination produces a single zero-distance candidate."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    candidates = dynamic_service.generate_candidates(start, start, 10.0)

    assert len(candidates) == 1
    assert candidates[0].distance_km == 0.0
    assert candidates[0].distance_nm == 0.0
    assert candidates[0].estimated_time_minutes == 0.0


# ============================================================================
# 2. ROUTE EVALUATION & SCORING TESTS
# ============================================================================

def test_route_scoring_bounds(evaluation_service: RouteEvaluationService) -> None:
    """Verify that evaluated route scores strictly lie within [0.0, 100.0]."""
    wps = [
        Coordinate(latitude=18.5204, longitude=72.8567),
        Coordinate(latitude=18.6500, longitude=72.9000),
    ]
    cand = CandidateRoute(
        candidate_id="cand-1",
        variant_name="direct_geodesic",
        waypoints=wps,
        distance_km=20.0,
        distance_nm=10.8,
        estimated_time_minutes=60.0,
    )
    vessel = Vessel(speed_knots=10.8)

    evaluated = evaluation_service.evaluate_candidate(
        candidate=cand,
        vessel=vessel,
        objective="safe_and_efficient",
        marine_conditions=None,
    )

    assert 0.0 <= evaluated.score <= 100.0
    assert evaluated.scoring_breakdown is not None
    assert 0.0 <= evaluated.scoring_breakdown.final_score <= 100.0


def test_ocean_penalty_increases_with_rough_sea(evaluation_service: RouteEvaluationService) -> None:
    """Verify ocean penalty increases when significant wave height and currents are harsh."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    cand = CandidateRoute(
        candidate_id="c-direct",
        variant_name="direct_geodesic",
        waypoints=wps,
        distance_km=15.0,
        distance_nm=8.1,
        estimated_time_minutes=45.0,
    )
    vessel = Vessel(speed_knots=10.0)

    # Calm sea
    calm_snapshot = MarineConditionsSnapshot(
        position=Coordinate(latitude=18.5, longitude=72.8),
        ocean=OceanConditions(significant_wave_height_m=0.8, current_speed_knots=0.5),
        weather=WeatherConditions(wind_speed_knots=5.0),
    )
    res_calm = evaluation_service.evaluate_candidate(cand, vessel, marine_conditions=calm_snapshot)

    # Rough sea (4.5m waves, 3.0 kt current)
    rough_snapshot = MarineConditionsSnapshot(
        position=Coordinate(latitude=18.5, longitude=72.8),
        ocean=OceanConditions(significant_wave_height_m=4.5, current_speed_knots=3.0),
        weather=WeatherConditions(wind_speed_knots=5.0),
    )
    res_rough = evaluation_service.evaluate_candidate(cand, vessel, marine_conditions=rough_snapshot)

    assert res_rough.scoring_breakdown.ocean_penalty > res_calm.scoring_breakdown.ocean_penalty
    assert res_rough.score < res_calm.score


def test_weather_penalty_increases_with_high_wind_and_poor_visibility(
    evaluation_service: RouteEvaluationService,
) -> None:
    """Verify weather penalty increases with gale-force winds and low visibility."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    cand = CandidateRoute(
        candidate_id="c-direct",
        variant_name="direct_geodesic",
        waypoints=wps,
        distance_km=15.0,
        distance_nm=8.1,
        estimated_time_minutes=45.0,
    )
    vessel = Vessel(speed_knots=10.0)

    # Mild weather
    mild_snap = MarineConditionsSnapshot(
        position=Coordinate(latitude=18.5, longitude=72.8),
        ocean=OceanConditions(significant_wave_height_m=1.0),
        weather=WeatherConditions(wind_speed_knots=8.0, visibility_km=10.0),
    )
    res_mild = evaluation_service.evaluate_candidate(cand, vessel, marine_conditions=mild_snap)

    # Severe storm (35kt wind, 0.5km visibility fog, 32kt gusts)
    storm_snap = MarineConditionsSnapshot(
        position=Coordinate(latitude=18.5, longitude=72.8),
        ocean=OceanConditions(significant_wave_height_m=1.0),
        weather=WeatherConditions(wind_speed_knots=35.0, wind_gust_knots=42.0, visibility_km=0.5),
    )
    res_storm = evaluation_service.evaluate_candidate(cand, vessel, marine_conditions=storm_snap)

    assert res_storm.scoring_breakdown.weather_penalty > res_mild.scoring_breakdown.weather_penalty
    assert res_storm.score < res_mild.score


def test_missing_ocean_and_weather_data_not_assumed_safe(
    evaluation_service: RouteEvaluationService,
) -> None:
    """Verify missing environmental data incurs explicit unverified penalty rather than assumed safe."""
    wps = [Coordinate(latitude=18.5, longitude=72.8), Coordinate(latitude=18.6, longitude=72.9)]
    cand = CandidateRoute(
        candidate_id="c-direct",
        variant_name="direct_geodesic",
        waypoints=wps,
        distance_km=15.0,
        distance_nm=8.1,
        estimated_time_minutes=45.0,
    )
    vessel = Vessel(speed_knots=10.0)

    # Completely missing environmental snapshot
    res = evaluation_service.evaluate_candidate(cand, vessel, marine_conditions=None)

    assert res.ocean_status == "unavailable"
    assert res.weather_status == "unavailable"
    assert res.scoring_breakdown.ocean_penalty > 0.0
    assert res.scoring_breakdown.weather_penalty > 0.0


# ============================================================================
# 3. BEST CANDIDATE SELECTION TESTS
# ============================================================================

def test_best_candidate_selection_highest_score(dynamic_service: DynamicRouteService) -> None:
    """Verify candidate with highest score is selected."""
    c1 = CandidateRoute(
        candidate_id="c1",
        variant_name="direct_geodesic",
        waypoints=[],
        distance_km=20.0,
        distance_nm=10.8,
        estimated_time_minutes=60.0,
        score=75.0,
    )
    c2 = CandidateRoute(
        candidate_id="c2",
        variant_name="starboard_offset",
        waypoints=[],
        distance_km=22.0,
        distance_nm=11.9,
        estimated_time_minutes=66.0,
        score=88.5,
    )
    c3 = CandidateRoute(
        candidate_id="c3",
        variant_name="port_offset",
        waypoints=[],
        distance_km=21.0,
        distance_nm=11.3,
        estimated_time_minutes=63.0,
        score=82.0,
    )

    best = dynamic_service.select_best_candidate([c1, c2, c3])
    assert best.candidate_id == "c2"
    assert best.score == 88.5


def test_best_candidate_tie_breaking(dynamic_service: DynamicRouteService) -> None:
    """Verify ties in score break in favor of the shorter distance candidate."""
    c1 = CandidateRoute(
        candidate_id="c1_short",
        variant_name="direct_geodesic",
        waypoints=[],
        distance_km=20.0,
        distance_nm=10.8,
        estimated_time_minutes=60.0,
        score=90.0,
    )
    c2 = CandidateRoute(
        candidate_id="c2_long",
        variant_name="starboard_offset",
        waypoints=[],
        distance_km=25.0,
        distance_nm=13.5,
        estimated_time_minutes=75.0,
        score=90.0,
    )

    best = dynamic_service.select_best_candidate([c2, c1])
    assert best.candidate_id == "c1_short"


# ============================================================================
# 4. API & POST /route INTEGRATION TESTS
# ============================================================================

def test_api_post_route_dynamic_response(client: TestClient) -> None:
    """Verify POST /route returns populated RouteResponse with dynamic scoring and evaluation metadata."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
        "objective": "safe_and_efficient",
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "computed"
    assert "route_id" in data
    assert "summary" in data
    assert 0.0 <= data["summary"]["route_score"] <= 100.0
    assert len(data["waypoints"]) >= 2
    assert "marine_conditions" in data
    assert "evaluation_metadata" in data

    meta = data["evaluation_metadata"]
    assert meta["candidate_count"] >= 3
    assert "selected_candidate" in meta
    assert "selected_variant" in meta
    assert "scoring" in meta
    assert "final_score" in meta["scoring"]
    assert "safety_governor_notice" in meta


def test_api_post_route_preserves_custom_environmental_conditions(client: TestClient) -> None:
    """Verify POST /route evaluates provided environmental conditions."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
        "environmental_conditions": {
            "position": {"latitude": 18.5204, "longitude": 72.8567},
            "ocean": {
                "source": "mock",
                "current_speed_knots": 1.2,
                "significant_wave_height_m": 1.5,
            },
            "weather": {
                "source": "mock",
                "wind_speed_knots": 10.0,
            },
            "status": "mock",
        },
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["marine_conditions"]["ocean"]["current_speed_knots"] == 1.2
    assert data["constraints"]["safety_check"] == "pending"
