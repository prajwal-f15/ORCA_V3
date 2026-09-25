"""Tests for health check and core endpoints."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.routing.base import RouteProvider
from app.routing.provider import DefaultRouteProvider
from app.services.route_service import RouteService


@pytest.fixture
def client() -> TestClient:
    """Fixture to provide FastAPI TestClient."""
    return TestClient(app)


def test_health_check(client: TestClient) -> None:
    """Test the GET /health endpoint returns expected status and format."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "ok",
        "service": "orca-route-engine",
    }


def test_api_v1_health_check(client: TestClient) -> None:
    """Test the GET /api/v1/health route."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_endpoint(client: TestClient) -> None:
    """Test the root GET / endpoint returns service information."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "environment" in data
    assert "docs_url" in data
    assert data["name"] == "orca-route-engine"


def test_route_service_provider_abstraction() -> None:
    """Test RouteService dependency on RouteProvider abstraction."""
    provider = DefaultRouteProvider()
    service = RouteService(provider=provider)

    assert isinstance(service.provider, RouteProvider)
    status_info = service.get_service_status()
    assert status_info["service"] == "orca-route-engine"
    assert status_info["provider"]["status"] == "active"
