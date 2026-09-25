"""Unit and integration tests for SQLiteTripRepository and database transactions."""

from datetime import datetime, timedelta, timezone
import os
import sqlite3
import pytest
from app.db.database import get_db_connection, init_db
from app.models.request import Coordinate, Vessel
from app.models.trip import TripStatus, TripTrackPoint
from app.repositories.trip_repository import SQLiteTripRepository, TripRecord


@pytest.fixture
def temp_db_path(tmp_path: os.PathLike) -> str:
    """Fixture providing an isolated temporary SQLite database path."""
    db_file = os.path.join(tmp_path, "test_orca.db")
    return str(db_file)


@pytest.fixture
def sqlite_repo(temp_db_path: str) -> SQLiteTripRepository:
    """Fixture providing a SQLiteTripRepository instance wired to the isolated temporary database."""
    return SQLiteTripRepository(db_path=temp_db_path)


def test_database_initialization(temp_db_path: str) -> None:
    """Test 1: Database tables and indexes are initialized correctly on startup."""
    init_db(temp_db_path)
    assert os.path.exists(temp_db_path)

    with get_db_connection(temp_db_path) as conn:
        cur = conn.cursor()
        # Verify tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row["name"] for row in cur.fetchall()}
        assert "trips" in tables
        assert "track_points" in tables

        # Verify indexes exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indexes = {row["name"] for row in cur.fetchall()}
        assert "idx_trips_status" in indexes
        assert "idx_track_points_trip_seq" in indexes


def test_create_and_retrieve_trip(sqlite_repo: SQLiteTripRepository) -> None:
    """Test 2 & 3: Creating a trip and retrieving it by unique ID."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = TripRecord(
        trip_id="trip_test_001",
        start_position=Coordinate(latitude=18.9220, longitude=72.8347),
        current_position=Coordinate(latitude=18.9220, longitude=72.8347),
        destination=Coordinate(latitude=15.4909, longitude=73.8278),
        vessel=Vessel(speed_knots=12.0),
        waypoints=[Coordinate(latitude=17.0, longitude=73.0)],
        arrival_threshold_nm=0.1,
        status=TripStatus.ACTIVE.value,
        track_points=[
            TripTrackPoint(latitude=18.9220, longitude=72.8347, timestamp=t0, sequence_number=0)
        ],
        distance_travelled_km=0.0,
        start_timestamp=t0,
        last_timestamp=t0,
    )

    saved = sqlite_repo.save(trip)
    assert saved.trip_id == "trip_test_001"

    retrieved = sqlite_repo.get_by_id("trip_test_001")
    assert retrieved is not None
    assert retrieved.trip_id == "trip_test_001"
    assert retrieved.status == TripStatus.ACTIVE.value
    assert retrieved.start_position.latitude == 18.9220
    assert retrieved.destination.latitude == 15.4909
    assert retrieved.vessel.speed_knots == 12.0
    assert len(retrieved.waypoints) == 1
    assert len(retrieved.track_points) == 1
    assert retrieved.track_points[0].sequence_number == 0


def test_update_trip_and_track_points(sqlite_repo: SQLiteTripRepository) -> None:
    """Test 4 & 5: Updating a trip adds new track points and updates cumulative metrics."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = TripRecord(
        trip_id="trip_test_002",
        start_position=Coordinate(latitude=18.0, longitude=72.0),
        current_position=Coordinate(latitude=18.0, longitude=72.0),
        destination=Coordinate(latitude=15.0, longitude=72.0),
        vessel=Vessel(speed_knots=10.0),
        waypoints=[],
        arrival_threshold_nm=0.1,
        status=TripStatus.ACTIVE.value,
        track_points=[
            TripTrackPoint(latitude=18.0, longitude=72.0, timestamp=t0, sequence_number=0)
        ],
        distance_travelled_km=0.0,
        start_timestamp=t0,
        last_timestamp=t0,
    )
    sqlite_repo.save(trip)

    # Append second track point
    t1 = t0 + timedelta(minutes=30)
    trip.track_points.append(
        TripTrackPoint(latitude=17.5, longitude=72.0, timestamp=t1, sequence_number=1)
    )
    trip.current_position = Coordinate(latitude=17.5, longitude=72.0)
    trip.distance_travelled_km = 55.6
    trip.last_timestamp = t1
    sqlite_repo.save(trip)

    retrieved = sqlite_repo.get_by_id("trip_test_002")
    assert retrieved is not None
    assert len(retrieved.track_points) == 2
    assert retrieved.current_position.latitude == 17.5
    assert retrieved.distance_travelled_km == 55.6


def test_retrieve_track_points_and_sequence_ordering(
    sqlite_repo: SQLiteTripRepository,
) -> None:
    """Test 6 & 7: Retrieving track points returns strictly ordered sequence numbers."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    points = [
        TripTrackPoint(latitude=18.0, longitude=72.0, timestamp=t0, sequence_number=0),
        TripTrackPoint(latitude=17.8, longitude=72.0, timestamp=t0 + timedelta(minutes=15), sequence_number=1),
        TripTrackPoint(latitude=17.5, longitude=72.0, timestamp=t0 + timedelta(minutes=30), sequence_number=2),
    ]
    trip = TripRecord(
        trip_id="trip_test_003",
        start_position=Coordinate(latitude=18.0, longitude=72.0),
        current_position=Coordinate(latitude=17.5, longitude=72.0),
        destination=Coordinate(latitude=15.0, longitude=72.0),
        vessel=Vessel(speed_knots=10.0),
        waypoints=[],
        arrival_threshold_nm=0.1,
        status=TripStatus.ACTIVE.value,
        track_points=points,
        distance_travelled_km=55.6,
        start_timestamp=t0,
        last_timestamp=t0 + timedelta(minutes=30),
    )
    sqlite_repo.save(trip)

    track = sqlite_repo.get_track_points("trip_test_003")
    assert len(track) == 3
    for i, tp in enumerate(track):
        assert tp.sequence_number == i


def test_trip_persistence_after_repository_reinstantiation(
    temp_db_path: str,
) -> None:
    """Test 8: Stored trip survives repository re-instantiation / backend restart."""
    repo1 = SQLiteTripRepository(db_path=temp_db_path)
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = TripRecord(
        trip_id="trip_persist_999",
        start_position=Coordinate(latitude=18.9220, longitude=72.8347),
        current_position=Coordinate(latitude=18.9220, longitude=72.8347),
        destination=Coordinate(latitude=15.4909, longitude=73.8278),
        vessel=Vessel(speed_knots=12.0),
        waypoints=[],
        arrival_threshold_nm=0.1,
        status=TripStatus.ACTIVE.value,
        track_points=[
            TripTrackPoint(latitude=18.9220, longitude=72.8347, timestamp=t0, sequence_number=0)
        ],
        distance_travelled_km=0.0,
        start_timestamp=t0,
        last_timestamp=t0,
    )
    repo1.save(trip)

    # Re-instantiate repository pointing to same database
    repo2 = SQLiteTripRepository(db_path=temp_db_path)
    loaded = repo2.get_by_id("trip_persist_999")
    assert loaded is not None
    assert loaded.trip_id == "trip_persist_999"
    assert loaded.start_position.latitude == 18.9220


def test_delete_trip_and_cascade_deletion(sqlite_repo: SQLiteTripRepository) -> None:
    """Test 9 & 10: Deleting a trip cascades to delete all associated track points."""
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    trip = TripRecord(
        trip_id="trip_to_delete",
        start_position=Coordinate(latitude=18.0, longitude=72.0),
        current_position=Coordinate(latitude=18.0, longitude=72.0),
        destination=Coordinate(latitude=15.0, longitude=72.0),
        vessel=Vessel(speed_knots=10.0),
        waypoints=[],
        arrival_threshold_nm=0.1,
        status=TripStatus.ACTIVE.value,
        track_points=[
            TripTrackPoint(latitude=18.0, longitude=72.0, timestamp=t0, sequence_number=0),
            TripTrackPoint(latitude=17.5, longitude=72.0, timestamp=t0 + timedelta(minutes=30), sequence_number=1),
        ],
        distance_travelled_km=55.0,
        start_timestamp=t0,
        last_timestamp=t0 + timedelta(minutes=30),
    )
    sqlite_repo.save(trip)

    deleted = sqlite_repo.delete("trip_to_delete")
    assert deleted is True

    # Check trip is gone
    assert sqlite_repo.get_by_id("trip_to_delete") is None
    # Check track points are cascaded
    track = sqlite_repo.get_track_points("trip_to_delete")
    assert len(track) == 0


def test_status_filtering_and_pagination(sqlite_repo: SQLiteTripRepository) -> None:
    """Test 11 & 12: Status filtering and pagination work accurately."""
    t0 = datetime(2026, 9, 12, 8, 0, 0, tzinfo=timezone.utc)

    # Insert 3 active trips and 2 completed trips
    for i in range(3):
        sqlite_repo.save(
            TripRecord(
                trip_id=f"trip_active_{i}",
                start_position=Coordinate(latitude=18.0, longitude=72.0),
                current_position=Coordinate(latitude=18.0, longitude=72.0),
                destination=Coordinate(latitude=15.0, longitude=72.0),
                vessel=Vessel(speed_knots=10.0),
                waypoints=[],
                arrival_threshold_nm=0.1,
                status=TripStatus.ACTIVE.value,
                track_points=[
                    TripTrackPoint(latitude=18.0, longitude=72.0, timestamp=t0 + timedelta(minutes=i))
                ],
                distance_travelled_km=0.0,
                start_timestamp=t0 + timedelta(minutes=i),
                last_timestamp=t0 + timedelta(minutes=i),
            )
        )

    for i in range(2):
        sqlite_repo.save(
            TripRecord(
                trip_id=f"trip_completed_{i}",
                start_position=Coordinate(latitude=18.0, longitude=72.0),
                current_position=Coordinate(latitude=15.0, longitude=72.0),
                destination=Coordinate(latitude=15.0, longitude=72.0),
                vessel=Vessel(speed_knots=10.0),
                waypoints=[],
                arrival_threshold_nm=0.1,
                status=TripStatus.COMPLETED.value,
                track_points=[
                    TripTrackPoint(latitude=18.0, longitude=72.0, timestamp=t0 + timedelta(hours=i + 5))
                ],
                distance_travelled_km=300.0,
                start_timestamp=t0 + timedelta(hours=i + 5),
                last_timestamp=t0 + timedelta(hours=i + 5),
                completed_at=t0 + timedelta(hours=i + 5),
            )
        )

    # Filter active
    active_trips, active_cnt = sqlite_repo.list_trips(status="active")
    assert active_cnt == 3
    assert len(active_trips) == 3

    # Filter completed
    completed_trips, completed_cnt = sqlite_repo.list_trips(status="completed")
    assert completed_cnt == 2
    assert len(completed_trips) == 2

    # Pagination: total 5 trips, limit 2, offset 0 -> 2 items
    p1, total = sqlite_repo.list_trips(limit=2, offset=0)
    assert total == 5
    assert len(p1) == 2

    # Pagination: limit 2, offset 4 -> 1 item
    p3, _ = sqlite_repo.list_trips(limit=2, offset=4)
    assert len(p3) == 1


def test_transaction_rollback_on_failure(temp_db_path: str) -> None:
    """Test 13: Transaction rolls back if an error occurs inside connection context."""
    init_db(temp_db_path)

    with pytest.raises(RuntimeError):
        with get_db_connection(temp_db_path) as conn:
            conn.execute(
                """
                INSERT INTO trips (
                    trip_id, status, start_latitude, start_longitude,
                    destination_latitude, destination_longitude, speed_knots,
                    waypoints_json, arrival_threshold_nm, started_at,
                    current_latitude, current_longitude, distance_travelled_km,
                    distance_travelled_nm, elapsed_time_minutes, created_at, updated_at
                ) VALUES ('trip_fail', 'active', 10, 10, 20, 20, 10, '[]', 0.1, '2026-09-12T00:00:00',
                          10, 10, 0, 0, 0, '2026-09-12T00:00:00', '2026-09-12T00:00:00')
                """
            )
            # Deliberately raise exception to trigger rollback
            raise RuntimeError("Forced simulation error")

    # Verify trip was rolled back and not persisted
    with get_db_connection(temp_db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM trips WHERE trip_id = 'trip_fail'")
        assert cur.fetchone() is None


def test_unknown_trip_handling(sqlite_repo: SQLiteTripRepository) -> None:
    """Test 14: Querying or deleting a non-existent trip returns None or False."""
    assert sqlite_repo.get_by_id("non_existent_trip_id") is None
    assert sqlite_repo.delete("non_existent_trip_id") is False
    assert sqlite_repo.get_track_points("non_existent_trip_id") == []
