"""Geography repository interface, SQLite persistent implementation, and In-Memory implementation."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from app.db.database import get_db_connection, init_db
from app.models.geography import (
    GeoBoundingBox,
    GeoDataset,
    GeoDatasetMetadata,
    GeoFeature,
    GeoFeatureType,
    GeoGeometry,
    GeometryType,
)


class DuplicateFeatureError(Exception):
    """Raised when attempting to add a feature with an existing feature_id."""

    pass


class GeographyRepository(ABC):
    """Abstract repository interface for geographic datasets and spatial features."""

    @abstractmethod
    def add_feature(self, feature: GeoFeature) -> GeoFeature:
        """Add a geographic feature to the repository.

        Args:
            feature: GeoFeature domain entity.

        Returns:
            The saved GeoFeature.

        Raises:
            DuplicateFeatureError: If feature_id already exists.
        """
        pass

    @abstractmethod
    def get_feature(self, feature_id: str) -> Optional[GeoFeature]:
        """Retrieve a geographic feature by its unique identifier.

        Args:
            feature_id: Unique string identifier.

        Returns:
            GeoFeature if found, None otherwise.
        """
        pass

    @abstractmethod
    def list_features(
        self,
        feature_type: Optional[GeoFeatureType] = None,
        dataset_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[GeoFeature], int]:
        """List geographic features with optional category/dataset filter and pagination.

        Args:
            feature_type: Optional filter by GeoFeatureType.
            dataset_id: Optional filter by dataset_id.
            limit: Maximum items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (list of GeoFeature items, total count matching filter).
        """
        pass

    @abstractmethod
    def delete_feature(self, feature_id: str) -> bool:
        """Delete a geographic feature from the repository.

        Args:
            feature_id: Unique identifier of feature to delete.

        Returns:
            True if deleted, False if feature was not found.
        """
        pass

    @abstractmethod
    def count_features(
        self,
        feature_type: Optional[GeoFeatureType] = None,
        dataset_id: Optional[str] = None,
    ) -> int:
        """Count total geographic features registered, optionally filtered.

        Args:
            feature_type: Optional filter by GeoFeatureType.
            dataset_id: Optional filter by dataset_id.

        Returns:
            Integer total count.
        """
        pass

    @abstractmethod
    def register_dataset(self, dataset: GeoDataset) -> GeoDataset:
        """Register or update geographic dataset metadata descriptor.

        Args:
            dataset: GeoDataset domain entity.

        Returns:
            Registered GeoDataset.
        """
        pass

    def upsert_dataset(self, dataset: GeoDataset) -> GeoDataset:
        """Upsert dataset descriptor (alias to register_dataset)."""
        return self.register_dataset(dataset)

    @abstractmethod
    def get_dataset(self, dataset_id: str) -> Optional[GeoDataset]:
        """Retrieve full dataset entity by ID.

        Args:
            dataset_id: Dataset identifier.

        Returns:
            GeoDataset if found, None otherwise.
        """
        pass

    @abstractmethod
    def get_dataset_metadata(
        self, dataset_id: Optional[str] = None
    ) -> List[GeoDatasetMetadata]:
        """Retrieve dataset metadata descriptors.

        Args:
            dataset_id: Optional single dataset ID filter.

        Returns:
            List of GeoDatasetMetadata descriptors.
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """Reset repository state."""
        pass


class SQLiteGeographyRepository(GeographyRepository):
    """Production SQLite-backed persistent repository for geographic datasets and spatial features."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize SQLiteGeographyRepository with target database file.

        Args:
            db_path: Path to SQLite database file. Defaults to configured DB path.
        """
        self.db_path = db_path
        init_db(self.db_path)

    def add_feature(self, feature: GeoFeature) -> GeoFeature:
        """Persist a geographic feature in SQLite with unique ID constraint."""
        now_str = datetime.now(timezone.utc).isoformat()
        src_upd = (
            feature.source_updated_at.isoformat()
            if feature.source_updated_at
            else now_str
        )
        geom_json = json.dumps(
            {"type": feature.geometry.type.value, "coordinates": feature.geometry.coordinates}
        )
        props_json = json.dumps(feature.properties or {})

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT feature_id FROM geo_features WHERE feature_id = ?", (feature.feature_id,))
            if cur.fetchone() is not None:
                raise DuplicateFeatureError(
                    f"Feature with ID '{feature.feature_id}' already exists in database."
                )

            cur.execute(
                """
                INSERT INTO geo_features (
                    feature_id, dataset_id, feature_type, name, geometry_type,
                    geometry_json, properties_json, source, source_updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feature.feature_id,
                    feature.dataset_id,
                    feature.feature_type.value,
                    feature.name,
                    feature.geometry_type,
                    geom_json,
                    props_json,
                    feature.source,
                    src_upd,
                    now_str,
                ),
            )

            # Synchronize feature_count in dataset record if dataset_id attached
            if feature.dataset_id:
                cur.execute(
                    """
                    UPDATE geo_datasets
                    SET feature_count = (
                        SELECT COUNT(*) FROM geo_features WHERE dataset_id = ?
                    ),
                    updated_at = ?
                    WHERE dataset_id = ?
                    """,
                    (feature.dataset_id, now_str, feature.dataset_id),
                )

        return feature

    def get_feature(self, feature_id: str) -> Optional[GeoFeature]:
        """Retrieve a geographic feature from SQLite by ID."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM geo_features WHERE feature_id = ?", (feature_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_feature(row)

    def list_features(
        self,
        feature_type: Optional[GeoFeatureType] = None,
        dataset_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[GeoFeature], int]:
        """List geographic features from SQLite with optional filters and pagination."""
        query = "SELECT * FROM geo_features WHERE 1=1"
        count_query = "SELECT COUNT(*) as cnt FROM geo_features WHERE 1=1"
        params: List[Any] = []

        if feature_type is not None:
            type_val = (
                feature_type.value
                if isinstance(feature_type, GeoFeatureType)
                else str(feature_type)
            )
            query += " AND feature_type = ?"
            count_query += " AND feature_type = ?"
            params.append(type_val)

        if dataset_id is not None:
            query += " AND dataset_id = ?"
            count_query += " AND dataset_id = ?"
            params.append(dataset_id)

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(count_query, params)
            total = cur.fetchone()["cnt"]

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            query_params = list(params) + [limit, offset]
            cur.execute(query, query_params)
            rows = cur.fetchall()

            features = [self._row_to_feature(r) for r in rows]
            return features, total

    def delete_feature(self, feature_id: str) -> bool:
        """Delete a feature by ID and update associated dataset feature count."""
        now_str = datetime.now(timezone.utc).isoformat()
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT dataset_id FROM geo_features WHERE feature_id = ?", (feature_id,))
            row = cur.fetchone()
            if row is None:
                return False

            ds_id = row["dataset_id"]
            cur.execute("DELETE FROM geo_features WHERE feature_id = ?", (feature_id,))
            deleted = cur.rowcount > 0

            if deleted and ds_id:
                cur.execute(
                    """
                    UPDATE geo_datasets
                    SET feature_count = (
                        SELECT COUNT(*) FROM geo_features WHERE dataset_id = ?
                    ),
                    updated_at = ?
                    WHERE dataset_id = ?
                    """,
                    (ds_id, now_str, ds_id),
                )
            return deleted

    def count_features(
        self,
        feature_type: Optional[GeoFeatureType] = None,
        dataset_id: Optional[str] = None,
    ) -> int:
        """Count features in SQLite matching optional criteria."""
        query = "SELECT COUNT(*) as cnt FROM geo_features WHERE 1=1"
        params: List[Any] = []
        if feature_type is not None:
            type_val = (
                feature_type.value
                if isinstance(feature_type, GeoFeatureType)
                else str(feature_type)
            )
            query += " AND feature_type = ?"
            params.append(type_val)
        if dataset_id is not None:
            query += " AND dataset_id = ?"
            params.append(dataset_id)

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            return cur.fetchone()["cnt"]

    def register_dataset(self, dataset: GeoDataset) -> GeoDataset:
        """Insert or update a dataset record in SQLite."""
        now_str = datetime.now(timezone.utc).isoformat()
        upd_str = dataset.updated_at.isoformat() if dataset.updated_at else now_str

        min_lat = dataset.bounding_box.min_latitude if dataset.bounding_box else None
        min_lon = dataset.bounding_box.min_longitude if dataset.bounding_box else None
        max_lat = dataset.bounding_box.max_latitude if dataset.bounding_box else None
        max_lon = dataset.bounding_box.max_longitude if dataset.bounding_box else None

        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO geo_datasets (
                    dataset_id, name, feature_type, source, source_url, version,
                    updated_at, feature_count, min_latitude, min_longitude,
                    max_latitude, max_longitude, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    name = excluded.name,
                    feature_type = excluded.feature_type,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    version = excluded.version,
                    updated_at = excluded.updated_at,
                    feature_count = excluded.feature_count,
                    min_latitude = excluded.min_latitude,
                    min_longitude = excluded.min_longitude,
                    max_latitude = excluded.max_latitude,
                    max_longitude = excluded.max_longitude
                """,
                (
                    dataset.dataset_id,
                    dataset.name,
                    dataset.feature_type.value,
                    dataset.source,
                    dataset.source_url,
                    dataset.version,
                    upd_str,
                    dataset.feature_count,
                    min_lat,
                    min_lon,
                    max_lat,
                    max_lon,
                    now_str,
                ),
            )
        return dataset

    def get_dataset(self, dataset_id: str) -> Optional[GeoDataset]:
        """Retrieve a full GeoDataset entity from SQLite."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM geo_datasets WHERE dataset_id = ?", (dataset_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_dataset(row)

    def get_dataset_metadata(
        self, dataset_id: Optional[str] = None
    ) -> List[GeoDatasetMetadata]:
        """Retrieve dataset metadata descriptors from SQLite."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            if dataset_id:
                cur.execute("SELECT * FROM geo_datasets WHERE dataset_id = ?", (dataset_id,))
            else:
                cur.execute("SELECT * FROM geo_datasets ORDER BY dataset_id ASC")
            rows = cur.fetchall()
            return [self._row_to_metadata(r) for r in rows]

    def clear(self) -> None:
        """Clear all feature records and reseed default dataset descriptors."""
        with get_db_connection(self.db_path) as conn:
            conn.execute("DELETE FROM geo_features;")
            conn.execute("DELETE FROM geo_datasets;")
        init_db(self.db_path)

    @staticmethod
    def _row_to_feature(row: sqlite3.Row) -> GeoFeature:
        """Convert a SQLite geo_features row into a GeoFeature domain model."""
        geom_data = json.loads(row["geometry_json"])
        props_data = json.loads(row["properties_json"] or "{}")

        upd_at = None
        if row["source_updated_at"]:
            try:
                upd_at = datetime.fromisoformat(row["source_updated_at"])
            except Exception:
                pass

        return GeoFeature(
            feature_id=row["feature_id"],
            dataset_id=row["dataset_id"],
            feature_type=GeoFeatureType(row["feature_type"]),
            name=row["name"],
            geometry_type=row["geometry_type"],
            geometry=GeoGeometry(
                type=GeometryType(geom_data["type"]),
                coordinates=geom_data["coordinates"],
            ),
            properties=props_data,
            source=row["source"],
            source_updated_at=upd_at,
        )

    @staticmethod
    def _row_to_dataset(row: sqlite3.Row) -> GeoDataset:
        """Convert a SQLite geo_datasets row into a GeoDataset domain model."""
        upd_at = None
        if row["updated_at"]:
            try:
                upd_at = datetime.fromisoformat(row["updated_at"])
            except Exception:
                pass

        bbox = None
        if (
            row["min_latitude"] is not None
            and row["min_longitude"] is not None
            and row["max_latitude"] is not None
            and row["max_longitude"] is not None
        ):
            bbox = GeoBoundingBox(
                min_latitude=row["min_latitude"],
                min_longitude=row["min_longitude"],
                max_latitude=row["max_latitude"],
                max_longitude=row["max_longitude"],
            )

        return GeoDataset(
            dataset_id=row["dataset_id"],
            name=row["name"],
            feature_type=GeoFeatureType(row["feature_type"]),
            source=row["source"],
            source_url=row["source_url"],
            version=row["version"],
            updated_at=upd_at,
            feature_count=row["feature_count"],
            bounding_box=bbox,
        )

    @staticmethod
    def _row_to_metadata(row: sqlite3.Row) -> GeoDatasetMetadata:
        """Convert a SQLite geo_datasets row into a GeoDatasetMetadata DTO."""
        upd_at = None
        if row["updated_at"]:
            try:
                upd_at = datetime.fromisoformat(row["updated_at"])
            except Exception:
                pass

        bbox = None
        if (
            row["min_latitude"] is not None
            and row["min_longitude"] is not None
            and row["max_latitude"] is not None
            and row["max_longitude"] is not None
        ):
            bbox = GeoBoundingBox(
                min_latitude=row["min_latitude"],
                min_longitude=row["min_longitude"],
                max_latitude=row["max_latitude"],
                max_longitude=row["max_longitude"],
            )

        return GeoDatasetMetadata(
            dataset_id=row["dataset_id"],
            name=row["name"],
            feature_type=row["feature_type"],
            source=row["source"],
            source_url=row["source_url"],
            version=row["version"],
            updated_at=upd_at,
            feature_count=row["feature_count"],
            bounding_box=bbox,
        )


class InMemoryGeographyRepository(GeographyRepository):
    """In-memory dictionary-backed implementation of GeographyRepository for isolated testing."""

    def __init__(self) -> None:
        """Initialize empty in-memory spatial storage and register default dataset placeholders."""
        self._features: Dict[str, GeoFeature] = {}
        self._datasets: Dict[str, GeoDataset] = {}
        self._initialize_default_datasets()

    def _initialize_default_datasets(self) -> None:
        """Seed initial dataset metadata placeholders for India Marine geographic categories."""
        default_definitions = [
            ("india_coastline", "India Coastline Boundary", GeoFeatureType.COASTLINE),
            ("india_marine_area", "India Marine & Coastal Areas", GeoFeatureType.MARINE_AREA),
            ("india_eez", "India Exclusive Economic Zone (EEZ)", GeoFeatureType.EEZ),
            ("india_ports", "India Major & Minor Ports", GeoFeatureType.PORT),
            ("india_harbours", "India Fishing Harbours", GeoFeatureType.HARBOUR),
            ("india_landing_centres", "India Fish Landing Centres", GeoFeatureType.LANDING_CENTRE),
            ("india_lighthouses", "India Coastal Lighthouses & Beacons", GeoFeatureType.LIGHTHOUSE),
            ("india_bathymetry", "India Coastal Bathymetry & Depth Contours", GeoFeatureType.BATHYMETRY),
        ]

        now = datetime.now(timezone.utc)
        for dataset_id, name, feat_type in default_definitions:
            self._datasets[dataset_id] = GeoDataset(
                dataset_id=dataset_id,
                name=name,
                feature_type=feat_type,
                source="pending",
                source_url="https://incois.gov.in/geoportal/MFASPFZ/index.html",
                version="pending",
                updated_at=now,
                feature_count=0,
                bounding_box=None,
            )

    def add_feature(self, feature: GeoFeature) -> GeoFeature:
        """Add a geographic feature to the repository with unique ID verification."""
        if feature.feature_id in self._features:
            raise DuplicateFeatureError(
                f"Feature with ID '{feature.feature_id}' already exists."
            )

        self._features[feature.feature_id] = feature
        self._sync_dataset_count(feature.feature_type, feature.dataset_id)
        return feature

    def get_feature(self, feature_id: str) -> Optional[GeoFeature]:
        """Retrieve a geographic feature by its unique identifier."""
        return self._features.get(feature_id)

    def list_features(
        self,
        feature_type: Optional[GeoFeatureType] = None,
        dataset_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[GeoFeature], int]:
        """List geographic features with optional category/dataset filter and pagination."""
        items = list(self._features.values())
        if feature_type is not None:
            type_val = (
                feature_type.value
                if isinstance(feature_type, GeoFeatureType)
                else str(feature_type)
            )
            items = [f for f in items if f.feature_type.value == type_val]

        if dataset_id is not None:
            items = [f for f in items if f.dataset_id == dataset_id]

        total = len(items)
        paginated = items[offset : offset + limit]
        return paginated, total

    def delete_feature(self, feature_id: str) -> bool:
        """Delete a geographic feature by ID."""
        if feature_id in self._features:
            feat = self._features.pop(feature_id)
            self._sync_dataset_count(feat.feature_type, feat.dataset_id)
            return True
        return False

    def count_features(
        self,
        feature_type: Optional[GeoFeatureType] = None,
        dataset_id: Optional[str] = None,
    ) -> int:
        """Count total registered features."""
        items = list(self._features.values())
        if feature_type is not None:
            type_val = (
                feature_type.value
                if isinstance(feature_type, GeoFeatureType)
                else str(feature_type)
            )
            items = [f for f in items if f.feature_type.value == type_val]
        if dataset_id is not None:
            items = [f for f in items if f.dataset_id == dataset_id]
        return len(items)

    def register_dataset(self, dataset: GeoDataset) -> GeoDataset:
        """Register or update a dataset descriptor."""
        self._datasets[dataset.dataset_id] = dataset
        return dataset

    def get_dataset(self, dataset_id: str) -> Optional[GeoDataset]:
        """Retrieve dataset entity by ID."""
        return self._datasets.get(dataset_id)

    def get_dataset_metadata(
        self, dataset_id: Optional[str] = None
    ) -> List[GeoDatasetMetadata]:
        """Retrieve dataset metadata descriptors."""
        if dataset_id:
            ds = self._datasets.get(dataset_id)
            if ds is None:
                return []
            return [self._to_metadata(ds)]

        return [self._to_metadata(ds) for ds in self._datasets.values()]

    def clear(self) -> None:
        """Reset repository state and reload clean dataset placeholders."""
        self._features.clear()
        self._datasets.clear()
        self._initialize_default_datasets()

    def _sync_dataset_count(
        self, feature_type: GeoFeatureType, dataset_id: Optional[str] = None
    ) -> None:
        """Update feature_count for dataset matching the feature type or dataset_id."""
        if dataset_id and dataset_id in self._datasets:
            cnt = self.count_features(dataset_id=dataset_id)
            self._datasets[dataset_id].feature_count = cnt
        else:
            type_val = (
                feature_type.value
                if isinstance(feature_type, GeoFeatureType)
                else str(feature_type)
            )
            cnt = self.count_features(feature_type=feature_type)
            for ds in self._datasets.values():
                if ds.feature_type.value == type_val:
                    ds.feature_count = cnt

    @staticmethod
    def _to_metadata(dataset: GeoDataset) -> GeoDatasetMetadata:
        """Convert GeoDataset entity to GeoDatasetMetadata DTO."""
        return GeoDatasetMetadata(
            dataset_id=dataset.dataset_id,
            name=dataset.name,
            feature_type=dataset.feature_type.value,
            source=dataset.source,
            source_url=dataset.source_url,
            version=dataset.version,
            updated_at=dataset.updated_at,
            feature_count=dataset.feature_count,
            bounding_box=dataset.bounding_box,
        )


# Singleton repository instance provider
_default_geography_repo: Optional[GeographyRepository] = None


def get_default_geography_repository() -> GeographyRepository:
    """Retrieve default persistent SQLite geography repository instance."""
    global _default_geography_repo
    if _default_geography_repo is None:
        _default_geography_repo = SQLiteGeographyRepository()
    return _default_geography_repo
