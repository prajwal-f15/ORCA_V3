"""Tests for Brain Route Engine Client Tool and POST /test/route-engine endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from brain_integration.route_engine_tool import (
    RouteEngineError,
    call_route_engine_api,
)
from brain_integration.routes import router as brain_test_router


import httpx
from app.main import app as route_engine_app


_route_engine_test_client = TestClient(route_engine_app)


class LocalhostASGITransport(httpx.BaseTransport):
    """Transport that routes 127.0.0.1:8000 requests to Route Engine ASGI app, and others to network."""

    def __init__(self) -> None:
        self.http_transport = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host in ("127.0.0.1", "localhost", "testserver") and request.url.port == 8000:
            return _route_engine_test_client._transport.handle_request(request)
        return self.http_transport.handle_request(request)


@pytest.fixture(autouse=True)
def route_engine_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture ensuring route engine calls to localhost:8000 route in-process during tests."""
    original_client_init = httpx.Client.__init__

    def patched_client_init(self, *args, **kwargs):
        if "transport" not in kwargs or kwargs["transport"] is None:
            kwargs["transport"] = LocalhostASGITransport()
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_client_init)


def get_brain_test_app() -> FastAPI:
    """Create FastAPI application representing the Brain backend with the integration router mounted."""
    app = FastAPI(title="ORCA Brain Test Backend")
    app.include_router(brain_test_router)
    return app


@pytest.fixture
def brain_client() -> TestClient:
    """Fixture providing TestClient for the Brain test backend."""
    return TestClient(get_brain_test_app())


def test_brain_call_route_engine_api_live() -> None:
    """Test call_route_engine_api against the live Route Engine service at http://127.0.0.1:8000/route."""
    response = call_route_engine_api(
        start_latitude=18.5204,
        start_longitude=72.8567,
        dest_latitude=18.6500,
        dest_longitude=72.9000,
        speed_knots=8.5,
        objective="safe_and_efficient",
        route_engine_url="http://127.0.0.1:8000/route",
    )

    assert "route_id" in response
    assert response["status"] == "computed"
    assert "summary" in response
    assert "waypoints" in response
    assert len(response["waypoints"]) >= 2
    assert response["summary"]["distance_km"] > 0.0
    assert response["summary"]["distance_nm"] > 0.0
    assert response["summary"]["estimated_time_minutes"] > 0.0
    assert 0.0 <= response["summary"]["route_score"] <= 100.0


def test_brain_test_endpoint_live(brain_client: TestClient) -> None:
    """Test POST /test/route-engine in the Brain backend delegating to Route Engine."""
    payload = {
        "start": {"latitude": 18.5204, "longitude": 72.8567},
        "destination": {"latitude": 18.6500, "longitude": 72.9000},
        "vessel": {"speed_knots": 8.5},
        "objective": "safe_and_efficient",
    }
    response = brain_client.post("/test/route-engine", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "route_id" in data
    assert data["status"] == "computed"
    assert data["summary"]["distance_km"] > 0.0
    assert data["summary"]["distance_nm"] > 0.0
    assert data["summary"]["estimated_time_minutes"] > 0.0
    assert len(data["waypoints"]) >= 2


def test_brain_route_engine_unavailable_error() -> None:
    """Test error handling when Route Engine is unavailable at invalid port."""
    with pytest.raises(RouteEngineError) as exc_info:
        call_route_engine_api(
            start_latitude=18.5204,
            start_longitude=72.8567,
            dest_latitude=18.6500,
            dest_longitude=72.9000,
            route_engine_url="http://127.0.0.1:59999/route",
            timeout=0.5,
        )

    err_str = str(exc_info.value)
    assert any(
        phrase in err_str
        for phrase in ["Could not connect", "timed out", "Network communication error"]
    )


def test_brain_route_engine_http_error() -> None:
    """Test error handling when Route Engine returns 422 for invalid coordinate."""
    with pytest.raises(RouteEngineError) as exc_info:
        call_route_engine_api(
            start_latitude=95.0,  # Invalid latitude > 90
            start_longitude=72.8567,
            dest_latitude=18.6500,
            dest_longitude=72.9000,
            route_engine_url="http://127.0.0.1:8000/route",
        )

    assert exc_info.value.status_code == 422
