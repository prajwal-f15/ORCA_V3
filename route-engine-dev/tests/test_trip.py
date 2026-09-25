"""Unit and integration tests for TripService, Trip persistence, and Trip API endpoints."""

from datetime import datetime, timedelta, timezone
import math
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.request import Coordinate, Vessel
from app.models.trip import (
    TripResponse,
    TripStartRequest,
    TripStatus,
    TripStopRequest,
    TripSummary,
    TripUpdateRequest,
)
from app.repositories.trip_repository import SQLiteTripRepository
from app.services.navigation_service import NavigationService
from app.services.trip_service import (
    InvalidTimestampError,
    TripInactiveError,
    TripNotFoundError,
    TripService,
)


@pytest.fixture
def temp_db(tmp_path: os.PathLike) -> str:
    """Fixture providing an isolated temporary database path for each test."""
    db_file = os.path.join(tmp_path, "test_trip_service.db")
    return str(db_file)


@pytest.fixture
def repo(temp_db: str) -> SQLiteTripRepository:
    """Fixture providing SQLiteTripRepository wired to isolated temp DB."""
    return SQLiteTripRepository(db_path=temp_db)


@pytest.fixture
def trip_service(repo: SQLiteTripRepository) -> TripService:
    """Fixture providing TripService wired to the isolated SQLite repository."""
    nav_service = NavigationService(default_arrival_threshold_nm=0.1)
    return TripService(repository=repo, navigation_service=nav_service)


@pytest.fixture
def client() -> TestClient:
    """Fixture providing FastAPI TestClient."""
    return TestClient(app)


# =========================================================================
# 1-4. START TRIP & INITIAL STATE TESTS
# =========================================================================


def test_start_trip(trip_service: TripService) -> None:
    """Test 1: Starting a trip creates an active trip with correct origin and destination."""
    start_pos = Coordinate(latitude=18.9220, longitude=72.8347)  # Mumbai
    dest_pos = Coordinate(latitude=15.4909, longitude=73.8278)   # Goa
    req = TripStartRequest(
        start=start_pos,
        destination=dest_pos,
        vessel=Vessel(speed_knots=12.0),
    )
    res = trip_service.start_trip(req)
    assert res.trip_id.startswith("trip_")
    assert res.status == TripStatus.ACTIVE.value
    assert res.start_position.latitude == 18.9220
    assert res.destination.latitude == 15.4909


def test_unique_trip_id(trip_service: TripService) -> None:
    """Test 2: Starting multiple trips generates unique, distinct trip IDs."""
    start_pos = Coordinate(latitude=18.9220, longitude=72.8347)
    dest_pos = Coordinate(latitude=15.4909, longitude=73.8278)
    req = TripStartRequest(
        start=start_pos,
        destination=dest_pos,
        vessel=Vessel(speed_knots=10.0),
    )
    res1 = trip_service.start_trip(req)
    res2 = trip_service.start_trip(req)
    assert res1.trip_id != res2.trip_id


def test_first_track_point(trip_service: TripService, repo: SQLiteTripRepository) -> None:
    """Test 3: First recorded track point is precisely the start position with timestamp."""
    start_time = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_pos = Coordinate(latitude=18.9220, longitude=72.8347)
    dest_pos = Coordinate(latitude=15.4909, longitude=73.8278)
    req = TripStartRequest(
        start=start_pos,
        destination=dest_pos,
        vessel=Vessel(speed_knots=12.0),
        timestamp=start_time,
    )
    res = trip_service.start_trip(req)
    assert res.track_points_count == 1

    stored = repo.get_by_id(res.trip_id)
    assert stored is not None
    assert len(stored.track_points) == 1
    assert stored.track_points[0].latitude == 18.9220
    assert stored.track_points[0].longitude == 72.8347
    assert stored.track_points[0].timestamp == start_time


def test_initial_travelled_distance_zero(trip_service: TripService) -> None:
    """Test 4: Initial travelled distance is exactly zero km and zero nautical miles."""
    start_pos = Coordinate(latitude=18.9220, longitude=72.8347)
    dest_pos = Coordinate(latitude=15.4909, longitude=73.8278)
    req = TripStartRequest(
        start=start_pos,
        destination=dest_pos,
        vessel=Vessel(speed_knots=12.0),
    )
    res = trip_service.start_trip(req)
    assert res.distance_travelled_km == 0.0
    assert res.distance_travelled_nm == 0.0
    assert res.elapsed_time_minutes == 0.0


# =========================================================================
# 5-8. GPS UPDATE & CUMULATIVE DISTANCE TESTS
# =========================================================================


def test_single_gps_update(trip_service: TripService) -> None:
    """Test 5: A single GPS update adds segment distance and increments track point count."""
    start_time = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_pos = Coordinate(latitude=18.0, longitude=72.0)
    dest_pos = Coordinate(latitude=15.0, longitude=72.0)
    res_start = trip_service.start_trip(
        TripStartRequest(
            start=start_pos,
            destination=dest_pos,
            vessel=Vessel(speed_knots=10.0),
            timestamp=start_time,
        )
    )

    update_time = start_time + timedelta(minutes=30)
    pos_update = Coordinate(latitude=17.5, longitude=72.0)  # ~55.6 km south
    res_up = trip_service.update_trip(
        res_start.trip_id,
        TripUpdateRequest(current_position=pos_update, timestamp=update_time),
    )
    assert res_up.track_points_count == 2
    assert res_up.current_position.latitude == 17.5
    assert res_up.distance_travelled_km > 50.0
    assert res_up.distance_travelled_nm > 25.0
    assert res_up.elapsed_time_minutes == 30.0


def test_multiple_gps_updates(trip_service: TripService) -> None:
    """Test 6: Multiple sequential GPS updates increment track points and cumulative distance."""
    t0 = datetime(2026, 9, 12, 8, 0, 0, tzinfo=timezone.utc)
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=12.0),
            timestamp=t0,
        )
    )

    points = [
        (17.8, 72.0, 15),
        (17.5, 72.0, 30),
        (17.2, 72.0, 45),
        (17.0, 72.0, 60),
    ]
    for lat, lon, minutes in points:
        t_cur = t0 + timedelta(minutes=minutes)
        res = trip_service.update_trip(
            res.trip_id,
            TripUpdateRequest(
                current_position=Coordinate(latitude=lat, longitude=lon),
                timestamp=t_cur,
            ),
        )

    assert res.track_points_count == 5  # Start + 4 updates
    assert res.elapsed_time_minutes == 60.0
    assert res.distance_travelled_km > 100.0


def test_cumulative_travelled_distance_segment_rule(trip_service: TripService) -> None:
    """Test 7: Travelled distance strictly sums consecutive segments (not direct start-to-current)."""
    t0 = datetime(2026, 9, 12, 8, 0, 0, tzinfo=timezone.utc)
    p0 = Coordinate(latitude=10.0, longitude=70.0)
    dest = Coordinate(latitude=10.0, longitude=73.0)
    res = trip_service.start_trip(
        TripStartRequest(
            start=p0,
            destination=dest,
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Move North to p1 (11.0, 70.0)
    p1 = Coordinate(latitude=11.0, longitude=70.0)
    res = trip_service.update_trip(
        res.trip_id,
        TripUpdateRequest(current_position=p1, timestamp=t0 + timedelta(hours=1)),
    )
    seg1 = res.distance_travelled_km

    # Move back South to p0 (10.0, 70.0)
    p2 = Coordinate(latitude=10.0, longitude=70.0)
    res = trip_service.update_trip(
        res.trip_id,
        TripUpdateRequest(current_position=p2, timestamp=t0 + timedelta(hours=2)),
    )

    # Cumulative travelled distance should be ~ 2 * seg1, whereas direct start-to-current distance is 0!
    assert math.isclose(res.distance_travelled_km, seg1 * 2.0, rel_tol=1e-3)
    assert res.distance_travelled_km > 200.0


def test_same_position_update(trip_service: TripService) -> None:
    """Test 8: Sending the same GPS coordinate adds zero distance."""
    t0 = datetime(2026, 9, 12, 8, 0, 0, tzinfo=timezone.utc)
    p0 = Coordinate(latitude=18.9220, longitude=72.8347)
    res = trip_service.start_trip(
        TripStartRequest(
            start=p0,
            destination=Coordinate(latitude=15.4909, longitude=73.8278),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )
    # First update with identical position
    res = trip_service.update_trip(
        res.trip_id,
        TripUpdateRequest(current_position=p0, timestamp=t0 + timedelta(minutes=10)),
    )
    assert res.distance_travelled_km == 0.0
    assert res.distance_travelled_nm == 0.0
    assert res.track_points_count == 2
    assert res.elapsed_time_minutes == 10.0


# =========================================================================
# 9-12. ELAPSED TIME, STOP TRIP & FINAL GPS POINT TESTS
# =========================================================================


def test_elapsed_time(trip_service: TripService) -> None:
    """Test 9: Elapsed time matches the difference between last timestamp and start timestamp."""
    t0 = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )
    t_update = t0 + timedelta(hours=2, minutes=45)
    res_up = trip_service.update_trip(
        res.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=17.0, longitude=72.0),
            timestamp=t_update,
        ),
    )
    assert res_up.elapsed_time_minutes == 165.0  # 2 hours 45 minutes = 165 minutes


def test_stop_trip(trip_service: TripService) -> None:
    """Test 10: Stopping a trip completes the voyage and updates status."""
    t0 = datetime(2026, 9, 12, 8, 0, 0, tzinfo=timezone.utc)
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )
    stop_res = trip_service.stop_trip(
        res.trip_id,
        TripStopRequest(timestamp=t0 + timedelta(hours=1)),
    )
    assert stop_res.status == TripStatus.COMPLETED.value
    assert stop_res.elapsed_time_minutes == 60.0


def test_completed_status(trip_service: TripService) -> None:
    """Test 11: Completed status is reflected in trip entity and trip summary."""
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=10.0),
        )
    )
    trip_service.stop_trip(res.trip_id)
    retrieved = trip_service.get_trip(res.trip_id)
    assert retrieved.status == TripStatus.COMPLETED.value

    summary: TripSummary = trip_service.get_trip_summary(res.trip_id)
    assert summary.status == TripStatus.COMPLETED.value


def test_final_gps_point(trip_service: TripService) -> None:
    """Test 12: Stopping a trip with a final GPS position records the final track point."""
    t0 = datetime(2026, 9, 12, 8, 0, 0, tzinfo=timezone.utc)
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )
    final_pos = Coordinate(latitude=15.0, longitude=72.0)
    stop_res = trip_service.stop_trip(
        res.trip_id,
        TripStopRequest(
            current_position=final_pos,
            timestamp=t0 + timedelta(hours=3),
        ),
    )
    assert stop_res.status == TripStatus.COMPLETED.value
    assert stop_res.current_position.latitude == 15.0
    assert stop_res.track_points_count == 2
    assert stop_res.distance_travelled_km > 300.0


# =========================================================================
# 13-18. ERROR HANDLING & VALIDATION TESTS
# =========================================================================


def test_unknown_trip(trip_service: TripService) -> None:
    """Test 13: Accessing, updating, or stopping an unknown trip raises TripNotFoundError."""
    with pytest.raises(TripNotFoundError, match="was not found"):
        trip_service.get_trip("trip_non_existent")

    with pytest.raises(TripNotFoundError, match="was not found"):
        trip_service.update_trip(
            "trip_non_existent",
            TripUpdateRequest(current_position=Coordinate(latitude=10.0, longitude=70.0)),
        )

    with pytest.raises(TripNotFoundError, match="was not found"):
        trip_service.stop_trip("trip_non_existent")


def test_update_completed_trip(trip_service: TripService) -> None:
    """Test 14: Updating a completed trip raises TripInactiveError."""
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=10.0),
        )
    )
    trip_service.stop_trip(res.trip_id)

    with pytest.raises(TripInactiveError, match="cannot receive GPS updates|already completed|completed"):
        trip_service.update_trip(
            res.trip_id,
            TripUpdateRequest(current_position=Coordinate(latitude=17.0, longitude=72.0)),
        )


def test_invalid_coordinate_validation() -> None:
    """Test 15: Invalid coordinates (> 90 lat or > 180 lon) raise Pydantic validation error."""
    with pytest.raises(ValueError):
        TripStartRequest(
            start=Coordinate(latitude=95.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=10.0),
        )

    with pytest.raises(ValueError):
        TripUpdateRequest(current_position=Coordinate(latitude=18.0, longitude=190.0))


def test_invalid_speed_validation() -> None:
    """Test 16: Zero or negative speed in Vessel raises Pydantic validation error."""
    with pytest.raises(ValueError):
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=0.0),
        )

    with pytest.raises(ValueError):
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=-5.0),
        )


def test_older_timestamp_rejected(trip_service: TripService) -> None:
    """Test 17: Sending a GPS update with an older timestamp is strictly rejected."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    older_time = t0 - timedelta(minutes=5)
    with pytest.raises(InvalidTimestampError, match="cannot be earlier than previous"):
        trip_service.update_trip(
            res.trip_id,
            TripUpdateRequest(
                current_position=Coordinate(latitude=17.9, longitude=72.0),
                timestamp=older_time,
            ),
        )


def test_navigation_state_included(trip_service: TripService) -> None:
    """Test 18: Every start and GPS update includes a valid NavigationState."""
    res = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.0, longitude=72.0),
            destination=Coordinate(latitude=15.0, longitude=72.0),
            vessel=Vessel(speed_knots=12.0),
            waypoints=[
                Coordinate(latitude=17.0, longitude=72.0),
                Coordinate(latitude=16.0, longitude=72.0),
            ],
        )
    )
    assert res.navigation_state is not None
    assert res.navigation_state.remaining_distance_km > 0.0
    assert res.navigation_state.bearing_degrees == 180.0  # Due South
    assert res.navigation_state.next_waypoint is not None
    assert res.navigation_state.next_waypoint.latitude == 17.0

    # Advance vessel
    res_up = trip_service.update_trip(
        res.trip_id,
        TripUpdateRequest(current_position=Coordinate(latitude=17.0, longitude=72.0)),
    )
    assert res_up.navigation_state.next_waypoint is not None
    assert res_up.navigation_state.next_waypoint.latitude == 16.0


# =========================================================================
# 19-25. PERSISTENCE, HISTORY, TRACK & DELETE TESTS
# =========================================================================


def test_trip_survives_service_and_repo_recreation(temp_db: str) -> None:
    """Test 19: Trip survives service & repository re-instantiation across restarts."""
    repo1 = SQLiteTripRepository(db_path=temp_db)
    svc1 = TripService(repository=repo1)

    t0 = datetime(2026, 9, 12, 9, 0, 0, tzinfo=timezone.utc)
    res_start = svc1.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.9220, longitude=72.8347),
            destination=Coordinate(latitude=15.4909, longitude=73.8278),
            vessel=Vessel(speed_knots=14.0),
            timestamp=t0,
        )
    )
    trip_id = res_start.trip_id

    # Update via svc1
    svc1.update_trip(
        trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=17.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    # Recreate service and repository instance pointing to the same SQLite DB
    repo2 = SQLiteTripRepository(db_path=temp_db)
    svc2 = TripService(repository=repo2)

    loaded = svc2.get_trip(trip_id)
    assert loaded.trip_id == trip_id
    assert loaded.status == "active"
    assert loaded.current_position.latitude == 17.5
    assert loaded.track_points_count == 2
    assert loaded.distance_travelled_km > 100.0


def test_api_start_trip_endpoint(client: TestClient) -> None:
    """Test 20: POST /trips/start returns 201 Created with full TripResponse payload."""
    payload = {
        "start": {"latitude": 18.9220, "longitude": 72.8347},
        "destination": {"latitude": 15.4909, "longitude": 73.8278},
        "vessel": {"speed_knots": 14.5},
        "waypoints": [
            {"latitude": 17.5000, "longitude": 73.1000},
        ],
    }
    response = client.post("/trips/start", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "trip_id" in data
    assert data["status"] == "active"
    assert data["distance_travelled_km"] == 0.0
    assert data["track_points_count"] == 1
    assert "navigation_state" in data


def test_api_update_trip_endpoint(client: TestClient) -> None:
    """Test 21: POST /trips/{trip_id}/update records incremental track point and returns 200."""
    start_payload = {
        "start": {"latitude": 18.0, "longitude": 72.0},
        "destination": {"latitude": 15.0, "longitude": 72.0},
        "vessel": {"speed_knots": 10.0},
    }
    start_res = client.post("/trips/start", json=start_payload).json()
    trip_id = start_res["trip_id"]

    update_payload = {
        "current_position": {"latitude": 17.0, "longitude": 72.0},
    }
    update_res = client.post(f"/trips/{trip_id}/update", json=update_payload)
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["track_points_count"] == 2
    assert data["distance_travelled_km"] > 100.0


def test_api_stop_trip_endpoint(client: TestClient) -> None:
    """Test 22: POST /trips/{trip_id}/stop completes trip and returns 200."""
    start_payload = {
        "start": {"latitude": 18.0, "longitude": 72.0},
        "destination": {"latitude": 15.0, "longitude": 72.0},
        "vessel": {"speed_knots": 10.0},
    }
    start_res = client.post("/trips/start", json=start_payload).json()
    trip_id = start_res["trip_id"]

    stop_payload = {
        "current_position": {"latitude": 15.0, "longitude": 72.0},
    }
    stop_res = client.post(f"/trips/{trip_id}/stop", json=stop_payload)
    assert stop_res.status_code == 200
    data = stop_res.json()
    assert data["status"] == "completed"


def test_api_get_trip_endpoint(client: TestClient) -> None:
    """Test 23: GET /trips/{trip_id} retrieves recorded trip details."""
    start_payload = {
        "start": {"latitude": 18.0, "longitude": 72.0},
        "destination": {"latitude": 15.0, "longitude": 72.0},
        "vessel": {"speed_knots": 10.0},
    }
    start_res = client.post("/trips/start", json=start_payload).json()
    trip_id = start_res["trip_id"]

    get_res = client.get(f"/trips/{trip_id}")
    assert get_res.status_code == 200
    assert get_res.json()["trip_id"] == trip_id

    # Test unknown trip returns 404
    get_404 = client.get("/trips/trip_unknown_id")
    assert get_404.status_code == 404


def test_api_trip_history_endpoint(client: TestClient) -> None:
    """Test 24: GET /trips and GET /api/v1/trips return paginated trip history."""
    # Create an active and completed trip
    start_res = client.post(
        "/trips/start",
        json={
            "start": {"latitude": 18.0, "longitude": 72.0},
            "destination": {"latitude": 15.0, "longitude": 72.0},
            "vessel": {"speed_knots": 10.0},
        },
    ).json()
    trip_id = start_res["trip_id"]

    client.post(
        f"/trips/{trip_id}/stop",
        json={"current_position": {"latitude": 15.0, "longitude": 72.0}},
    )

    history_res = client.get("/trips?limit=10&offset=0")
    assert history_res.status_code == 200
    data = history_res.json()
    assert "trips" in data
    assert "total" in data
    assert data["total"] >= 1
    assert data["trips"][0]["trip_id"] is not None

    # Test v1 prefix
    v1_res = client.get("/api/v1/trips?status=completed")
    assert v1_res.status_code == 200
    assert v1_res.json()["total"] >= 1


def test_api_trip_track_endpoint(client: TestClient) -> None:
    """Test 25: GET /trips/{trip_id}/track returns chronological GPS track points."""
    start_res = client.post(
        "/trips/start",
        json={
            "start": {"latitude": 18.0, "longitude": 72.0},
            "destination": {"latitude": 15.0, "longitude": 72.0},
            "vessel": {"speed_knots": 10.0},
        },
    ).json()
    trip_id = start_res["trip_id"]

    client.post(
        f"/trips/{trip_id}/update",
        json={"current_position": {"latitude": 17.0, "longitude": 72.0}},
    )

    track_res = client.get(f"/trips/{trip_id}/track")
    assert track_res.status_code == 200
    track_data = track_res.json()
    assert track_data["trip_id"] == trip_id
    assert len(track_data["track_points"]) == 2
    assert track_data["track_points"][0]["sequence_number"] == 0
    assert track_data["track_points"][1]["sequence_number"] == 1


def test_api_delete_trip_endpoint(client: TestClient) -> None:
    """Test 26: DELETE /trips/{trip_id} deletes the trip and returns confirmation."""
    start_res = client.post(
        "/trips/start",
        json={
            "start": {"latitude": 18.0, "longitude": 72.0},
            "destination": {"latitude": 15.0, "longitude": 72.0},
            "vessel": {"speed_knots": 10.0},
        },
    ).json()
    trip_id = start_res["trip_id"]

    del_res = client.delete(f"/trips/{trip_id}")
    assert del_res.status_code == 200
    assert del_res.json()["trip_id"] == trip_id

    # Confirm 404 on subsequent get
    assert client.get(f"/trips/{trip_id}").status_code == 404
    # Confirm 404 on deleting non-existent trip
    assert client.delete(f"/trips/{trip_id}").status_code == 404
