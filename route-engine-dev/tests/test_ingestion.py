"""Comprehensive unit and integration tests for Step 10 Real Official India Marine Geographic Data Ingestion."""

import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.ingestion.geo_data_loader import GeoDataLoader, IngestionResult
from app.ingestion.geo_data_validator import GeoDataValidationError, GeoDataValidator
from app.models.geography import (
    GeoBoundingBox,
    GeoDataset,
    GeoDatasetMetadata,
    GeoFeature,
    GeoFeatureType,
    GeoGeometry,
    GeometryType,
)
from app.repositories.geography_repository import (
    DuplicateFeatureError,
    InMemoryGeographyRepository,
    SQLiteGeographyRepository,
)
from app.services.geography_service import (
    DatasetNotFoundError,
    FeatureNotFoundError,
    GeographyService,
    InvalidFeatureTypeError,
    get_geography_service,
)


@pytest.fixture
def temp_db_path(tmp_path):
    """Fixture providing a temporary SQLite database file path."""
    db_file = tmp_path / "test_geography.db"
    return str(db_file)


@pytest.fixture
def sqlite_repo(temp_db_path):
    """Fixture providing an isolated SQLiteGeographyRepository."""
    return SQLiteGeographyRepository(db_path=temp_db_path)


@pytest.fixture
def in_memory_repo():
    """Fixture providing an isolated InMemoryGeographyRepository."""
    repo = InMemoryGeographyRepository()
    repo.clear()
    return repo


@pytest.fixture
def geography_service(in_memory_repo):
    """Fixture providing GeographyService with isolated in-memory repository."""
    return GeographyService(repository=in_memory_repo)


@pytest.fixture
def client(geography_service):
    """Fixture providing FastAPI TestClient with overridden geography service."""
    app.dependency_overrides[get_geography_service] = lambda: geography_service
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# =============================================================================
# 1. VALID GEOJSON VALIDATION TESTS
# =============================================================================


def test_validator_valid_polygon():
    """Test validator successfully parses and validates a GeoJSON Polygon FeatureCollection."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "poly-1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [72.8, 18.9],
                            [73.0, 18.9],
                            [73.0, 19.1],
                            [72.8, 19.1],
                            [72.8, 18.9],
                        ]
                    ],
                },
                "properties": {"name": "Test Coastal Zone"},
            }
        ],
    }
    validator = GeoDataValidator()
    features, bbox = validator.validate_geojson(geojson, default_feature_type="marine_area")
    assert len(features) == 1
    feat = features[0]
    assert feat.id == "poly-1"
    assert feat.feature_type == GeoFeatureType.MARINE_AREA
    assert feat.geometry.type == GeometryType.POLYGON
    assert feat.properties["name"] == "Test Coastal Zone"
    assert bbox is not None
    assert bbox.min_lon == 72.8
    assert bbox.max_lon == 73.0
    assert bbox.min_lat == 18.9
    assert bbox.max_lat == 19.1


def test_validator_valid_multipolygon():
    """Test validator successfully validates a MultiPolygon."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [70.0, 15.0],
                                [71.0, 15.0],
                                [71.0, 16.0],
                                [70.0, 16.0],
                                [70.0, 15.0],
                            ]
                        ],
                        [
                            [
                                [80.0, 10.0],
                                [81.0, 10.0],
                                [81.0, 11.0],
                                [80.0, 11.0],
                                [80.0, 10.0],
                            ]
                        ],
                    ],
                },
                "properties": {"name": "India EEZ Sector"},
            }
        ],
    }
    validator = GeoDataValidator()
    features, bbox = validator.validate_geojson(geojson, default_feature_type="eez")
    assert len(features) == 1
    assert features[0].geometry.type == GeometryType.MULTIPOLYGON
    assert bbox.min_lon == 70.0
    assert bbox.max_lon == 81.0
    assert bbox.min_lat == 10.0
    assert bbox.max_lat == 16.0


def test_validator_valid_linestring():
    """Test validator successfully validates a LineString (e.g. coastline segment)."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [72.82, 18.92],
                        [72.85, 18.95],
                        [72.88, 19.00],
                    ],
                },
                "properties": {"name": "Mumbai Coastline Segment"},
            }
        ],
    }
    validator = GeoDataValidator()
    features, bbox = validator.validate_geojson(geojson, default_feature_type="coastline")
    assert len(features) == 1
    assert features[0].geometry.type == GeometryType.LINESTRING
    assert features[0].feature_type == GeoFeatureType.COASTLINE


def test_validator_valid_point():
    """Test validator successfully validates a Point feature."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "port-jnpt",
                "geometry": {
                    "type": "Point",
                    "coordinates": [72.95, 18.95],
                },
                "properties": {"name": "JNPT Port", "feature_type": "port"},
            }
        ],
    }
    validator = GeoDataValidator()
    features, bbox = validator.validate_geojson(geojson)
    assert len(features) == 1
    assert features[0].feature_type == GeoFeatureType.PORT
    assert features[0].geometry.type == GeometryType.POINT
    assert bbox.min_lon == 72.95
    assert bbox.max_lat == 18.95


# =============================================================================
# 2. INVALID GEOJSON & COORDINATE VALIDATION TESTS
# =============================================================================


def test_validator_invalid_geojson_structure():
    """Test validator rejects non-dictionary or empty inputs."""
    validator = GeoDataValidator()
    with pytest.raises(GeoDataValidationError, match="Expected GeoJSON dict or string"):
        validator.validate_geojson(12345)  # type: ignore

    with pytest.raises(GeoDataValidationError, match="Missing top-level 'type' attribute"):
        validator.validate_geojson({"features": []})


def test_validator_invalid_geojson_type():
    """Test validator rejects unsupported top-level GeoJSON types."""
    validator = GeoDataValidator()
    with pytest.raises(GeoDataValidationError, match="Unrecognized GeoJSON document type"):
        validator.validate_geojson({"type": "UnsupportedGeometryCollection", "geometries": []})


def test_validator_out_of_bounds_coordinates():
    """Test validator strictly rejects coordinates outside [-180, 180] lon or [-90, 90] lat."""
    validator = GeoDataValidator()

    # Out-of-bounds Longitude (> 180)
    bad_lon_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [185.0, 19.0],
                },
                "properties": {},
            }
        ],
    }
    with pytest.raises(GeoDataValidationError, match="Longitude 185.0 out of range"):
        validator.validate_geojson(bad_lon_geojson)

    # Out-of-bounds Latitude (> 90)
    bad_lat_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [72.8, 95.0],
                },
                "properties": {},
            }
        ],
    }
    with pytest.raises(GeoDataValidationError, match="Latitude 95.0 out of range"):
        validator.validate_geojson(bad_lat_geojson)


def test_validator_unclosed_polygon_ring():
    """Test validator rejects Polygon rings that are not closed."""
    unclosed_polygon = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [72.8, 18.9],
                            [73.0, 18.9],
                            [73.0, 19.1],
                            [72.8, 19.1],
                            # Missing closing coordinate [72.8, 18.9]
                        ]
                    ],
                },
                "properties": {},
            }
        ],
    }
    validator = GeoDataValidator()
    with pytest.raises(GeoDataValidationError, match="first and last coordinates must be identical"):
        validator.validate_geojson(unclosed_polygon)


def test_validator_polygon_too_few_points():
    """Test validator rejects Polygon rings with fewer than 4 points."""
    polygon_few_pts = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [72.8, 18.9],
                            [73.0, 18.9],
                            [72.8, 18.9],
                        ]
                    ],
                },
                "properties": {},
            }
        ],
    }
    validator = GeoDataValidator()
    with pytest.raises(GeoDataValidationError, match="must have at least 4 positions"):
        validator.validate_geojson(polygon_few_pts)


def test_validator_malformed_coordinate_dimensions():
    """Test validator rejects coordinates that are not 2-element [lon, lat] pairs."""
    malformed_coords = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [72.8],  # Missing lat
                },
                "properties": {},
            }
        ],
    }
    validator = GeoDataValidator()
    with pytest.raises(GeoDataValidationError, match="Expected \\[lon, lat\\] coordinate pair"):
        validator.validate_geojson(malformed_coords)


# =============================================================================
# 3. GEO DATA LOADER INGESTION PIPELINE TESTS
# =============================================================================


def test_geo_data_loader_ingest_dict(in_memory_repo):
    """Test GeoDataLoader ingesting GeoJSON dict directly."""
    loader = GeoDataLoader(repository=in_memory_repo, save_processed=False)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "coast-001",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[72.8, 18.9], [72.9, 19.0]],
                },
                "properties": {"name": "INCOIS Coastline Segment"},
            }
        ],
    }

    result = loader.ingest_geojson_data(
        geojson_data=geojson,
        dataset_id="india_coastline",
        dataset_name="Official India Coastline",
        source="INCOIS",
        source_url="https://incois.gov.in/geoportal/MFASPFZ/index.html",
        version="2026.1",
        default_feature_type="coastline",
    )

    assert result.success is True
    assert result.features_ingested == 1
    assert result.dataset_id == "india_coastline"
    assert result.bounding_box is not None

    # Verify repository state
    dataset = in_memory_repo.get_dataset("india_coastline")
    assert dataset is not None
    assert dataset.feature_count == 1
    assert dataset.source == "INCOIS"
    assert dataset.version == "2026.1"

    feature = in_memory_repo.get_feature("coast-001")
    assert feature is not None
    assert feature.dataset_id == "india_coastline"
    assert feature.feature_type == GeoFeatureType.COASTLINE


def test_geo_data_loader_ingest_file(tmp_path, in_memory_repo):
    """Test GeoDataLoader ingesting from a physical .geojson file and saving processed output."""
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()

    raw_file = raw_dir / "official_eez.geojson"
    geojson_content = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "eez-sector-1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [70.0, 10.0],
                            [75.0, 10.0],
                            [75.0, 15.0],
                            [70.0, 15.0],
                            [70.0, 10.0],
                        ]
                    ],
                },
                "properties": {"name": "INCOIS EEZ Sector 1"},
            }
        ],
    }
    raw_file.write_text(json.dumps(geojson_content), encoding="utf-8")

    loader = GeoDataLoader(
        repository=in_memory_repo,
        processed_dir=str(processed_dir),
        save_processed=True,
    )

    result = loader.ingest_file(
        file_path=str(raw_file),
        dataset_id="india_eez",
        dataset_name="Official India EEZ Boundary",
        source="INCOIS PFZ Geoportal",
        source_url="https://incois.gov.in/geoportal/MFASPFZ/index.html",
        version="v2026",
        default_feature_type="eez",
    )

    assert result.success is True
    assert result.features_ingested == 1
    assert result.processed_file_path is not None
    assert os.path.exists(result.processed_file_path)

    # Check processed JSON format
    with open(result.processed_file_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["dataset_id"] == "india_eez"
    assert saved_data["source"] == "INCOIS PFZ Geoportal"
    assert len(saved_data["features"]) == 1


def test_geo_data_loader_file_not_found(in_memory_repo):
    """Test GeoDataLoader error handling when raw file does not exist."""
    loader = GeoDataLoader(repository=in_memory_repo)
    result = loader.ingest_file(
        file_path="non_existent_file.geojson",
        dataset_id="test_ds",
    )
    assert result.success is False
    assert "not found" in result.errors[0].lower()


def test_geo_data_loader_malformed_json_file(tmp_path, in_memory_repo):
    """Test GeoDataLoader error handling when raw file contains invalid JSON syntax."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ unquoted_key: 123 ", encoding="utf-8")

    loader = GeoDataLoader(repository=in_memory_repo)
    result = loader.ingest_file(file_path=str(bad_file), dataset_id="bad_ds")
    assert result.success is False
    assert "malformed" in result.errors[0].lower() or "json" in result.errors[0].lower()


# =============================================================================
# 4. SQLITE GEOGRAPHY REPOSITORY PERSISTENCE TESTS
# =============================================================================


def test_sqlite_repository_persistence(temp_db_path):
    """Test that SQLiteGeographyRepository persists datasets and features across re-instantiation."""
    repo1 = SQLiteGeographyRepository(db_path=temp_db_path)

    # Add dataset
    bbox = GeoBoundingBox(min_lon=70.0, max_lon=75.0, min_lat=10.0, max_lat=15.0)
    dataset = GeoDataset(
        dataset_id="india_eez",
        name="Official India EEZ",
        feature_type=GeoFeatureType.EEZ,
        source="INCOIS",
        source_url="https://incois.gov.in",
        version="1.0",
        feature_count=1,
        bounding_box=bbox,
    )
    repo1.upsert_dataset(dataset)

    # Add feature
    geom = GeoGeometry(
        type=GeometryType.POLYGON,
        coordinates=[
            [[70.0, 10.0], [75.0, 10.0], [75.0, 15.0], [70.0, 15.0], [70.0, 10.0]]
        ],
    )
    feature = GeoFeature(
        id="eez-feature-1",
        dataset_id="india_eez",
        feature_type=GeoFeatureType.EEZ,
        geometry=geom,
        properties={"zone": "West Coast"},
    )
    repo1.add_feature(feature)

    # Re-instantiate repository pointing to same database
    repo2 = SQLiteGeographyRepository(db_path=temp_db_path)

    persisted_ds = repo2.get_dataset("india_eez")
    assert persisted_ds is not None
    assert persisted_ds.source == "INCOIS"
    assert persisted_ds.feature_count == 1
    assert persisted_ds.bounding_box.min_lon == 70.0

    persisted_feat = repo2.get_feature("eez-feature-1")
    assert persisted_feat is not None
    assert persisted_feat.dataset_id == "india_eez"
    assert persisted_feat.geometry.type == GeometryType.POLYGON
    assert persisted_feat.properties["zone"] == "West Coast"


def test_sqlite_repository_filtering_by_dataset(sqlite_repo):
    """Test querying features filtered by dataset_id in SQLiteGeographyRepository."""
    # Insert two datasets and features
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9])

    feat1 = GeoFeature(
        id="feat-coast-1",
        dataset_id="india_coastline",
        feature_type=GeoFeatureType.COASTLINE,
        geometry=geom,
    )
    feat2 = GeoFeature(
        id="feat-eez-1",
        dataset_id="india_eez",
        feature_type=GeoFeatureType.EEZ,
        geometry=geom,
    )
    sqlite_repo.add_feature(feat1)
    sqlite_repo.add_feature(feat2)

    coast_features, count1 = sqlite_repo.list_features(dataset_id="india_coastline")
    assert count1 == 1
    assert coast_features[0].id == "feat-coast-1"

    eez_features, count2 = sqlite_repo.list_features(dataset_id="india_eez")
    assert count2 == 1
    assert eez_features[0].id == "feat-eez-1"


def test_sqlite_repository_duplicate_feature(sqlite_repo):
    """Test SQLiteGeographyRepository raises DuplicateFeatureError on duplicate ID."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9])
    feat = GeoFeature(id="dup-feat", feature_type=GeoFeatureType.PORT, geometry=geom)
    sqlite_repo.add_feature(feat)

    with pytest.raises(DuplicateFeatureError):
        sqlite_repo.add_feature(feat)


# =============================================================================
# 5. GEOGRAPHY SERVICE & API ENDPOINT TESTS (STEP 10 EXTENSIONS)
# =============================================================================


def test_service_get_dataset(in_memory_repo):
    """Test GeographyService.get_dataset returns dataset or raises DatasetNotFoundError."""
    service = GeographyService(repository=in_memory_repo)

    # Pre-registered dataset exists
    ds = service.get_dataset("india_coastline")
    assert ds.dataset_id == "india_coastline"

    # Non-existent dataset raises DatasetNotFoundError
    with pytest.raises(DatasetNotFoundError):
        service.get_dataset("non_existent_dataset")


def test_service_list_features_with_dataset_filter(in_memory_repo):
    """Test GeographyService.list_features with dataset_id filter."""
    service = GeographyService(repository=in_memory_repo)
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9])

    in_memory_repo.add_feature(
        GeoFeature(
            id="f-ds1",
            dataset_id="india_coastline",
            feature_type=GeoFeatureType.COASTLINE,
            geometry=geom,
        )
    )
    in_memory_repo.add_feature(
        GeoFeature(
            id="f-ds2",
            dataset_id="india_eez",
            feature_type=GeoFeatureType.EEZ,
            geometry=geom,
        )
    )

    features, total = service.list_features(dataset_id="india_coastline")
    assert total == 1
    assert features[0].id == "f-ds1"


def test_api_get_dataset_by_id_success(client, in_memory_repo):
    """Test GET /geography/datasets/{dataset_id} returns 200 OK with dataset metadata."""
    response = client.get("/geography/datasets/india_coastline")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == "india_coastline"
    assert data["name"] == "India Coastline Boundary"
    assert data["feature_type"] == "coastline"


def test_api_get_dataset_by_id_not_found(client):
    """Test GET /geography/datasets/{dataset_id} returns 404 for unknown dataset ID."""
    response = client.get("/geography/datasets/unknown_id")
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


def test_api_get_features_filtered_by_dataset(client, in_memory_repo):
    """Test GET /geography/features?dataset_id=... returns filtered features."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9])
    in_memory_repo.add_feature(
        GeoFeature(
            id="feat-incois-1",
            dataset_id="india_coastline",
            feature_type=GeoFeatureType.COASTLINE,
            geometry=geom,
        )
    )
    in_memory_repo.add_feature(
        GeoFeature(
            id="feat-incois-2",
            dataset_id="india_eez",
            feature_type=GeoFeatureType.EEZ,
            geometry=geom,
        )
    )

    # Filter by india_coastline
    resp = client.get("/geography/features?dataset_id=india_coastline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["features"]) == 1
    assert data["features"][0]["feature_id"] == "feat-incois-1"
    assert data["features"][0]["dataset_id"] == "india_coastline"
