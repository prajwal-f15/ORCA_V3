"""PFZ repository interface, SQLite persistent implementation, and InMemory implementation."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from app.db.database import get_db_connection, init_db
from app.models.geography import GeoGeometry, GeometryType
from app.models.pfz import (
    PFZDatasetStatus,
    PFZFreshness,
    PFZObservation,
    PFZStatus,
    PFZZone,
)
from app.models.request import Coordinate


class DuplicatePFZZoneError(Exception):
    """Raised when attempting to save a PFZ zone with an existing pfz_id."""

    pass


class PFZRepository(ABC):
    """Abstract repository interface for Potential Fishing Zone persistence."""

    @abstractmethod
    def save_zone(self, zone: PFZZone) -> PFZZone:
        """Save or update a PFZ zone domain entity."""
        pass

    @abstractmethod
    def get_zone(self, pfz_id: str) -> Optional[PFZZone]:
        """Retrieve a single PFZ zone by its unique identifier."""
        pass

    @abstractmethod
    def list_zones(
        self,
        limit: int = 50,
        offset: int = 0,
        min_confidence: Optional[float] = None,
        valid_only: bool = False,
    ) -> Tuple[List[PFZZone], int]:
        """List registered PFZ zones with optional confidence filtering and pagination."""
        pass

    @abstractmethod
    def delete_zone(self, pfz_id: str) -> bool:
        """Delete a PFZ zone by identifier."""
        pass

    @abstractmethod
    def count_zones(self) -> int:
        """Count total registered PFZ zones."""
        pass

    @abstractmethod
    def save_observation(self, observation: PFZObservation) -> PFZObservation:
        """Save an oceanographic prediction observation."""
        pass

    @abstractmethod
    def get_observations(
        self, limit: int = 100, offset: int = 0
    ) -> List[PFZObservation]:
        """List oceanographic prediction observations."""
        pass

    @abstractmethod
    def get_status(self) -> PFZStatus:
        """Query operational dataset status and freshness."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Reset repository contents."""
        pass


class SQLitePFZRepository(PFZRepository):
    """Persistent SQLite implementation for PFZ zones and prediction observations."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize SQLite repository with database path."""
        self.db_path = db_path
        init_db(self.db_path)

    def save_zone(self, zone: PFZZone) -> PFZZone:
        """Insert or update a PFZ zone record in SQLite."""
        now_str = datetime.now(timezone.utc).isoformat()
        src_upd = (
            zone.source_updated_at.isoformat()
            if zone.source_updated_at
            else now_str
        )
        val_from = zone.valid_from.isoformat() if zone.valid_from else None
        val_until = zone.valid_until.isoformat() if zone.valid_until else None

        geom_json = json.dumps(
            {"type": zone.geometry.type.value, "coordinates": zone.geometry.coordinates}
        )
        props_json = json.dumps(zone.properties or {})

        cent_lat = zone.centroid.latitude if zone.centroid else None
        cent_lon = zone.centroid.longitude if zone.centroid else None

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pfz_zones (
                    pfz_id, dataset_id, name, geometry_type, geometry_json,
                    centroid_latitude, centroid_longitude, confidence, suitability_score,
                    valid_from, valid_until, properties_json, source, source_url,
                    source_updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pfz_id) DO UPDATE SET
                    name = excluded.name,
                    geometry_type = excluded.geometry_type,
                    geometry_json = excluded.geometry_json,
                    centroid_latitude = excluded.centroid_latitude,
                    centroid_longitude = excluded.centroid_longitude,
                    confidence = excluded.confidence,
                    suitability_score = excluded.suitability_score,
                    valid_from = excluded.valid_from,
                    valid_until = excluded.valid_until,
                    properties_json = excluded.properties_json,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    source_updated_at = excluded.source_updated_at
                """,
                (
                    zone.pfz_id,
                    zone.dataset_id or "india_pfz",
                    zone.name,
                    zone.geometry_type or zone.geometry.type.value,
                    geom_json,
                    cent_lat,
                    cent_lon,
                    zone.confidence,
                    zone.suitability_score,
                    val_from,
                    val_until,
                    props_json,
                    zone.source,
                    zone.source_url,
                    src_upd,
                    now_str,
                ),
            )

            # Update feature count in geo_datasets tracking table
            cur.execute(
                """
                UPDATE geo_datasets
                SET feature_count = (SELECT COUNT(*) FROM pfz_zones),
                    updated_at = ?
                WHERE dataset_id = 'india_pfz'
                """,
                (now_str,),
            )

        return zone

    def get_zone(self, pfz_id: str) -> Optional[PFZZone]:
        """Retrieve single PFZ zone by ID from SQLite."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pfz_zones WHERE pfz_id = ?", (pfz_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_zone(row)

    def list_zones(
        self,
        limit: int = 50,
        offset: int = 0,
        min_confidence: Optional[float] = None,
        valid_only: bool = False,
    ) -> Tuple[List[PFZZone], int]:
        """List PFZ zones from SQLite with optional confidence and validity filters."""
        query = "SELECT * FROM pfz_zones WHERE 1=1"
        count_query = "SELECT COUNT(*) as cnt FROM pfz_zones WHERE 1=1"
        params: List[Any] = []

        if min_confidence is not None:
            query += " AND confidence >= ?"
            count_query += " AND confidence >= ?"
            params.append(min_confidence)

        if valid_only:
            now_iso = datetime.now(timezone.utc).isoformat()
            query += " AND (valid_until IS NULL OR valid_until >= ?)"
            count_query += " AND (valid_until IS NULL OR valid_until >= ?)"
            params.append(now_iso)

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(count_query, params)
            total = cur.fetchone()["cnt"]

            query += " ORDER BY suitability_score DESC NULLS LAST, confidence DESC NULLS LAST LIMIT ? OFFSET ?"
            query_params = list(params) + [limit, offset]
            cur.execute(query, query_params)
            rows = cur.fetchall()

            zones = [self._row_to_zone(r) for r in rows]
            return zones, total

    def delete_zone(self, pfz_id: str) -> bool:
        """Delete PFZ zone by ID."""
        now_str = datetime.now(timezone.utc).isoformat()
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM pfz_zones WHERE pfz_id = ?", (pfz_id,))
            deleted = cur.rowcount > 0
            if deleted:
                cur.execute(
                    """
                    UPDATE geo_datasets
                    SET feature_count = (SELECT COUNT(*) FROM pfz_zones),
                        updated_at = ?
                    WHERE dataset_id = 'india_pfz'
                    """,
                    (now_str,),
                )
            return deleted

    def count_zones(self) -> int:
        """Count total PFZ zones."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM pfz_zones")
            return cur.fetchone()["cnt"]

    def save_observation(self, observation: PFZObservation) -> PFZObservation:
        """Persist a single prediction observation."""
        now_str = datetime.now(timezone.utc).isoformat()
        ts_str = observation.timestamp.isoformat()
        props_json = json.dumps(observation.properties or {})

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pfz_observations (
                    observation_id, timestamp, latitude, longitude,
                    fish_potential_score, confidence, species, sst_celsius,
                    chlorophyll_mg_m3, source, model_version, properties_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    fish_potential_score = excluded.fish_potential_score,
                    confidence = excluded.confidence,
                    species = excluded.species,
                    sst_celsius = excluded.sst_celsius,
                    chlorophyll_mg_m3 = excluded.chlorophyll_mg_m3,
                    source = excluded.source,
                    model_version = excluded.model_version,
                    properties_json = excluded.properties_json
                """,
                (
                    observation.observation_id,
                    ts_str,
                    observation.latitude,
                    observation.longitude,
                    observation.fish_potential_score,
                    observation.confidence,
                    observation.species,
                    observation.sst_celsius,
                    observation.chlorophyll_mg_m3,
                    observation.source,
                    observation.model_version,
                    props_json,
                    now_str,
                ),
            )
        return observation

    def get_observations(
        self, limit: int = 100, offset: int = 0
    ) -> List[PFZObservation]:
        """Retrieve recent prediction observations."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM pfz_observations ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = cur.fetchall()
            return [self._row_to_observation(r) for r in rows]

    def get_status(self) -> PFZStatus:
        """Determine dataset status and advisory freshness."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt, MAX(source_updated_at) as last_upd FROM pfz_zones")
            row = cur.fetchone()
            count = row["cnt"]
            last_upd_str = row["last_upd"]

        if count == 0:
            return PFZStatus(
                source="INCOIS",
                source_url="https://incois.gov.in/geoportal/MFASPFZ/index.html",
                last_updated=None,
                freshness=PFZFreshness.PENDING,
                dataset_status=PFZDatasetStatus.PENDING,
                feature_count=0,
                model_version="INCOIS-PFZ-v3",
                message="PFZ advisory data: Pending official dataset ingestion from INCOIS",
            )

        last_upd = None
        if last_upd_str:
            try:
                last_upd = datetime.fromisoformat(last_upd_str)
            except Exception:
                pass

        now_utc = datetime.now(timezone.utc)
        # Check if last update was within 48 hours
        is_fresh = last_upd is not None and (now_utc - last_upd).total_seconds() < 172800

        return PFZStatus(
            source="INCOIS",
            source_url="https://incois.gov.in/geoportal/MFASPFZ/index.html",
            last_updated=last_upd,
            freshness=PFZFreshness.FRESH if is_fresh else PFZFreshness.STALE,
            dataset_status=PFZDatasetStatus.AVAILABLE,
            feature_count=count,
            model_version="INCOIS-PFZ-v3",
            message=f"INCOIS PFZ advisory available: {count} zone(s) registered",
        )

    def clear(self) -> None:
        """Clear all PFZ zones and observations."""
        with get_db_connection(self.db_path) as conn:
            conn.execute("DELETE FROM pfz_zones;")
            conn.execute("DELETE FROM pfz_observations;")
            conn.execute(
                "UPDATE geo_datasets SET feature_count = 0 WHERE dataset_id = 'india_pfz';"
            )

    @staticmethod
    def _row_to_zone(row: sqlite3.Row) -> PFZZone:
        """Deserialize a SQLite pfz_zones row to a PFZZone domain entity."""
        geom_data = json.loads(row["geometry_json"])
        props_data = json.loads(row["properties_json"] or "{}")

        upd_at = None
        if row["source_updated_at"]:
            try:
                upd_at = datetime.fromisoformat(row["source_updated_at"])
            except Exception:
                pass

        val_from = None
        if row["valid_from"]:
            try:
                val_from = datetime.fromisoformat(row["valid_from"])
            except Exception:
                pass

        val_until = None
        if row["valid_until"]:
            try:
                val_until = datetime.fromisoformat(row["valid_until"])
            except Exception:
                pass

        centroid = None
        if row["centroid_latitude"] is not None and row["centroid_longitude"] is not None:
            centroid = Coordinate(
                latitude=row["centroid_latitude"],
                longitude=row["centroid_longitude"],
            )

        return PFZZone(
            pfz_id=row["pfz_id"],
            dataset_id=row["dataset_id"],
            name=row["name"],
            geometry_type=row["geometry_type"],
            geometry=GeoGeometry(
                type=GeometryType(geom_data["type"]),
                coordinates=geom_data["coordinates"],
            ),
            centroid=centroid,
            confidence=row["confidence"],
            suitability_score=row["suitability_score"],
            valid_from=val_from,
            valid_until=val_until,
            properties=props_data,
            source=row["source"],
            source_url=row["source_url"],
            source_updated_at=upd_at,
        )

    @staticmethod
    def _row_to_observation(row: sqlite3.Row) -> PFZObservation:
        """Deserialize a SQLite pfz_observations row to a PFZObservation domain entity."""
        props_data = json.loads(row["properties_json"] or "{}")
        ts = datetime.fromisoformat(row["timestamp"])

        return PFZObservation(
            observation_id=row["observation_id"],
            timestamp=ts,
            latitude=row["latitude"],
            longitude=row["longitude"],
            fish_potential_score=row["fish_potential_score"],
            confidence=row["confidence"],
            species=row["species"],
            sst_celsius=row["sst_celsius"],
            chlorophyll_mg_m3=row["chlorophyll_mg_m3"],
            source=row["source"],
            model_version=row["model_version"],
            properties=props_data,
        )


class InMemoryPFZRepository(PFZRepository):
    """Isolated In-Memory implementation for unit and regression testing."""

    def __init__(self) -> None:
        """Initialize empty in-memory dictionaries."""
        self._zones: Dict[str, PFZZone] = {}
        self._observations: Dict[str, PFZObservation] = {}

    def save_zone(self, zone: PFZZone) -> PFZZone:
        self._zones[zone.pfz_id] = zone
        return zone

    def get_zone(self, pfz_id: str) -> Optional[PFZZone]:
        return self._zones.get(pfz_id)

    def list_zones(
        self,
        limit: int = 50,
        offset: int = 0,
        min_confidence: Optional[float] = None,
        valid_only: bool = False,
    ) -> Tuple[List[PFZZone], int]:
        items = list(self._zones.values())
        if min_confidence is not None:
            items = [z for z in items if z.confidence is not None and z.confidence >= min_confidence]
        if valid_only:
            now_utc = datetime.now(timezone.utc)
            items = [z for z in items if z.valid_until is None or z.valid_until >= now_utc]

        # Sort by suitability score desc, then confidence desc
        items.sort(
            key=lambda z: (z.suitability_score or 0.0, z.confidence or 0.0), reverse=True
        )
        total = len(items)
        return items[offset : offset + limit], total

    def delete_zone(self, pfz_id: str) -> bool:
        return bool(self._zones.pop(pfz_id, None))

    def count_zones(self) -> int:
        return len(self._zones)

    def save_observation(self, observation: PFZObservation) -> PFZObservation:
        self._observations[observation.observation_id] = observation
        return observation

    def get_observations(
        self, limit: int = 100, offset: int = 0
    ) -> List[PFZObservation]:
        items = list(self._observations.values())
        items.sort(key=lambda o: o.timestamp, reverse=True)
        return items[offset : offset + limit]

    def get_status(self) -> PFZStatus:
        count = len(self._zones)
        if count == 0:
            return PFZStatus(
                source="INCOIS",
                source_url="https://incois.gov.in/geoportal/MFASPFZ/index.html",
                last_updated=None,
                freshness=PFZFreshness.PENDING,
                dataset_status=PFZDatasetStatus.PENDING,
                feature_count=0,
                model_version="INCOIS-PFZ-v3",
                message="PFZ advisory data: Pending official dataset ingestion from INCOIS",
            )
        return PFZStatus(
            source="INCOIS",
            source_url="https://incois.gov.in/geoportal/MFASPFZ/index.html",
            last_updated=datetime.now(timezone.utc),
            freshness=PFZFreshness.FRESH,
            dataset_status=PFZDatasetStatus.AVAILABLE,
            feature_count=count,
            model_version="INCOIS-PFZ-v3",
            message=f"INCOIS PFZ advisory available: {count} zone(s) registered",
        )

    def clear(self) -> None:
        self._zones.clear()
        self._observations.clear()


# Default singleton instance provider
_default_pfz_repo: Optional[PFZRepository] = None


def get_default_pfz_repository() -> PFZRepository:
    """Retrieve default persistent SQLite PFZ repository instance."""
    global _default_pfz_repo
    if _default_pfz_repo is None:
        _default_pfz_repo = SQLitePFZRepository()
    return _default_pfz_repo
