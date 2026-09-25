"""Unit and integration tests for NavigationService and Navigation API endpoint."""

import math
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.request import Coordinate, NavigationRequest, Vessel
from app.models.response import NavigationState
from app.services.geo_service import GeoService
from app.services.navigation_service import NavigationService
from app.services.route_service import RouteService


@pytest.fixture
def client() -> TestClient:
    """Fixture providing FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def nav_service() -> NavigationService:
    """Fixture providing an instance of NavigationService."""
    return NavigationService(default_arrival_threshold_nm=0.1)


# =========================================================================
# 1-5. BEARING TESTS
# =========================================================================


def test_bearing_north(nav_service: NavigationService) -> None:
    """Test standard initial great-circle bearing pointing due North ≈ 0° / 360°."""
    start = Coordinate(latitude=10.0, longitude=70.0)
    target = Coordinate(latitude=20.0, longitude=70.0)
    bearing = GeoService.initial_bearing_degrees(start, target)
    assert math.isclose(bearing, 0.0, abs_tol=0.1)


def test_bearing_east(nav_service: NavigationService) -> None:
    """Test standard initial great-circle bearing pointing due East ≈ 90°."""
    start = Coordinate(latitude=0.0, longitude=70.0)
    target = Coordinate(latitude=0.0, longitude=80.0)
    bearing = GeoService.initial_bearing_degrees(start, target)
    assert math.isclose(bearing, 90.0, abs_tol=0.1)


def test_bearing_south(nav_service: NavigationService) -> None:
    """Test standard initial great-circle bearing pointing due South ≈ 180°."""
    start = Coordinate(latitude=20.0, longitude=70.0)
    target = Coordinate(latitude=10.0, longitude=70.0)
    bearing = GeoService.initial_bearing_degrees(start, target)
    assert math.isclose(bearing, 180.0, abs_tol=0.1)


def test_bearing_west(nav_service: NavigationService) -> None:
    """Test standard initial great-circle bearing pointing due West ≈ 270°."""
    start = Coordinate(latitude=0.0, longitude=80.0)
    target = Coordinate(latitude=0.0, longitude=70.0)
    bearing = GeoService.initial_bearing_degrees(start, target)
    assert math.isclose(bearing, 270.0, abs_tol=0.1)


def test_bearing_normalization(nav_service: NavigationService) -> None:
    """Test bearing is strictly normalized to [0, 360) across quadrants and identical points."""
    # Identical coordinates
    c = Coordinate(latitude=18.9220, longitude=72.8347)
    assert GeoService.initial_bearing_degrees(c, c) == 0.0

    # Northwest quadrant (~315°)
    nw_start = Coordinate(latitude=10.0, longitude=10.0)
    nw_dest = Coordinate(latitude=15.0, longitude=5.0)
    nw_bearing = GeoService.initial_bearing_degrees(nw_start, nw_dest)
    assert 270.0 < nw_bearing < 360.0

    # Southwest quadrant (~225°)
    sw_dest = Coordinate(latitude=5.0, longitude=5.0)
    sw_bearing = GeoService.initial_bearing_degrees(nw_start, sw_dest)
    assert 180.0 < sw_bearing < 270.0

    # Southeast quadrant (~135°)
    se_dest = Coordinate(latitude=5.0, longitude=15.0)
    se_bearing = GeoService.initial_bearing_degrees(nw_start, se_dest)
    assert 90.0 < se_bearing < 180.0


# =========================================================================
# 6-8. DISTANCE & ETA TESTS
# =========================================================================


def test_remaining_distance(nav_service: NavigationService) -> None:
    """Test remaining distance calculation in kilometers from current position to destination."""
    curr = Coordinate(latitude=18.9220, longitude=72.8347)  # Mumbai
    dest = Coordinate(latitude=15.4909, longitude=73.8278)  # Goa
    req = NavigationRequest(
        current_position=curr,
        start=curr,
        destination=dest,
        vessel=Vessel(speed_knots=15.0),
    )
    state = nav_service.calculate_navigation_state(req)
    expected_km = GeoService.haversine_distance_km(curr, dest)
    assert math.isclose(state.remaining_distance_km, expected_km, rel_tol=1e-3)
    assert 385.0 < state.remaining_distance_km < 400.0


def test_remaining_distance_in_nautical_miles(nav_service: NavigationService) -> None:
    """Test remaining distance calculation in nautical miles matches km / 1.852 standard."""
    curr = Coordinate(latitude=18.9220, longitude=72.8347)
    dest = Coordinate(latitude=15.4909, longitude=73.8278)
    req = NavigationRequest(
        current_position=curr,
        start=curr,
        destination=dest,
        vessel=Vessel(speed_knots=15.0),
    )
    state = nav_service.calculate_navigation_state(req)
    assert math.isclose(
        state.remaining_distance_nm,
        state.remaining_distance_km / 1.852,
        rel_tol=1e-3,
    )


def test_remaining_eta(nav_service: NavigationService) -> None:
    """Test remaining ETA computation: time_minutes = (remaining_nm / speed_knots) * 60."""
    curr = Coordinate(latitude=18.0, longitude=73.0)
    dest = Coordinate(latitude=16.0, longitude=73.0)
    speed = 12.0
    req = NavigationRequest(
        current_position=curr,
        start=Coordinate(latitude=19.0, longitude=73.0),
        destination=dest,
        vessel=Vessel(speed_knots=speed),
    )
    state = nav_service.calculate_navigation_state(req)
    expected_eta = round((state.remaining_distance_nm / speed) * 60.0, 2)
    assert math.isclose(state.estimated_time_remaining_minutes, expected_eta, abs_tol=0.1)


# =========================================================================
# 9-12. PROGRESS TESTS
# =========================================================================


def test_progress_at_route_start(nav_service: NavigationService) -> None:
    """Test route progress is approximately 0% when current position matches origin."""
    start = Coordinate(latitude=18.9220, longitude=72.8347)
    dest = Coordinate(latitude=15.4909, longitude=73.8278)
    req = NavigationRequest(
        current_position=start,
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=12.0),
    )
    state = nav_service.calculate_navigation_state(req)
    assert state.progress_percent == 0.0
    assert state.status == "not_started"


def test_progress_around_halfway(nav_service: NavigationService) -> None:
    """Test route progress is approximately 50% when vessel is around the midpoint."""
    start = Coordinate(latitude=10.0, longitude=70.0)
    mid = Coordinate(latitude=15.0, longitude=70.0)
    dest = Coordinate(latitude=20.0, longitude=70.0)
    req = NavigationRequest(
        current_position=mid,
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
    )
    state = nav_service.calculate_navigation_state(req)
    assert 49.0 <= state.progress_percent <= 51.0
    assert state.status == "navigating"


def test_progress_near_destination(nav_service: NavigationService) -> None:
    """Test route progress is 100% when vessel is within arrival threshold of destination."""
    dest = Coordinate(latitude=15.4909, longitude=73.8278)
    # A point within 0.05 NM of destination
    near_dest = Coordinate(latitude=15.4909, longitude=73.8279)
    req = NavigationRequest(
        current_position=near_dest,
        start=Coordinate(latitude=18.9220, longitude=72.8347),
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
        arrival_threshold_nm=0.5,
    )
    state = nav_service.calculate_navigation_state(req)
    assert state.progress_percent == 100.0
    assert state.estimated_time_remaining_minutes == 0.0
    assert state.status == "arrived"


def test_progress_clamping(nav_service: NavigationService) -> None:
    """Test progress is strictly clamped within [0, 100] when vessel is behind start or beyond dest."""
    start = Coordinate(latitude=10.0, longitude=70.0)
    dest = Coordinate(latitude=20.0, longitude=70.0)

    # Position behind start (further away from dest than start is)
    behind_start = Coordinate(latitude=5.0, longitude=70.0)
    req_behind = NavigationRequest(
        current_position=behind_start,
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
    )
    state_behind = nav_service.calculate_navigation_state(req_behind)
    assert state_behind.progress_percent == 0.0

    # Position at or past destination
    req_at_dest = NavigationRequest(
        current_position=dest,
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
    )
    state_at_dest = nav_service.calculate_navigation_state(req_at_dest)
    assert state_at_dest.progress_percent == 100.0


# =========================================================================
# 13-15. ARRIVAL, ZERO-DISTANCE & INVALID SPEED TESTS
# =========================================================================


def test_arrival_threshold(nav_service: NavigationService) -> None:
    """Test configurable arrival threshold correctly flags arrived state and clears ETA."""
    dest = Coordinate(latitude=12.0, longitude=80.0)
    # 0.08 NM away from destination
    near_dest = Coordinate(latitude=12.001, longitude=80.0)
    dist_nm = GeoService.km_to_nautical_miles(GeoService.haversine_distance_km(near_dest, dest))

    # Test with threshold larger than distance -> Arrived
    req_arrived = NavigationRequest(
        current_position=near_dest,
        start=Coordinate(latitude=10.0, longitude=80.0),
        destination=dest,
        vessel=Vessel(speed_knots=12.0),
        arrival_threshold_nm=dist_nm + 0.1,
    )
    state_arrived = nav_service.calculate_navigation_state(req_arrived)
    assert state_arrived.status == "arrived"
    assert state_arrived.progress_percent == 100.0
    assert state_arrived.estimated_time_remaining_minutes == 0.0

    # Test with threshold smaller than distance -> Navigating
    req_navigating = NavigationRequest(
        current_position=near_dest,
        start=Coordinate(latitude=10.0, longitude=80.0),
        destination=dest,
        vessel=Vessel(speed_knots=12.0),
        arrival_threshold_nm=dist_nm - 0.01,
    )
    state_navigating = nav_service.calculate_navigation_state(req_navigating)
    assert state_navigating.status == "navigating"
    assert state_navigating.estimated_time_remaining_minutes > 0.0


def test_zero_distance_navigation(nav_service: NavigationService) -> None:
    """Test zero distance navigation when start, destination, and current position are identical."""
    coord = Coordinate(latitude=18.9220, longitude=72.8347)
    req = NavigationRequest(
        current_position=coord,
        start=coord,
        destination=coord,
        vessel=Vessel(speed_knots=12.0),
    )
    state = nav_service.calculate_navigation_state(req)
    assert state.remaining_distance_km == 0.0
    assert state.remaining_distance_nm == 0.0
    assert state.estimated_time_remaining_minutes == 0.0
    assert state.progress_percent == 100.0
    assert state.bearing_degrees == 0.0
    assert state.next_waypoint is None
    assert state.status == "arrived"


def test_invalid_or_zero_vessel_speed(nav_service: NavigationService) -> None:
    """Test that zero or negative vessel speed raises ValueError in NavigationService."""
    curr = Coordinate(latitude=18.0, longitude=72.0)
    dest = Coordinate(latitude=15.0, longitude=73.0)

    # Directly creating NavigationRequest with speed 0 bypasses pydantic if constructed manually
    # or testing calculation method directly
    req = NavigationRequest(
        current_position=curr,
        start=curr,
        destination=dest,
        vessel=Vessel(speed_knots=10.0),
    )
    # Manually mutate speed to test service-level defense
    req.vessel.speed_knots = 0.0
    with pytest.raises(ValueError, match="must be greater than zero"):
        nav_service.calculate_navigation_state(req)

    req.vessel.speed_knots = -5.0
    with pytest.raises(ValueError, match="must be greater than zero"):
        nav_service.calculate_navigation_state(req)


# =========================================================================
# 16-18. WAYPOINT DETECTION, NO WAYPOINT & NAVIGATION STATUS TESTS
# =========================================================================


def test_next_waypoint_detection(nav_service: NavigationService) -> None:
    """Test sequential next waypoint detection as vessel advances along planned waypoints."""
    w0 = Coordinate(latitude=10.0, longitude=70.0)
    w1 = Coordinate(latitude=12.0, longitude=70.0)
    w2 = Coordinate(latitude=14.0, longitude=70.0)
    w3 = Coordinate(latitude=16.0, longitude=70.0)
    w4 = Coordinate(latitude=18.0, longitude=70.0)  # Destination
    waypoints = [w0, w1, w2, w3, w4]

    # At start (w0): next waypoint should be w1
    req_at_start = NavigationRequest(
        current_position=w0,
        start=w0,
        destination=w4,
        vessel=Vessel(speed_knots=10.0),
        waypoints=waypoints,
    )
    state_start = nav_service.calculate_navigation_state(req_at_start)
    assert state_start.next_waypoint is not None
    assert state_start.next_waypoint.latitude == w1.latitude
    assert state_start.next_waypoint.longitude == w1.longitude
    assert state_start.total_waypoints == 5

    # En route between w1 and w2 (e.g., at lat 13.0): next waypoint should be w2
    pos_mid = Coordinate(latitude=13.0, longitude=70.0)
    req_mid = NavigationRequest(
        current_position=pos_mid,
        start=w0,
        destination=w4,
        vessel=Vessel(speed_knots=10.0),
        waypoints=waypoints,
    )
    state_mid = nav_service.calculate_navigation_state(req_mid)
    assert state_mid.next_waypoint is not None
    assert state_mid.next_waypoint.latitude == w2.latitude

    # At w3: next waypoint should be w4
    req_at_w3 = NavigationRequest(
        current_position=w3,
        start=w0,
        destination=w4,
        vessel=Vessel(speed_knots=10.0),
        waypoints=waypoints,
    )
    state_w3 = nav_service.calculate_navigation_state(req_at_w3)
    assert state_w3.next_waypoint is not None
    assert state_w3.next_waypoint.latitude == w4.latitude

    # At w4 (destination): next waypoint should be None
    req_at_dest = NavigationRequest(
        current_position=w4,
        start=w0,
        destination=w4,
        vessel=Vessel(speed_knots=10.0),
        waypoints=waypoints,
    )
    state_dest = nav_service.calculate_navigation_state(req_at_dest)
    assert state_dest.next_waypoint is None
    assert state_dest.status == "arrived"


def test_no_waypoint_case(nav_service: NavigationService) -> None:
    """Test navigation state calculation when no intermediate waypoints are provided."""
    start = Coordinate(latitude=18.9220, longitude=72.8347)
    dest = Coordinate(latitude=15.4909, longitude=73.8278)
    curr = Coordinate(latitude=17.0000, longitude=73.2000)

    req = NavigationRequest(
        current_position=curr,
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=12.0),
        waypoints=[],
    )
    state = nav_service.calculate_navigation_state(req)
    assert state.next_waypoint is None
    assert state.total_waypoints == 0
    assert state.status == "navigating"
    # Bearing should be directed straight toward destination
    expected_bearing = GeoService.initial_bearing_degrees(curr, dest)
    assert math.isclose(state.bearing_degrees, expected_bearing, abs_tol=0.1)


def test_navigation_status_lifecycle(nav_service: NavigationService) -> None:
    """Test full lifecycle transition of navigation status: not_started -> navigating -> arrived."""
    start = Coordinate(latitude=10.0, longitude=70.0)
    dest = Coordinate(latitude=20.0, longitude=70.0)

    # 1. Not started (at origin)
    req_start = NavigationRequest(
        current_position=start,
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=12.0),
    )
    assert nav_service.calculate_navigation_state(req_start).status == "not_started"

    # 2. Navigating (underway)
    req_nav = NavigationRequest(
        current_position=Coordinate(latitude=14.0, longitude=70.0),
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=12.0),
    )
    assert nav_service.calculate_navigation_state(req_nav).status == "navigating"

    # 3. Arrived (at destination)
    req_arr = NavigationRequest(
        current_position=dest,
        start=start,
        destination=dest,
        vessel=Vessel(speed_knots=12.0),
    )
    assert nav_service.calculate_navigation_state(req_arr).status == "arrived"


# =========================================================================
# API ENDPOINT TESTS (POST /navigation/state)
# =========================================================================


def test_api_navigation_state_endpoint(client: TestClient) -> None:
    """Test POST /navigation/state returns 200 OK with fully validated NavigationState response."""
    payload = {
        "current_position": {"latitude": 17.5000, "longitude": 73.1000},
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 14.0},
        "waypoints": [
            {"latitude": 18.9220, "longitude": 72.8347},
            {"latitude": 17.2000, "longitude": 73.3000},
            {"latitude": 15.4909, "longitude": 73.8278},
        ],
        "arrival_threshold_nm": 0.2,
    }
    response = client.post("/navigation/state", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "current_position" in data
    assert "destination" in data
    assert data["remaining_distance_km"] > 0.0
    assert data["remaining_distance_nm"] > 0.0
    assert data["estimated_time_remaining_minutes"] > 0.0
    assert 0.0 <= data["bearing_degrees"] < 360.0
    assert 0.0 <= data["progress_percent"] <= 100.0
    assert data["total_waypoints"] == 3
    assert data["status"] in ["not_started", "navigating", "arrived"]


def test_api_navigation_state_arrived(client: TestClient) -> None:
    """Test POST /navigation/state returns arrived status and 100% progress when at destination."""
    payload = {
        "current_position": {"latitude": 15.4909, "longitude": 73.8278},
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/navigation/state", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "arrived"
    assert data["progress_percent"] == 100.0
    assert data["estimated_time_remaining_minutes"] == 0.0


def test_api_navigation_state_validation_error(client: TestClient) -> None:
    """Test POST /navigation/state returns 422 for invalid coordinate or zero vessel speed."""
    # Invalid speed (<= 0)
    payload_invalid_speed = {
        "current_position": {"latitude": 18.9220, "longitude": 72.8347},
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 0.0},
    }
    response = client.post("/navigation/state", json=payload_invalid_speed)
    assert response.status_code == 422

    # Invalid latitude (> 90)
    payload_invalid_lat = {
        "current_position": {"latitude": 95.0, "longitude": 72.8347},
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 12.0},
    }
    response = client.post("/navigation/state", json=payload_invalid_lat)
    assert response.status_code == 422
