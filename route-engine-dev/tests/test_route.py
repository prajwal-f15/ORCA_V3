"""Unit tests for Route API contract, distance/ETA integration, and validation."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.request import Coordinate, RouteRequest, Vessel
from app.models.response import RouteConstraints, RouteResponse, RouteSummary
from app.routing.provider import DefaultRouteProvider
from app.services.route_service import RouteService


@pytest.fixture
def client() -> TestClient:
    """Fixture to provide FastAPI TestClient."""
    return TestClient(app)


def test_valid_route_request(client: TestClient) -> None:
    """Test POST /route returns 200 with real distance, ETA, and pending constraints."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 14.5},
        "objective": "safe_and_efficient",
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "route_id" in data
    assert data["status"] == "computed"
    assert "summary" in data
    assert "waypoints" in data
    assert len(data["waypoints"]) == 5
    assert data["waypoints"][0]["latitude"] == 18.9220
    assert data["waypoints"][0]["longitude"] == 72.8347
    assert data["waypoints"][-1]["latitude"] == 15.4909
    assert data["waypoints"][-1]["longitude"] == 73.8278
    assert "constraints" in data

    # Verify real calculated metrics for Mumbai -> Goa (~394 km, ~213 nm)
    assert data["summary"]["distance_km"] > 380.0
    assert data["summary"]["distance_nm"] > 200.0
    assert data["summary"]["estimated_time_minutes"] > 800.0
    assert 0.0 <= data["summary"]["route_score"] <= 100.0

    # Verify constraints status set to pending for safety governor
    assert data["constraints"]["safety_check"] == "pending"
    assert data["constraints"]["weather_check"] in ["evaluated", "mock", "pending"]
    assert data["constraints"]["restricted_area_check"] in ["cleared", "warning", "pending"]


def test_valid_route_request_default_objective(client: TestClient) -> None:
    """Test POST /route uses default objective 'safe_and_efficient' when omitted."""
    payload = {
        "start": {"latitude": 12.9716, "longitude": 77.5946},
        "destination": {"latitude": 13.0827, "longitude": 80.2707},
        "vessel": {"speed_knots": 10.0},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "computed"
    assert data["summary"]["distance_km"] > 0.0


def test_zero_distance_route(client: TestClient) -> None:
    """Test that identical start and destination produce zero distance and zero ETA."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 18.9220, "longitude": 72.8347},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["distance_km"] == 0.0
    assert data["summary"]["distance_nm"] == 0.0
    assert data["summary"]["estimated_time_minutes"] == 0.0


def test_invalid_latitude_above_range(client: TestClient) -> None:
    """Test validation fails when latitude is > 90."""
    payload = {
        "start": {"latitude": 95.0, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 422


def test_invalid_latitude_below_range(client: TestClient) -> None:
    """Test validation fails when latitude is < -90."""
    payload = {
        "start": {"latitude": -91.5, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 422


def test_invalid_longitude_above_range(client: TestClient) -> None:
    """Test validation fails when longitude is > 180."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": 185.0},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 422


def test_invalid_longitude_below_range(client: TestClient) -> None:
    """Test validation fails when longitude is < -180."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": -181.0},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/route", json=payload)
    assert response.status_code == 422


def test_invalid_vessel_speed_zero_or_negative(client: TestClient) -> None:
    """Test validation fails when speed_knots is <= 0."""
    # Zero speed
    payload_zero = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 0.0},
    }
    response_zero = client.post("/route", json=payload_zero)
    assert response_zero.status_code == 422

    # Negative speed
    payload_neg = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": -5.0},
    }
    response_neg = client.post("/route", json=payload_neg)
    assert response_neg.status_code == 422


def test_valid_route_response_schema() -> None:
    """Test RouteResponse model validation and serialization directly."""
    provider = DefaultRouteProvider()
    service = RouteService(provider=provider)

    req = RouteRequest(
        start=Coordinate(latitude=18.9220, longitude=72.8347),
        destination=Coordinate(latitude=15.4909, longitude=73.8278),
        vessel=Vessel(speed_knots=12.0),
        objective="safe_and_efficient",
    )

    res: RouteResponse = service.calculate_route(req)
    assert isinstance(res, RouteResponse)
    assert isinstance(res.summary, RouteSummary)
    assert isinstance(res.constraints, RouteConstraints)
    assert res.summary.distance_km > 0.0
    assert res.summary.distance_nm > 0.0
    assert res.summary.estimated_time_minutes > 0.0
    assert 0 <= res.summary.route_score <= 100
    assert len(res.waypoints) == 5
    assert res.waypoints[0].latitude == round(req.start.latitude, 6)
    assert res.waypoints[-1].latitude == round(req.destination.latitude, 6)
