"""Comprehensive unit and integration test suite for Objective-based Route Optimization Engine."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.dynamic_routing import (
    CandidateRoute,
    CandidateScoringBreakdown,
    DynamicRouteEvaluationSummary,
    ObjectiveWeights,
    RoutingObjective,
)
from app.models.marine_conditions import (
    MarineConditionsSnapshot,
    OceanConditions,
    WeatherConditions,
)
from app.models.pfz import PFZZone
from app.models.request import Coordinate, RouteRequest, Vessel
from app.models.response import RouteResponse
from app.repositories.pfz_repository import PFZRepository
from app.services.dynamic_route_service import DynamicRouteService
from app.services.pfz_service import PFZService
from app.services.route_optimization_service import (
    DEFAULT_OBJECTIVE_PROFILES,
    RouteOptimizationService,
)


@pytest.fixture
def client() -> TestClient:
    """Fixture providing FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def optimization_service() -> RouteOptimizationService:
    """Fixture providing RouteOptimizationService."""
    return RouteOptimizationService()


@pytest.fixture
def dynamic_service() -> DynamicRouteService:
    """Fixture providing DynamicRouteService."""
    return DynamicRouteService()


# ============================================================================
# 1. OBJECTIVE PROFILE & WEIGHTS VALIDATION
# ============================================================================

def test_supported_objectives_profiles(optimization_service: RouteOptimizationService) -> None:
    """Verify all 5 supported objectives have distinct, valid weighting profiles."""
    expected_objectives = [
        "safe_and_efficient",
        "nearest_destination",
        "fastest_arrival",
        "lowest_fuel",
        "highest_potential",
    ]
    for obj in expected_objectives:
        weights = optimization_service.get_objective_weights(obj)
        assert isinstance(weights, ObjectiveWeights)
        assert weights.distance_weight >= 0.0
        assert weights.eta_weight >= 0.0
        assert weights.ocean_weight >= 0.0
        assert weights.weather_weight >= 0.0
        assert weights.constraint_weight >= 0.0


def test_unsupported_objective_rejected() -> None:
    """Verify unsupported objectives raise clear validation error in RouteRequest."""
    with pytest.raises(ValidationError) as exc_info:
        RouteRequest(
            start=Coordinate(latitude=18.52, longitude=72.85),
            destination=Coordinate(latitude=18.65, longitude=72.90),
            vessel=Vessel(speed_knots=10.0),
            objective="warp_speed_objective",
        )
    assert "Unsupported routing objective" in str(exc_info.value)


def test_unsupported_objective_rejected_in_api(client: TestClient) -> None:
    """Verify POST /route returns 422 for unsupported objective."""
    payload = {
        "start": {"latitude": 18.52, "longitude": 72.85},
        "destination": {"latitude": 18.65, "longitude": 72.90},
        "vessel": {"speed_knots": 10.0},
        "objective": "unsupported_magic_route",
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 422
    assert "Unsupported routing objective" in response.text


# ============================================================================
# 2. OBJECTIVE-SPECIFIC SCORING PRIORITIES
# ============================================================================

def test_nearest_destination_prioritizes_distance(optimization_service: RouteOptimizationService) -> None:
    """Verify nearest_destination objective assigns highest weight to shortest distance."""
    w = optimization_service.get_objective_weights("nearest_destination")
    assert w.distance_weight > w.eta_weight
    assert w.distance_weight > w.ocean_weight
    assert w.distance_weight >= 0.60


def test_fastest_arrival_prioritizes_eta(optimization_service: RouteOptimizationService) -> None:
    """Verify fastest_arrival objective assigns highest weight to minimum ETA."""
    w = optimization_service.get_objective_weights("fastest_arrival")
    assert w.eta_weight > w.distance_weight
    assert w.eta_weight > w.ocean_weight
    assert w.eta_weight >= 0.60


def test_lowest_fuel_prioritizes_fuel_efficiency(optimization_service: RouteOptimizationService) -> None:
    """Verify lowest_fuel objective incorporates fuel consumption weight."""
    w = optimization_service.get_objective_weights("lowest_fuel")
    assert w.fuel_weight > 0.0
    assert w.fuel_weight >= 0.30


def test_highest_potential_prioritizes_pfz(optimization_service: RouteOptimizationService) -> None:
    """Verify highest_potential objective incorporates PFZ potential weight."""
    w = optimization_service.get_objective_weights("highest_potential")
    assert w.potential_weight > 0.0
    assert w.potential_weight >= 0.40


def test_safe_and_efficient_balanced_weights(optimization_service: RouteOptimizationService) -> None:
    """Verify safe_and_efficient objective balances distance, ETA, ocean, and weather."""
    w = optimization_service.get_objective_weights("safe_and_efficient")
    assert w.distance_weight > 0.0
    assert w.eta_weight > 0.0
    assert w.ocean_weight > 0.0
    assert w.weather_weight > 0.0
    assert w.constraint_weight > 0.0


# ============================================================================
# 3. MULTI-CANDIDATE OPTIMIZATION & SELECTION TESTS
# ============================================================================

def test_optimization_selects_best_candidate_safe_and_efficient(
    optimization_service: RouteOptimizationService,
) -> None:
    """Test optimization execution under safe_and_efficient profile."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)
    req = RouteRequest(
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
        objective="safe_and_efficient",
    )
    dyn_svc = DynamicRouteService()
    cands = dyn_svc.generate_candidates(start, dest, 10.0)

    selected, all_cands, summary = optimization_service.optimize_route(req, cands)

    assert selected is not None
    assert 0.0 <= selected.score <= 100.0
    assert len(all_cands) == 3
    assert summary.objective == "safe_and_efficient"
    assert summary.selected_candidate == selected.candidate_id
    assert "distance" in summary.scoring
    assert "eta" in summary.scoring


def test_optimization_lowest_fuel_with_vessel_fuel_params(
    optimization_service: RouteOptimizationService,
) -> None:
    """Test optimization with explicit vessel fuel consumption rate."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)
    req = RouteRequest(
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=12.0, fuel_rate_liters_per_hour=35.0),
        objective="lowest_fuel",
    )
    dyn_svc = DynamicRouteService()
    cands = dyn_svc.generate_candidates(start, dest, 12.0)

    selected, all_cands, summary = optimization_service.optimize_route(req, cands)

    assert selected.fuel_status == "available"
    assert summary.fuel_integration == "available"
    assert "fuel_score" in summary.scoring


def test_optimization_lowest_fuel_without_fuel_params_uses_estimation(
    optimization_service: RouteOptimizationService,
) -> None:
    """Test optimization without explicit vessel fuel parameters reports estimated fuel index."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)
    req = RouteRequest(
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
        objective="lowest_fuel",
    )
    dyn_svc = DynamicRouteService()
    cands = dyn_svc.generate_candidates(start, dest, 10.0)

    selected, all_cands, summary = optimization_service.optimize_route(req, cands)

    assert selected.fuel_status == "estimated"
    assert summary.fuel_integration == "estimated"


def test_optimization_highest_potential_with_pfz_zones(
    optimization_service: RouteOptimizationService,
) -> None:
    """Test highest_potential objective integrates with PFZ service and reports score."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)
    req = RouteRequest(
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
        objective="highest_potential",
    )
    dyn_svc = DynamicRouteService()
    cands = dyn_svc.generate_candidates(start, dest, 10.0)

    selected, all_cands, summary = optimization_service.optimize_route(req, cands)

    assert summary.objective == "highest_potential"
    assert summary.pfz_integration in ["available", "mock", "unavailable"]
    if selected.scoring_breakdown.potential_score is not None:
        assert 0.0 <= selected.scoring_breakdown.potential_score <= 100.0


def test_optimization_score_bounds_across_all_objectives(
    optimization_service: RouteOptimizationService,
) -> None:
    """Verify that every supported objective produces final scores bounded in [0.0, 100.0]."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)
    dyn_svc = DynamicRouteService()
    cands = dyn_svc.generate_candidates(start, dest, 10.0)

    for obj in [
        "safe_and_efficient",
        "nearest_destination",
        "fastest_arrival",
        "lowest_fuel",
        "highest_potential",
    ]:
        req = RouteRequest(
            start=start,
            destination=dest,
            vessel=Vessel(speed_knots=10.0),
            objective=obj,
        )
        selected, all_cands, summary = optimization_service.optimize_route(req, cands)
        assert 0.0 <= selected.score <= 100.0
        assert 0.0 <= summary.scoring["final_score"] <= 100.0


def test_deterministic_optimization_results(
    optimization_service: RouteOptimizationService,
) -> None:
    """Verify that multiple optimization runs with identical input produce exact deterministic scores."""
    start = Coordinate(latitude=18.5204, longitude=72.8567)
    dest = Coordinate(latitude=18.6500, longitude=72.9000)
    req = RouteRequest(
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
        objective="safe_and_efficient",
    )
    dyn_svc = DynamicRouteService()
    cands = dyn_svc.generate_candidates(start, dest, 10.0)

    run1_sel, _, run1_sum = optimization_service.optimize_route(req, cands)
    run2_sel, _, run2_sum = optimization_service.optimize_route(req, cands)

    assert run1_sel.candidate_id == run2_sel.candidate_id
    assert run1_sel.score == run2_sel.score
    assert run1_sum.scoring == run2_sum.scoring


# ============================================================================
# 4. FULL POST /route API INTEGRATION ACROSS ALL 5 OBJECTIVES
# ============================================================================

@pytest.mark.parametrize(
    "objective",
    [
        "safe_and_efficient",
        "nearest_destination",
        "fastest_arrival",
        "lowest_fuel",
        "highest_potential",
    ],
)
def test_api_post_route_for_all_objectives(client: TestClient, objective: str) -> None:
    """Verify POST /route returns 200 and valid RouteResponse for each supported objective."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
        "objective": objective,
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "computed"
    assert "route_id" in data
    assert "summary" in data
    assert 0.0 <= data["summary"]["route_score"] <= 100.0
    assert len(data["waypoints"]) >= 2
    assert "constraints" in data
    assert data["constraints"]["safety_check"] == "pending"
    assert "evaluation_metadata" in data
    assert data["evaluation_metadata"]["objective"] == objective


def test_api_post_route_preserves_marine_conditions_and_safety_governor_notice(
    client: TestClient,
) -> None:
    """Verify response includes marine_conditions snapshot and explicit safety disclaimer."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 10.0},
        "objective": "safe_and_efficient",
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["marine_conditions"] is not None
    assert "safety_governor_notice" in data["evaluation_metadata"]
    assert "Safety Governor" in data["evaluation_metadata"]["safety_governor_notice"]
