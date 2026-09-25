"""Route Engine Client and Tool for ORCA Brain Integration.

This module provides a dedicated, test-only HTTP client tool for ORCA Brain
to communicate with the standalone ORCA V3 Route Engine service.

Architecture Flow:
    Brain (LLM / Agent / Orchestrator)
        ↓
    Route Engine Client / Tool (this module)
        ↓  POST http://127.0.0.1:8000/route
    ORCA V3 Route Engine (FastAPI Microservice)
        ↓
    Validated RouteResponse JSON
"""

import logging
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger("orca_brain.route_engine_client")

# Default Route Engine URL (Local testing)
DEFAULT_ROUTE_ENGINE_URL = "http://127.0.0.1:8000/route"
DEFAULT_TIMEOUT_SECONDS = 15.0


class RouteEngineError(Exception):
    """Base exception for Route Engine client communication failures."""

    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


def call_route_engine_api(
    start_latitude: float,
    start_longitude: float,
    dest_latitude: float,
    dest_longitude: float,
    speed_knots: float = 8.5,
    objective: str = "safe_and_efficient",
    route_engine_url: str = DEFAULT_ROUTE_ENGINE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Call the ORCA V3 Route Engine API to calculate a marine voyage route.

    Args:
        start_latitude: Starting latitude in decimal degrees (-90 to 90).
        start_longitude: Starting longitude in decimal degrees (-180 to 180).
        dest_latitude: Destination latitude in decimal degrees (-90 to 90).
        dest_longitude: Destination longitude in decimal degrees (-180 to 180).
        speed_knots: Vessel operational speed in knots (> 0).
        objective: Routing objective (default: "safe_and_efficient").
        route_engine_url: URL to Route Engine POST endpoint.
        timeout: HTTP request timeout in seconds.

    Returns:
        Dict[str, Any] containing the complete Route Engine response JSON:
            - route_id: Unique route identifier
            - status: Execution status
            - summary: { distance_km, distance_nm, estimated_time_minutes, route_score }
            - waypoints: List of { latitude, longitude } points
            - constraints: { safety_check, weather_check, restricted_area_check }
            - marine_conditions: Optional snapshot

    Raises:
        RouteEngineError: On connection refused, timeout, 4xx/5xx HTTP errors, or invalid JSON.
    """
    payload = {
        "start": {
            "latitude": float(start_latitude),
            "longitude": float(start_longitude),
        },
        "destination": {
            "latitude": float(dest_latitude),
            "longitude": float(dest_longitude),
        },
        "vessel": {
            "speed_knots": float(speed_knots),
        },
        "objective": str(objective),
    }

    logger.info("Calling Route Engine at %s with payload: %s", route_engine_url, payload)

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                route_engine_url,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )

            # Check for HTTP status errors (4xx / 5xx)
            if response.is_error:
                error_detail = None
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text

                raise RouteEngineError(
                    message=f"Route Engine returned HTTP {response.status_code}: {error_detail}",
                    status_code=response.status_code,
                    details=error_detail,
                )

            # Parse JSON response
            try:
                response_data = response.json()
            except Exception as json_err:
                raise RouteEngineError(
                    message=f"Invalid JSON response from Route Engine: {json_err}",
                    status_code=response.status_code,
                    details=response.text,
                ) from json_err

            logger.info("Route Engine response successfully received. Route ID: %s", response_data.get("route_id"))
            return response_data

    except httpx.ConnectError as conn_err:
        error_msg = (
            f"Could not connect to Route Engine at {route_engine_url}. "
            "Ensure the Route Engine service is running (e.g., uvicorn app.main:app --port 8000)."
        )
        logger.error(error_msg)
        raise RouteEngineError(message=error_msg) from conn_err

    except httpx.TimeoutException as timeout_err:
        error_msg = f"Request to Route Engine at {route_engine_url} timed out after {timeout} seconds."
        logger.error(error_msg)
        raise RouteEngineError(message=error_msg) from timeout_err

    except httpx.RequestError as req_err:
        error_msg = f"Network communication error with Route Engine: {req_err}"
        logger.error(error_msg)
        raise RouteEngineError(message=error_msg) from req_err
