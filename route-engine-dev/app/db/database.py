"""SQLite database connection, schema initialization, and safe schema migrations for ORCA Route Engine."""

from contextlib import contextmanager
import os
import sqlite3
from typing import Generator, Optional
from app.core.config import get_settings


def get_configured_db_path() -> str:
    """Retrieve database path from settings."""
    settings = get_settings()
    return getattr(settings, "ORCA_ROUTE_DB_PATH", "data/orca_routes.db")


def ensure_db_directory(db_path: str) -> None:
    """Ensure parent directory for database file exists."""
    dir_path = os.path.dirname(os.path.abspath(db_path))
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


@contextmanager
def get_db_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager providing a transactional, short-lived SQLite database connection.

    Args:
        db_path: Optional database file path. Defaults to configured ORCA_ROUTE_DB_PATH.

    Yields:
        sqlite3.Connection with Row factory and Foreign Keys enabled.
    """
    path = db_path or get_configured_db_path()
    ensure_db_directory(path)

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables, indexes, and apply safe non-destructive schema migrations.

    Args:
        db_path: Optional database file path. Defaults to configured ORCA_ROUTE_DB_PATH.
    """
    path = db_path or get_configured_db_path()
    ensure_db_directory(path)

    with get_db_connection(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trips (
                trip_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                start_latitude REAL NOT NULL,
                start_longitude REAL NOT NULL,
                destination_latitude REAL NOT NULL,
                destination_longitude REAL NOT NULL,
                speed_knots REAL NOT NULL,
                waypoints_json TEXT NOT NULL DEFAULT '[]',
                arrival_threshold_nm REAL NOT NULL DEFAULT 0.1,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                current_latitude REAL NOT NULL,
                current_longitude REAL NOT NULL,
                distance_travelled_km REAL NOT NULL DEFAULT 0.0,
                distance_travelled_nm REAL NOT NULL DEFAULT 0.0,
                elapsed_time_minutes REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                return_mode TEXT,
                return_destination_latitude REAL,
                return_destination_longitude REAL,
                return_status TEXT,
                return_started_at TEXT,
                return_completed_at TEXT,
                return_origin_latitude REAL,
                return_origin_longitude REAL
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS track_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                timestamp TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips(trip_id) ON DELETE CASCADE
            );
            """
        )

        # Migration: Ensure return columns exist on existing databases
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(trips);")
        existing_cols = {row["name"] for row in cur.fetchall()}

        return_columns = [
            ("return_mode", "TEXT"),
            ("return_destination_latitude", "REAL"),
            ("return_destination_longitude", "REAL"),
            ("return_status", "TEXT"),
            ("return_started_at", "TEXT"),
            ("return_completed_at", "TEXT"),
            ("return_origin_latitude", "REAL"),
            ("return_origin_longitude", "REAL"),
        ]

        for col_name, col_type in return_columns:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE trips ADD COLUMN {col_name} {col_type};")

        # Create indexes for optimal lookup and sequencing
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_started_at ON trips(started_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_return_status ON trips(return_status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_track_points_trip_id ON track_points(trip_id);")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_track_points_trip_seq ON track_points(trip_id, sequence_number);"
        )

        # Geographic Datasets & Features Tables (Step 10 Persistence)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geo_datasets (
                dataset_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                feature_type TEXT NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT,
                version TEXT NOT NULL,
                updated_at TEXT,
                feature_count INTEGER NOT NULL DEFAULT 0,
                min_latitude REAL,
                min_longitude REAL,
                max_latitude REAL,
                max_longitude REAL,
                created_at TEXT NOT NULL
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geo_features (
                feature_id TEXT PRIMARY KEY,
                dataset_id TEXT,
                feature_type TEXT NOT NULL,
                name TEXT,
                geometry_type TEXT NOT NULL,
                geometry_json TEXT NOT NULL,
                properties_json TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL,
                source_updated_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (dataset_id) REFERENCES geo_datasets(dataset_id) ON DELETE SET NULL
            );
            """
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_geo_features_type ON geo_features(feature_type);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_geo_features_dataset ON geo_features(dataset_id);"
        )

        # PFZ (Potential Fishing Zone) Tables (Step 13 Persistence)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pfz_zones (
                pfz_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL DEFAULT 'india_pfz',
                name TEXT,
                geometry_type TEXT NOT NULL,
                geometry_json TEXT NOT NULL,
                centroid_latitude REAL,
                centroid_longitude REAL,
                confidence REAL,
                suitability_score REAL,
                valid_from TEXT,
                valid_until TEXT,
                properties_json TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT 'INCOIS',
                source_url TEXT,
                source_updated_at TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pfz_observations (
                observation_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                fish_potential_score REAL,
                confidence REAL,
                species TEXT,
                sst_celsius REAL,
                chlorophyll_mg_m3 REAL,
                source TEXT NOT NULL DEFAULT 'INCOIS',
                model_version TEXT,
                properties_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_pfz_zones_confidence ON pfz_zones(confidence);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pfz_zones_suitability ON pfz_zones(suitability_score);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pfz_zones_valid_until ON pfz_zones(valid_until);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pfz_observations_time ON pfz_observations(timestamp);")

        # Ensure default India marine dataset metadata records exist
        now_str = "2026-09-12T00:00:00+00:00"
        default_datasets = [
            (
                "india_coastline",
                "India Coastline Boundary",
                "coastline",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_marine_area",
                "India Marine & Coastal Areas",
                "marine_area",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_eez",
                "India Exclusive Economic Zone (EEZ)",
                "eez",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_ports",
                "India Major & Minor Ports",
                "port",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_harbours",
                "India Fishing Harbours",
                "harbour",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_landing_centres",
                "India Fish Landing Centres",
                "landing_centre",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_lighthouses",
                "India Coastal Lighthouses & Beacons",
                "lighthouse",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_bathymetry",
                "India Coastal Bathymetry & Depth Contours",
                "bathymetry",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_restricted_areas",
                "India Marine Protected & Restricted Navigation Areas",
                "restricted_area",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
            (
                "india_pfz",
                "India Potential Fishing Zones (INCOIS Advisory)",
                "pfz",
                "pending",
                "https://incois.gov.in/geoportal/MFASPFZ/index.html",
                "pending",
                now_str,
                0,
                now_str,
            ),
        ]

        for ds_row in default_datasets:
            conn.execute(
                """
                INSERT OR IGNORE INTO geo_datasets (
                    dataset_id, name, feature_type, source, source_url,
                    version, updated_at, feature_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ds_row,
            )
