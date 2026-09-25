"""Comprehensive unit and integration tests for Step 8 Return Navigation Core."""

from datetime import datetime, timedelta, timezone
import os
import sqlite3
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from app.api.routes import router
from app.db.database import get_db_connection, init_db
from app.main import app
from app.models.request import Coordinate, Vessel
from app.models.trip import (
    ReturnMode,
    ReturnStatus,
    ReturnTripRequest,
    ReturnUpdateRequest,
    TripStartRequest,
    TripStatus,
    TripStopRequest,
    TripTrackPoint,
    TripUpdateRequest,
)
from app.repositories.trip_repository import SQLiteTripRepository, TripRecord
from app.services.geo_service import GeoService
from app.services.navigation_service import NavigationService
from app.services.return_service import (
    ReturnNavigationNotActiveError,
    ReturnService,
)
from app.services.trip_service import (
    InvalidTimestampError,
    TripInactiveError,
    TripNotFoundError,
    TripService,
)


@pytest.fixture
def temp_db_path(tmp_path: os.PathLike) -> str:
    """Fixture providing isolated temporary SQLite database path."""
    db_file = os.path.join(tmp_path, "test_orca_return.db")
    return str(db_file)


@pytest.fixture
def sqlite_repo(temp_db_path: str) -> SQLiteTripRepository:
    """Fixture providing a SQLiteTripRepository instance wired to the isolated temporary database."""
    return SQLiteTripRepository(db_path=temp_db_path)


@pytest.fixture
def trip_service(sqlite_repo: SQLiteTripRepository) -> TripService:
    """Fixture providing TripService wired to test SQLiteTripRepository."""
    nav_service = NavigationService()
    return_svc = ReturnService(navigation_service=nav_service)
    return TripService(
        repository=sqlite_repo,
        navigation_service=nav_service,
        return_service=return_svc,
    )


@pytest.fixture
def client(trip_service: TripService) -> TestClient:
    """Fixture providing FastAPI TestClient with trip_service dependency overridden."""
    from app.services.trip_service import get_trip_service

    app.dependency_overrides[get_trip_service] = lambda: trip_service
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# =============================================================================
# UNIT & SERVICE TESTS (1 - 23)
# =============================================================================


def test_1_return_to_start(trip_service: TripService) -> None:
    """Test 1: Start return navigation with mode 'start'."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_req = TripStartRequest(
        start=Coordinate(latitude=18.9220, longitude=72.8347),
        destination=Coordinate(latitude=18.5000, longitude=72.8000),
        vessel=Vessel(speed_knots=12.0),
        timestamp=t0,
    )
    trip = trip_service.start_trip(start_req)

    # Move vessel out to fishing area
    t1 = t0 + timedelta(hours=1)
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.6000, longitude=72.8200),
            timestamp=t1,
        ),
    )

    ret_state = trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    assert ret_state.trip_id == trip.trip_id
    assert ret_state.return_mode == ReturnMode.START
    assert ret_state.return_destination.latitude == 18.9220
    assert ret_state.return_destination.longitude == 72.8347
    assert ret_state.status == ReturnStatus.RETURNING


def test_2_return_to_harbour(trip_service: TripService) -> None:
    """Test 2: Start return navigation with mode 'harbour'."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_req = TripStartRequest(
        start=Coordinate(latitude=18.9220, longitude=72.8347),
        destination=Coordinate(latitude=18.5000, longitude=72.8000),
        vessel=Vessel(speed_knots=12.0),
        timestamp=t0,
    )
    trip = trip_service.start_trip(start_req)

    harbour_coord = Coordinate(latitude=18.9500, longitude=72.8200)
    ret_state = trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.HARBOUR, harbour=harbour_coord),
    )

    assert ret_state.trip_id == trip.trip_id
    assert ret_state.return_mode == ReturnMode.HARBOUR
    assert ret_state.return_destination.latitude == 18.9500
    assert ret_state.return_destination.longitude == 72.8200
    assert ret_state.status == ReturnStatus.RETURNING


def test_3_harbour_required_for_harbour_mode() -> None:
    """Test 3: Validation fails if harbour coordinate is omitted when mode is harbour."""
    with pytest.raises((ValueError, ValidationError)):
        ReturnTripRequest(mode=ReturnMode.HARBOUR, harbour=None)


def test_4_start_mode_does_not_require_harbour() -> None:
    """Test 4: Harbour coordinate is optional and ignored when mode is start."""
    req = ReturnTripRequest(mode=ReturnMode.START)
    assert req.mode == ReturnMode.START
    assert req.harbour is None


def test_5_return_destination_correctness(trip_service: TripService) -> None:
    """Test 5: Preserves original destination while setting correct return destination."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=18.9220, longitude=72.8347)
    dest_coord = Coordinate(latitude=18.0000, longitude=72.0000)

    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=dest_coord,
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Move out 50 km
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5000, longitude=72.4000),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    # Return to start
    ret_state = trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )
    assert ret_state.return_destination.latitude == start_coord.latitude
    assert ret_state.return_destination.longitude == start_coord.longitude

    # Verify original trip destination is unchanged
    saved_trip = trip_service.get_trip(trip.trip_id)
    assert saved_trip.destination.latitude == dest_coord.latitude
    assert saved_trip.destination.longitude == dest_coord.longitude
    assert saved_trip.start_position.latitude == start_coord.latitude


def test_6_and_7_return_distance_km_and_nm(trip_service: TripService) -> None:
    """Test 6 & 7: Return distance calculation in km and NM using GeoService."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=19.0, longitude=73.0)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Vessel is at (18.5, 73.0)
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    ret_state = trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    expected_km = GeoService.haversine_distance_km(
        Coordinate(latitude=18.5, longitude=73.0), start_coord
    )
    expected_nm = GeoService.km_to_nautical_miles(expected_km)

    assert ret_state.remaining_distance_km == expected_km
    assert ret_state.remaining_distance_nm == expected_nm


def test_8_return_eta(trip_service: TripService) -> None:
    """Test 8: Estimated time remaining to return destination based on vessel speed."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=19.0, longitude=73.0)
    vessel = Vessel(speed_knots=12.0)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=vessel,
            timestamp=t0,
        )
    )

    # Move vessel 0.5 degrees South
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    ret_state = trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    expected_km = GeoService.haversine_distance_km(
        Coordinate(latitude=18.5, longitude=73.0), start_coord
    )
    expected_nm = GeoService.km_to_nautical_miles(expected_km)
    expected_eta = GeoService.calculate_eta_minutes(expected_nm, vessel.speed_knots)
    assert ret_state.estimated_time_remaining_minutes == expected_eta


def test_9_return_bearing(trip_service: TripService) -> None:
    """Test 9: Bearing angle towards return destination."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=19.0, longitude=73.0)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Move vessel directly South of start
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    ret_state = trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    # Bearing from (18.5, 73.0) to (19.0, 73.0) directly North should be ~0.0 degrees
    expected_bearing = GeoService.initial_bearing_degrees(
        Coordinate(latitude=18.5, longitude=73.0), start_coord
    )
    assert ret_state.bearing_degrees == expected_bearing
    assert round(ret_state.bearing_degrees, 1) == 0.0


def test_10_return_progress(trip_service: TripService) -> None:
    """Test 10: Progress percentage along the return leg."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=19.0, longitude=73.0)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Move to (18.0, 73.0)
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.0, longitude=73.0),
            timestamp=t0 + timedelta(hours=2),
        ),
    )

    # Start return from (18.0, 73.0) to (19.0, 73.0)
    ret_state_start = trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )
    assert ret_state_start.progress_percent == 0.0

    # Advance halfway back to (18.5, 73.0)
    ret_state_half = trip_service.update_return(
        trip.trip_id,
        ReturnUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=3),
        ),
    )
    # Approx 50% progress
    assert 48.0 <= ret_state_half.progress_percent <= 52.0


def test_11_and_12_return_arrival_threshold_and_status(
    trip_service: TripService,
) -> None:
    """Test 11 & 12: Arriving within configurable arrival threshold sets return_arrived and clamps metrics."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=18.9220, longitude=72.8347)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=Coordinate(latitude=18.5000, longitude=72.8000),
            vessel=Vessel(speed_knots=12.0),
            arrival_threshold_nm=0.2,
            timestamp=t0,
        )
    )

    # Move out 20 km
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.7000, longitude=72.8000),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    # Start return
    trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    # Send GPS update within 0.05 NM of start (~50 meters away)
    near_start = Coordinate(latitude=18.9222, longitude=72.8347)
    ret_state = trip_service.update_return(
        trip.trip_id,
        ReturnUpdateRequest(
            current_position=near_start,
            timestamp=t0 + timedelta(hours=2),
        ),
    )

    assert ret_state.status == ReturnStatus.RETURN_ARRIVED
    assert ret_state.remaining_distance_km == 0.0
    assert ret_state.remaining_distance_nm == 0.0
    assert ret_state.estimated_time_remaining_minutes == 0.0
    assert ret_state.progress_percent == 100.0

    # Trip remains active until explicit stop
    saved_trip = trip_service.get_trip(trip.trip_id)
    assert saved_trip.status == TripStatus.ACTIVE.value


def test_13_return_gps_update(trip_service: TripService) -> None:
    """Test 13: Updating GPS position during active return recalculates return navigation metrics."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=19.0, longitude=73.0)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Start return from (18.0, 73.0)
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.0, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )
    trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    # Update GPS to (18.6, 73.0)
    updated_state = trip_service.update_return(
        trip.trip_id,
        ReturnUpdateRequest(
            current_position=Coordinate(latitude=18.6, longitude=73.0),
            timestamp=t0 + timedelta(hours=2),
        ),
    )

    assert updated_state.current_position.latitude == 18.6
    assert updated_state.remaining_distance_km < 50.0
    assert updated_state.status == ReturnStatus.RETURNING


def test_14_cumulative_trip_distance_continues_during_return(
    trip_service: TripService,
) -> None:
    """Test 14: Total trip distance accumulates outbound and return legs without resetting."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    p0 = Coordinate(latitude=19.0, longitude=73.0)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=p0,
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Outbound leg to p1
    p1 = Coordinate(latitude=18.5, longitude=73.0)
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(current_position=p1, timestamp=t0 + timedelta(hours=1)),
    )
    outbound_km = GeoService.haversine_distance_km(p0, p1)

    # Start return to p0
    trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    # Return leg to p2
    p2 = Coordinate(latitude=18.8, longitude=73.0)
    trip_service.update_return(
        trip.trip_id,
        ReturnUpdateRequest(current_position=p2, timestamp=t0 + timedelta(hours=2)),
    )
    return_leg_km = GeoService.haversine_distance_km(p1, p2)

    total_trip = trip_service.get_trip(trip.trip_id)
    expected_total_km = round(outbound_km + return_leg_km, 4)
    assert abs(total_trip.distance_travelled_km - expected_total_km) < 0.01


def test_15_return_track_points_append_to_existing_trip(
    trip_service: TripService,
) -> None:
    """Test 15: Return GPS points are appended to the existing trip's track points."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=19.0, longitude=73.0),
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )
    # 1 track point at start
    assert len(trip.track_points) == 1

    # Outbound update
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )
    # Start return
    trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    # Return update
    trip_service.update_return(
        trip.trip_id,
        ReturnUpdateRequest(
            current_position=Coordinate(latitude=18.9, longitude=73.0),
            timestamp=t0 + timedelta(hours=2),
        ),
    )

    saved_track = trip_service.get_trip_track(trip.trip_id)
    assert len(saved_track.track_points) == 3
    assert saved_track.track_points[0].sequence_number == 0
    assert saved_track.track_points[1].sequence_number == 1
    assert saved_track.track_points[2].sequence_number == 2


def test_16_and_17_return_cancel_and_original_trip_active(
    trip_service: TripService,
) -> None:
    """Test 16 & 17: Cancelling return navigation clears return state and keeps trip active."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=19.0, longitude=73.0),
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    # Move out first
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    # Cancel return
    cancel_res = trip_service.cancel_return(trip.trip_id)
    assert cancel_res.trip_id == trip.trip_id
    assert "cancelled" in cancel_res.message.lower()

    # Verify trip is still active and return state is cleared
    saved_trip = trip_service.get_trip(trip.trip_id)
    assert saved_trip.status == TripStatus.ACTIVE.value
    assert saved_trip.return_navigation_state is None

    # Getting return state now raises ReturnNavigationNotActiveError
    with pytest.raises(ReturnNavigationNotActiveError):
        trip_service.get_return_state(trip.trip_id)


def test_18_unknown_trip(trip_service: TripService) -> None:
    """Test 18: Operations on non-existent trip_id raise TripNotFoundError."""
    with pytest.raises(TripNotFoundError):
        trip_service.start_return("unknown_trip", ReturnTripRequest(mode=ReturnMode.START))

    with pytest.raises(TripNotFoundError):
        trip_service.update_return(
            "unknown_trip",
            ReturnUpdateRequest(
                current_position=Coordinate(latitude=18.0, longitude=72.0),
                timestamp=datetime.now(timezone.utc),
            ),
        )

    with pytest.raises(TripNotFoundError):
        trip_service.cancel_return("unknown_trip")

    with pytest.raises(TripNotFoundError):
        trip_service.get_return_state("unknown_trip")


def test_19_return_on_completed_trip_rejected(trip_service: TripService) -> None:
    """Test 19: Starting return on a completed trip raises TripInactiveError."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=19.0, longitude=73.0),
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )
    trip_service.stop_trip(trip.trip_id, TripStopRequest(timestamp=t0 + timedelta(hours=1)))

    with pytest.raises(TripInactiveError):
        trip_service.start_return(trip.trip_id, ReturnTripRequest(mode=ReturnMode.START))


def test_20_return_update_without_active_return_rejected(
    trip_service: TripService,
) -> None:
    """Test 20: Updating return GPS without starting return raises ReturnNavigationNotActiveError."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=19.0, longitude=73.0),
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )

    with pytest.raises(ReturnNavigationNotActiveError):
        trip_service.update_return(
            trip.trip_id,
            ReturnUpdateRequest(
                current_position=Coordinate(latitude=18.5, longitude=73.0),
                timestamp=t0 + timedelta(hours=1),
            ),
        )


def test_21_return_state_retrieval(trip_service: TripService) -> None:
    """Test 21: get_return_state returns accurate snapshot."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_coord = Coordinate(latitude=19.0, longitude=73.0)
    trip = trip_service.start_trip(
        TripStartRequest(
            start=start_coord,
            destination=Coordinate(latitude=18.0, longitude=73.0),
            vessel=Vessel(speed_knots=10.0),
            timestamp=t0,
        )
    )
    # Move out
    trip_service.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=73.0),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    trip_service.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.START),
    )

    state = trip_service.get_return_state(trip.trip_id)
    assert state.trip_id == trip.trip_id
    assert state.return_mode == ReturnMode.START
    assert state.return_destination.latitude == start_coord.latitude


def test_22_return_persistence_after_repository_recreation(
    temp_db_path: str,
) -> None:
    """Test 22: Return state survives repository recreation (backend restart)."""
    repo1 = SQLiteTripRepository(db_path=temp_db_path)
    service1 = TripService(repository=repo1)

    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    harbour = Coordinate(latitude=18.9500, longitude=72.8200)
    trip = service1.start_trip(
        TripStartRequest(
            start=Coordinate(latitude=18.9220, longitude=72.8347),
            destination=Coordinate(latitude=18.0000, longitude=72.0000),
            vessel=Vessel(speed_knots=12.0),
            timestamp=t0,
        )
    )
    # Move out 20 km
    service1.update_trip(
        trip.trip_id,
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.7000, longitude=72.8000),
            timestamp=t0 + timedelta(hours=1),
        ),
    )

    service1.start_return(
        trip.trip_id,
        ReturnTripRequest(mode=ReturnMode.HARBOUR, harbour=harbour),
    )

    # Recreate repository pointing to the same SQLite database
    repo2 = SQLiteTripRepository(db_path=temp_db_path)
    service2 = TripService(repository=repo2)

    loaded_state = service2.get_return_state(trip.trip_id)
    assert loaded_state.trip_id == trip.trip_id
    assert loaded_state.return_mode == ReturnMode.HARBOUR
    assert loaded_state.return_destination.latitude == harbour.latitude
    assert loaded_state.return_destination.longitude == harbour.longitude
    assert loaded_state.status == ReturnStatus.RETURNING


def test_23_database_schema_migration(tmp_path: os.PathLike) -> None:
    """Test 23: Safe migration mechanism upgrades older DB schema without return columns non-destructively."""
    old_db_file = str(os.path.join(tmp_path, "legacy_orca.db"))

    # Create legacy table schema (Step 7 version without return fields)
    with get_db_connection(old_db_file) as conn:
        conn.execute(
            """
            CREATE TABLE trips (
                trip_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                start_latitude REAL NOT NULL,
                start_longitude REAL NOT NULL,
                destination_latitude REAL NOT NULL,
                destination_longitude REAL NOT NULL,
                speed_knots REAL NOT NULL,
                waypoints_json TEXT NOT NULL,
                arrival_threshold_nm REAL NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                current_latitude REAL NOT NULL,
                current_longitude REAL NOT NULL,
                distance_travelled_km REAL NOT NULL,
                distance_travelled_nm REAL NOT NULL,
                elapsed_time_minutes REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE track_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips (trip_id) ON DELETE CASCADE
            );
            """
        )
        # Insert legacy trip
        conn.execute(
            """
            INSERT INTO trips (
                trip_id, status, start_latitude, start_longitude,
                destination_latitude, destination_longitude, speed_knots,
                waypoints_json, arrival_threshold_nm, started_at,
                current_latitude, current_longitude, distance_travelled_km,
                distance_travelled_nm, elapsed_time_minutes, created_at, updated_at
            ) VALUES (
                'legacy_001', 'active', 18.9, 72.8, 18.0, 72.0, 10.0,
                '[]', 0.1, '2026-09-12T10:00:00+00:00',
                18.9, 72.8, 0.0, 0.0, 0.0,
                '2026-09-12T10:00:00+00:00', '2026-09-12T10:00:00+00:00'
            );
            """
        )

    # Initialize repository on legacy DB (triggers migration)
    migrated_repo = SQLiteTripRepository(db_path=old_db_file)
    legacy_trip = migrated_repo.get_by_id("legacy_001")

    assert legacy_trip is not None
    assert legacy_trip.trip_id == "legacy_001"
    assert legacy_trip.return_mode is None
    assert legacy_trip.return_status is None

    # Now verify we can use return features on the migrated database
    service = TripService(repository=migrated_repo)
    # Move vessel away from start first
    service.update_trip(
        "legacy_001",
        TripUpdateRequest(
            current_position=Coordinate(latitude=18.5, longitude=72.5),
            timestamp=datetime(2026, 9, 12, 11, 0, 0, tzinfo=timezone.utc),
        ),
    )
    ret_state = service.start_return(
        "legacy_001",
        ReturnTripRequest(mode=ReturnMode.START),
    )
    assert ret_state.return_mode == ReturnMode.START
    assert ret_state.status == ReturnStatus.RETURNING


# =============================================================================
# API INTEGRATION TESTS (24 - 27)
# =============================================================================


def test_24_api_start_return(client: TestClient) -> None:
    """Test 24: POST /trips/{trip_id}/return/start and /api/v1/trips/{trip_id}/return/start."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_resp = client.post(
        "/trips/start",
        json={
            "start": {"latitude": 18.9220, "longitude": 72.8347},
            "destination": {"latitude": 18.0000, "longitude": 72.0000},
            "vessel": {"speed_knots": 12.0},
            "timestamp": t0.isoformat(),
        },
    )
    assert start_resp.status_code == 201
    trip_id = start_resp.json()["trip_id"]

    # Move vessel out
    client.post(
        f"/trips/{trip_id}/update",
        json={
            "current_position": {"latitude": 18.5000, "longitude": 72.5000},
            "timestamp": (t0 + timedelta(hours=1)).isoformat(),
        },
    )

    # Start return via root route
    return_resp = client.post(
        f"/trips/{trip_id}/return/start",
        json={"mode": "start"},
    )
    assert return_resp.status_code == 200
    data = return_resp.json()
    assert data["trip_id"] == trip_id
    assert data["return_mode"] == "start"
    assert data["status"] == "returning"

    # Also test API v1 prefix route on a second trip
    start_resp2 = client.post(
        "/api/v1/trips/start",
        json={
            "start": {"latitude": 18.9220, "longitude": 72.8347},
            "destination": {"latitude": 18.0000, "longitude": 72.0000},
            "vessel": {"speed_knots": 12.0},
            "timestamp": t0.isoformat(),
        },
    )
    assert start_resp2.status_code == 201
    trip_id2 = start_resp2.json()["trip_id"]

    # Move vessel 2 out
    client.post(
        f"/api/v1/trips/{trip_id2}/update",
        json={
            "current_position": {"latitude": 18.5000, "longitude": 72.5000},
            "timestamp": (t0 + timedelta(hours=1)).isoformat(),
        },
    )

    harbour_payload = {
        "mode": "harbour",
        "harbour": {"latitude": 18.9500, "longitude": 72.8200},
    }
    return_resp2 = client.post(
        f"/api/v1/trips/{trip_id2}/return/start",
        json=harbour_payload,
    )
    assert return_resp2.status_code == 200
    data2 = return_resp2.json()
    assert data2["return_mode"] == "harbour"
    assert data2["return_destination"]["latitude"] == 18.9500
    assert data2["status"] == "returning"


def test_25_api_update_return(client: TestClient) -> None:
    """Test 25: POST /trips/{trip_id}/return/update."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_resp = client.post(
        "/trips/start",
        json={
            "start": {"latitude": 19.0, "longitude": 73.0},
            "destination": {"latitude": 18.0, "longitude": 73.0},
            "vessel": {"speed_knots": 10.0},
            "timestamp": t0.isoformat(),
        },
    )
    trip_id = start_resp.json()["trip_id"]

    # Move vessel out to (18.0, 73.0)
    t1 = t0 + timedelta(hours=1)
    client.post(
        f"/trips/{trip_id}/update",
        json={
            "current_position": {"latitude": 18.0, "longitude": 73.0},
            "timestamp": t1.isoformat(),
        },
    )

    # Start return
    client.post(f"/trips/{trip_id}/return/start", json={"mode": "start"})

    # Send return GPS update to (18.6, 73.0)
    t2 = t1 + timedelta(hours=1)
    update_resp = client.post(
        f"/trips/{trip_id}/return/update",
        json={
            "current_position": {"latitude": 18.6, "longitude": 73.0},
            "timestamp": t2.isoformat(),
        },
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["current_position"]["latitude"] == 18.6
    assert data["status"] == "returning"


def test_26_api_cancel_return(client: TestClient) -> None:
    """Test 26: POST /trips/{trip_id}/return/cancel."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_resp = client.post(
        "/trips/start",
        json={
            "start": {"latitude": 19.0, "longitude": 73.0},
            "destination": {"latitude": 18.0, "longitude": 73.0},
            "vessel": {"speed_knots": 10.0},
            "timestamp": t0.isoformat(),
        },
    )
    trip_id = start_resp.json()["trip_id"]

    # Move vessel out
    client.post(
        f"/trips/{trip_id}/update",
        json={
            "current_position": {"latitude": 18.5, "longitude": 73.0},
            "timestamp": (t0 + timedelta(hours=1)).isoformat(),
        },
    )

    client.post(f"/trips/{trip_id}/return/start", json={"mode": "start"})

    # Cancel return
    cancel_resp = client.post(f"/trips/{trip_id}/return/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["trip_id"] == trip_id

    # Verify return state is now 404
    get_ret = client.get(f"/trips/{trip_id}/return")
    assert get_ret.status_code == 404


def test_27_api_get_return_state(client: TestClient) -> None:
    """Test 27: GET /trips/{trip_id}/return."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    start_resp = client.post(
        "/trips/start",
        json={
            "start": {"latitude": 18.9220, "longitude": 72.8347},
            "destination": {"latitude": 18.0000, "longitude": 72.0000},
            "vessel": {"speed_knots": 12.0},
            "timestamp": t0.isoformat(),
        },
    )
    trip_id = start_resp.json()["trip_id"]

    # Before return starts -> 404
    before_resp = client.get(f"/trips/{trip_id}/return")
    assert before_resp.status_code == 404

    # Move vessel out
    client.post(
        f"/trips/{trip_id}/update",
        json={
            "current_position": {"latitude": 18.5000, "longitude": 72.5000},
            "timestamp": (t0 + timedelta(hours=1)).isoformat(),
        },
    )

    # Start return
    client.post(f"/trips/{trip_id}/return/start", json={"mode": "start"})

    # After return starts -> 200
    after_resp = client.get(f"/trips/{trip_id}/return")
    assert after_resp.status_code == 200
    data = after_resp.json()
    assert data["trip_id"] == trip_id
    assert data["return_mode"] == "start"
    assert data["status"] == "returning"
