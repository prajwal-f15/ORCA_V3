"""Repository abstraction and SQLite implementation for persistent Trip storage."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Dict, List, Optional, Tuple
from app.db.database import get_configured_db_path, get_db_connection, init_db
from app.models.request import Coordinate, Vessel
from app.models.response import NavigationState
from app.models.trip import TripTrackPoint


@dataclass
class TripRecord:
    """Domain record representing the full state and history of a voyage trip."""

    trip_id: str
    start_position: Coordinate
    current_position: Coordinate
    destination: Coordinate
    vessel: Vessel
    waypoints: List[Coordinate]
    arrival_threshold_nm: float
    status: str
    track_points: List[TripTrackPoint]
    distance_travelled_km: float
    start_timestamp: datetime
    last_timestamp: datetime
    completed_at: Optional[datetime] = None
    navigation_state: Optional[NavigationState] = None
    return_mode: Optional[str] = None
    return_destination: Optional[Coordinate] = None
    return_status: Optional[str] = None
    return_started_at: Optional[datetime] = None
    return_completed_at: Optional[datetime] = None
    return_origin_position: Optional[Coordinate] = None


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Safely parse ISO datetime string into UTC-aware datetime."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class TripRepository(ABC):
    """Abstract interface for Trip data persistence."""

    @abstractmethod
    def save(self, trip: TripRecord) -> TripRecord:
        """Persist or update a trip record transactionally."""
        pass

    @abstractmethod
    def get_by_id(self, trip_id: str) -> Optional[TripRecord]:
        """Retrieve a trip record by its unique ID."""
        pass

    @abstractmethod
    def list_trips(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[TripRecord], int]:
        """List trips matching optional filters with pagination, returning (trips, total_count)."""
        pass

    @abstractmethod
    def get_track_points(self, trip_id: str) -> List[TripTrackPoint]:
        """Retrieve all track points for a trip ordered chronologically."""
        pass

    @abstractmethod
    def delete(self, trip_id: str) -> bool:
        """Delete a trip and its associated track points."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all stored trip records (used primarily for test isolation)."""
        pass


class SQLiteTripRepository(TripRepository):
    """SQLite-backed persistent implementation of TripRepository."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize SQLiteTripRepository and ensure schema is created.

        Args:
            db_path: Path to SQLite database file. Defaults to configured ORCA_ROUTE_DB_PATH.
        """
        self.db_path = db_path or get_configured_db_path()
        init_db(self.db_path)

    def save(self, trip: TripRecord) -> TripRecord:
        """Persist or update a trip record and its track points in a single transaction."""
        waypoints_data = json.dumps(
            [{"latitude": wp.latitude, "longitude": wp.longitude} for wp in trip.waypoints]
        )
        started_at_str = trip.start_timestamp.isoformat()
        updated_at_str = trip.last_timestamp.isoformat()
        completed_at_str = trip.completed_at.isoformat() if trip.completed_at else None
        return_started_at_str = (
            trip.return_started_at.isoformat() if trip.return_started_at else None
        )
        return_completed_at_str = (
            trip.return_completed_at.isoformat() if trip.return_completed_at else None
        )
        return_dest_lat = (
            trip.return_destination.latitude if trip.return_destination else None
        )
        return_dest_lon = (
            trip.return_destination.longitude if trip.return_destination else None
        )
        return_orig_lat = (
            trip.return_origin_position.latitude if trip.return_origin_position else None
        )
        return_orig_lon = (
            trip.return_origin_position.longitude if trip.return_origin_position else None
        )

        dist_nm = round(trip.distance_travelled_km / 1.852, 4)
        elapsed_minutes = round(
            max(0.0, (trip.last_timestamp - trip.start_timestamp).total_seconds()) / 60.0, 2
        )

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT trip_id FROM trips WHERE trip_id = ?", (trip.trip_id,))
            existing = cur.fetchone()

            if existing is None:
                cur.execute(
                    """
                    INSERT INTO trips (
                        trip_id, status, start_latitude, start_longitude,
                        destination_latitude, destination_longitude, speed_knots,
                        waypoints_json, arrival_threshold_nm, started_at, completed_at,
                        current_latitude, current_longitude, distance_travelled_km,
                        distance_travelled_nm, elapsed_time_minutes, created_at, updated_at,
                        return_mode, return_destination_latitude, return_destination_longitude,
                        return_status, return_started_at, return_completed_at,
                        return_origin_latitude, return_origin_longitude
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trip.trip_id,
                        trip.status,
                        trip.start_position.latitude,
                        trip.start_position.longitude,
                        trip.destination.latitude,
                        trip.destination.longitude,
                        trip.vessel.speed_knots,
                        waypoints_data,
                        trip.arrival_threshold_nm,
                        started_at_str,
                        completed_at_str,
                        trip.current_position.latitude,
                        trip.current_position.longitude,
                        trip.distance_travelled_km,
                        dist_nm,
                        elapsed_minutes,
                        started_at_str,
                        updated_at_str,
                        trip.return_mode,
                        return_dest_lat,
                        return_dest_lon,
                        trip.return_status,
                        return_started_at_str,
                        return_completed_at_str,
                        return_orig_lat,
                        return_orig_lon,
                    ),
                )
                # Insert initial track points
                for idx, tp in enumerate(trip.track_points):
                    tp.sequence_number = idx
                    cur.execute(
                        """
                        INSERT INTO track_points (
                            trip_id, latitude, longitude, timestamp, sequence_number
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (trip.trip_id, tp.latitude, tp.longitude, tp.timestamp.isoformat(), idx),
                    )
            else:
                cur.execute(
                    """
                    UPDATE trips SET
                        status = ?,
                        current_latitude = ?,
                        current_longitude = ?,
                        distance_travelled_km = ?,
                        distance_travelled_nm = ?,
                        elapsed_time_minutes = ?,
                        completed_at = ?,
                        updated_at = ?,
                        return_mode = ?,
                        return_destination_latitude = ?,
                        return_destination_longitude = ?,
                        return_status = ?,
                        return_started_at = ?,
                        return_completed_at = ?,
                        return_origin_latitude = ?,
                        return_origin_longitude = ?
                    WHERE trip_id = ?
                    """,
                    (
                        trip.status,
                        trip.current_position.latitude,
                        trip.current_position.longitude,
                        trip.distance_travelled_km,
                        dist_nm,
                        elapsed_minutes,
                        completed_at_str,
                        updated_at_str,
                        trip.return_mode,
                        return_dest_lat,
                        return_dest_lon,
                        trip.return_status,
                        return_started_at_str,
                        return_completed_at_str,
                        return_orig_lat,
                        return_orig_lon,
                        trip.trip_id,
                    ),
                )
                # Insert new track points beyond max sequence number
                cur.execute(
                    "SELECT COALESCE(MAX(sequence_number), -1) as max_seq FROM track_points WHERE trip_id = ?",
                    (trip.trip_id,),
                )
                max_seq = cur.fetchone()["max_seq"]
                for idx, tp in enumerate(trip.track_points):
                    if idx > max_seq:
                        tp.sequence_number = idx
                        cur.execute(
                            """
                            INSERT INTO track_points (
                                trip_id, latitude, longitude, timestamp, sequence_number
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                trip.trip_id,
                                tp.latitude,
                                tp.longitude,
                                tp.timestamp.isoformat(),
                                idx,
                            ),
                        )

        return trip

    def get_by_id(self, trip_id: str) -> Optional[TripRecord]:
        """Load a trip and its ordered track points from SQLite."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trips WHERE trip_id = ?", (trip_id,))
            row = cur.fetchone()
            if row is None:
                return None

            # Load track points
            cur.execute(
                "SELECT * FROM track_points WHERE trip_id = ? ORDER BY sequence_number ASC",
                (trip_id,),
            )
            tp_rows = cur.fetchall()
            track_points: List[TripTrackPoint] = [
                TripTrackPoint(
                    latitude=r["latitude"],
                    longitude=r["longitude"],
                    timestamp=parse_iso_datetime(r["timestamp"]) or datetime.now(timezone.utc),
                    sequence_number=r["sequence_number"],
                )
                for r in tp_rows
            ]

            # Reconstruct waypoints
            waypoints_raw = json.loads(row["waypoints_json"] or "[]")
            waypoints = [Coordinate(latitude=w["latitude"], longitude=w["longitude"]) for w in waypoints_raw]

            start_ts = parse_iso_datetime(row["started_at"]) or datetime.now(timezone.utc)
            last_ts = parse_iso_datetime(row["updated_at"]) or start_ts
            completed_ts = parse_iso_datetime(row["completed_at"])
            return_started_ts = parse_iso_datetime(row["return_started_at"])
            return_completed_ts = parse_iso_datetime(row["return_completed_at"])

            return_dest = None
            if row["return_destination_latitude"] is not None and row["return_destination_longitude"] is not None:
                return_dest = Coordinate(
                    latitude=row["return_destination_latitude"],
                    longitude=row["return_destination_longitude"],
                )

            return_orig = None
            if row["return_origin_latitude"] is not None and row["return_origin_longitude"] is not None:
                return_orig = Coordinate(
                    latitude=row["return_origin_latitude"],
                    longitude=row["return_origin_longitude"],
                )

            return TripRecord(
                trip_id=row["trip_id"],
                start_position=Coordinate(
                    latitude=row["start_latitude"], longitude=row["start_longitude"]
                ),
                current_position=Coordinate(
                    latitude=row["current_latitude"], longitude=row["current_longitude"]
                ),
                destination=Coordinate(
                    latitude=row["destination_latitude"],
                    longitude=row["destination_longitude"],
                ),
                vessel=Vessel(speed_knots=row["speed_knots"]),
                waypoints=waypoints,
                arrival_threshold_nm=row["arrival_threshold_nm"],
                status=row["status"],
                track_points=track_points,
                distance_travelled_km=row["distance_travelled_km"],
                start_timestamp=start_ts,
                last_timestamp=last_ts,
                completed_at=completed_ts,
                return_mode=row["return_mode"],
                return_destination=return_dest,
                return_status=row["return_status"],
                return_started_at=return_started_ts,
                return_completed_at=return_completed_ts,
                return_origin_position=return_orig,
            )

    def list_trips(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[TripRecord], int]:
        """Query trips with optional status filter, returning records and total count."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            if status:
                cur.execute("SELECT COUNT(*) as cnt FROM trips WHERE status = ?", (status,))
                total = cur.fetchone()["cnt"]
                cur.execute(
                    """
                    SELECT * FROM trips WHERE status = ?
                    ORDER BY started_at DESC, created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status, limit, offset),
                )
            else:
                cur.execute("SELECT COUNT(*) as cnt FROM trips")
                total = cur.fetchone()["cnt"]
                cur.execute(
                    """
                    SELECT * FROM trips
                    ORDER BY started_at DESC, created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )
            rows = cur.fetchall()

            trips: List[TripRecord] = []
            for row in rows:
                trip_id = row["trip_id"]
                cur.execute(
                    "SELECT COUNT(*) as tp_cnt FROM track_points WHERE trip_id = ?",
                    (trip_id,),
                )
                tp_cnt = cur.fetchone()["tp_cnt"]

                waypoints_raw = json.loads(row["waypoints_json"] or "[]")
                waypoints = [Coordinate(latitude=w["latitude"], longitude=w["longitude"]) for w in waypoints_raw]
                start_ts = parse_iso_datetime(row["started_at"]) or datetime.now(timezone.utc)
                last_ts = parse_iso_datetime(row["updated_at"]) or start_ts
                completed_ts = parse_iso_datetime(row["completed_at"])

                dummy_track_points = [
                    TripTrackPoint(
                        latitude=row["current_latitude"],
                        longitude=row["current_longitude"],
                        timestamp=last_ts,
                    )
                ] * max(1, tp_cnt)

                trips.append(
                    TripRecord(
                        trip_id=trip_id,
                        start_position=Coordinate(
                            latitude=row["start_latitude"], longitude=row["start_longitude"]
                        ),
                        current_position=Coordinate(
                            latitude=row["current_latitude"], longitude=row["current_longitude"]
                        ),
                        destination=Coordinate(
                            latitude=row["destination_latitude"],
                            longitude=row["destination_longitude"],
                        ),
                        vessel=Vessel(speed_knots=row["speed_knots"]),
                        waypoints=waypoints,
                        arrival_threshold_nm=row["arrival_threshold_nm"],
                        status=row["status"],
                        track_points=dummy_track_points,
                        distance_travelled_km=row["distance_travelled_km"],
                        start_timestamp=start_ts,
                        last_timestamp=last_ts,
                        completed_at=completed_ts,
                        return_mode=row["return_mode"],
                        return_status=row["return_status"],
                    )
                )

            return trips, total

    def get_track_points(self, trip_id: str) -> List[TripTrackPoint]:
        """Fetch ordered track points for a trip."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM track_points WHERE trip_id = ? ORDER BY sequence_number ASC",
                (trip_id,),
            )
            rows = cur.fetchall()
            return [
                TripTrackPoint(
                    latitude=r["latitude"],
                    longitude=r["longitude"],
                    timestamp=parse_iso_datetime(r["timestamp"]) or datetime.now(timezone.utc),
                    sequence_number=r["sequence_number"],
                )
                for r in rows
            ]

    def delete(self, trip_id: str) -> bool:
        """Delete a trip from the database (foreign key cascade handles track points)."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM trips WHERE trip_id = ?", (trip_id,))
            return cur.rowcount > 0

    def clear(self) -> None:
        """Clear all trips and track points."""
        with get_db_connection(self.db_path) as conn:
            conn.execute("DELETE FROM track_points;")
            conn.execute("DELETE FROM trips;")


class InMemoryTripRepository(TripRepository):
    """In-memory dictionary-backed implementation of TripRepository for fast unit testing."""

    def __init__(self) -> None:
        """Initialize empty in-memory trip storage."""
        self._storage: Dict[str, TripRecord] = {}

    def save(self, trip: TripRecord) -> TripRecord:
        """Store or update the trip record in memory."""
        for idx, tp in enumerate(trip.track_points):
            tp.sequence_number = idx
        self._storage[trip.trip_id] = trip
        return trip

    def get_by_id(self, trip_id: str) -> Optional[TripRecord]:
        """Look up a trip record by its unique identifier."""
        return self._storage.get(trip_id)

    def list_trips(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[TripRecord], int]:
        """List trips in memory with optional status filter and pagination."""
        all_trips = list(self._storage.values())
        if status:
            all_trips = [t for t in all_trips if t.status == status]
        all_trips.sort(key=lambda t: t.start_timestamp, reverse=True)
        total = len(all_trips)
        paginated = all_trips[offset : offset + limit]
        return paginated, total

    def get_track_points(self, trip_id: str) -> List[TripTrackPoint]:
        """Retrieve track points of a trip in memory."""
        trip = self._storage.get(trip_id)
        if trip is None:
            return []
        return trip.track_points

    def delete(self, trip_id: str) -> bool:
        """Delete a trip from in-memory storage."""
        if trip_id in self._storage:
            del self._storage[trip_id]
            return True
        return False

    def clear(self) -> None:
        """Reset internal in-memory trip storage."""
        self._storage.clear()


# Default singleton provider using SQLiteTripRepository
_default_sqlite_repo: Optional[SQLiteTripRepository] = None


def get_default_trip_repository() -> TripRepository:
    """Retrieve default persistent SQLite repository instance."""
    global _default_sqlite_repo
    if _default_sqlite_repo is None:
        _default_sqlite_repo = SQLiteTripRepository()
    return _default_sqlite_repo
