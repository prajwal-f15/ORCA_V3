"""Comprehensive unit and integration tests for Step 9 India Marine Geographic Data Foundation."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.main import app
from app.models.geography import (
    GeoBoundingBox,
    GeoDataset,
    GeoDatasetListResponse,
    GeoDatasetMetadata,
    GeoFeature,
    GeoFeatureListResponse,
    GeoFeatureType,
    GeoGeometry,
    GeometryType,
    GeoPoint,
)
from app.models.request import Coordinate
from app.repositories.geography_repository import (
    DuplicateFeatureError,
    GeographyRepository,
    InMemoryGeographyRepository,
)
from app.services.geography_service import (
    FeatureNotFoundError,
    GeographyService,
    InvalidFeatureTypeError,
    get_geography_service,
)


@pytest.fixture
def in_memory_repo() -> InMemoryGeographyRepository:
    """Fixture providing isolated InMemoryGeographyRepository."""
    repo = InMemoryGeographyRepository()
    repo.clear()
    return repo


@pytest.fixture
def geography_service(in_memory_repo: InMemoryGeographyRepository) -> GeographyService:
    """Fixture providing GeographyService with isolated in-memory repository."""
    return GeographyService(repository=in_memory_repo)


@pytest.fixture
def client(geography_service: GeographyService) -> TestClient:
    """Fixture providing FastAPI TestClient with overridden geography service."""
    app.dependency_overrides[get_geography_service] = lambda: geography_service
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# =============================================================================
# DATA MODEL & VALIDATION TESTS (1 - 10)
# =============================================================================


def test_1_geofeature_type_validation() -> None:
    """Test 1: Validate all supported GeoFeatureType enum values."""
    expected_types = {
        "coastline": GeoFeatureType.COASTLINE,
        "marine_area": GeoFeatureType.MARINE_AREA,
        "eez": GeoFeatureType.EEZ,
        "port": GeoFeatureType.PORT,
        "harbour": GeoFeatureType.HARBOUR,
        "landing_centre": GeoFeatureType.LANDING_CENTRE,
        "lighthouse": GeoFeatureType.LIGHTHOUSE,
        "bathymetry": GeoFeatureType.BATHYMETRY,
    }
    for val, enum_member in expected_types.items():
        assert GeoFeatureType(val) == enum_member

    with pytest.raises(ValueError):
        GeoFeatureType("invalid_domain_type")


def test_2_coordinate_validation() -> None:
    """Test 2: GeoPoint and Coordinate boundary validation [-90, 90] and [-180, 180]."""
    pt = GeoPoint(latitude=18.9220, longitude=72.8347)
    assert pt.latitude == 18.9220
    assert pt.longitude == 72.8347
    assert pt.to_geojson() == [72.8347, 18.9220]  # [longitude, latitude]

    # Test GeoJSON constructor
    reconstructed = GeoPoint.from_geojson([72.8347, 18.9220])
    assert reconstructed.latitude == 18.9220
    assert reconstructed.longitude == 72.8347

    # Test boundaries
    with pytest.raises(ValidationError):
        GeoPoint(latitude=91.0, longitude=72.0)
    with pytest.raises(ValidationError):
        GeoPoint(latitude=-91.0, longitude=72.0)
    with pytest.raises(ValidationError):
        GeoPoint(latitude=18.0, longitude=181.0)
    with pytest.raises(ValidationError):
        GeoPoint(latitude=18.0, longitude=-181.0)


def test_3_bounding_box_validation() -> None:
    """Test 3: GeoBoundingBox min/max coordinates and cross-validation."""
    bbox = GeoBoundingBox(
        min_latitude=6.5,
        min_longitude=68.0,
        max_latitude=35.5,
        max_longitude=97.5,
    )
    assert bbox.min_latitude == 6.5
    assert bbox.max_latitude == 35.5

    # min_latitude > max_latitude must fail
    with pytest.raises(ValidationError):
        GeoBoundingBox(
            min_latitude=20.0,
            min_longitude=70.0,
            max_latitude=10.0,
            max_longitude=80.0,
        )

    # min_longitude > max_longitude must fail
    with pytest.raises(ValidationError):
        GeoBoundingBox(
            min_latitude=10.0,
            min_longitude=80.0,
            max_latitude=20.0,
            max_longitude=70.0,
        )


def test_4_point_geometry() -> None:
    """Test 4: GeoGeometry Point type with [longitude, latitude] convention."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8347, 18.9220])
    assert geom.type == GeometryType.POINT
    assert geom.coordinates == [72.8347, 18.9220]


def test_5_linestring_geometry() -> None:
    """Test 5: GeoGeometry LineString with sequence of [longitude, latitude] points."""
    coords = [[72.8, 18.9], [72.9, 18.8], [73.0, 18.7]]
    geom = GeoGeometry(type=GeometryType.LINESTRING, coordinates=coords)
    assert geom.type == GeometryType.LINESTRING
    assert len(geom.coordinates) == 3


def test_6_polygon_geometry() -> None:
    """Test 6: GeoGeometry Polygon with closed linear rings."""
    ring = [
        [72.0, 18.0],
        [73.0, 18.0],
        [73.0, 19.0],
        [72.0, 19.0],
        [72.0, 18.0],
    ]
    geom = GeoGeometry(type=GeometryType.POLYGON, coordinates=[ring])
    assert geom.type == GeometryType.POLYGON
    assert len(geom.coordinates[0]) == 5


def test_7_multipolygon_geometry() -> None:
    """Test 7: GeoGeometry MultiPolygon containing multiple polygon rings."""
    poly1 = [
        [[70.0, 15.0], [71.0, 15.0], [71.0, 16.0], [70.0, 16.0], [70.0, 15.0]]
    ]
    poly2 = [
        [[72.0, 17.0], [73.0, 17.0], [73.0, 18.0], [72.0, 18.0], [72.0, 17.0]]
    ]
    geom = GeoGeometry(type=GeometryType.MULTIPOLYGON, coordinates=[poly1, poly2])
    assert geom.type == GeometryType.MULTIPOLYGON
    assert len(geom.coordinates) == 2


def test_8_invalid_geometry_type() -> None:
    """Test 8: Reject invalid/unrecognized geometry types."""
    with pytest.raises(ValidationError):
        GeoGeometry(type="InvalidGeometry", coordinates=[72.0, 18.0])


def test_9_invalid_coordinate() -> None:
    """Test 9: Reject coordinate pairs with out-of-range latitude/longitude or non-numeric values."""
    # Out of range latitude (95.0)
    with pytest.raises(ValidationError):
        GeoGeometry(type=GeometryType.POINT, coordinates=[72.0, 95.0])

    # Out of range longitude (190.0)
    with pytest.raises(ValidationError):
        GeoGeometry(type=GeometryType.POINT, coordinates=[190.0, 18.0])

    # Insufficient elements in coordinate pair
    with pytest.raises(ValidationError):
        GeoGeometry(type=GeometryType.POINT, coordinates=[72.0])


def test_10_feature_creation() -> None:
    """Test 10: GeoFeature model creation and attribute validation."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8347, 18.9220])
    feature = GeoFeature(
        feature_id="feat_mum_port",
        feature_type=GeoFeatureType.PORT,
        name="Mumbai Port",
        geometry=geom,
        properties={"category": "major_port", "berths": 32},
        source="INCOIS",
    )
    assert feature.feature_id == "feat_mum_port"
    assert feature.feature_type == GeoFeatureType.PORT
    assert feature.geometry_type == "Point"
    assert feature.name == "Mumbai Port"
    assert feature.properties["berths"] == 32


# =============================================================================
# REPOSITORY & SERVICE TESTS (11 - 19)
# =============================================================================


def test_11_feature_id_uniqueness(geography_service: GeographyService) -> None:
    """Test 11: Attempting to insert duplicate feature_id raises DuplicateFeatureError."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8347, 18.9220])
    feat1 = GeoFeature(
        feature_id="feat_unique_001",
        feature_type=GeoFeatureType.PORT,
        geometry=geom,
        source="INCOIS",
    )
    geography_service.add_feature(feat1)

    feat2 = GeoFeature(
        feature_id="feat_unique_001",
        feature_type=GeoFeatureType.LIGHTHOUSE,
        geometry=geom,
        source="INCOIS",
    )
    with pytest.raises(DuplicateFeatureError):
        geography_service.add_feature(feat2)


def test_12_add_feature(geography_service: GeographyService) -> None:
    """Test 12: Add feature correctly stores feature in repository."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8200, 18.9500])
    feature = GeoFeature(
        feature_id="harbour_01",
        feature_type=GeoFeatureType.HARBOUR,
        name="Sassoon Dock",
        geometry=geom,
        source="INCOIS",
    )
    saved = geography_service.add_feature(feature)
    assert saved.feature_id == "harbour_01"


def test_13_get_feature(geography_service: GeographyService) -> None:
    """Test 13: Retrieve feature by ID or raise FeatureNotFoundError."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8200, 18.9500])
    geography_service.add_feature(
        GeoFeature(
            feature_id="lh_01",
            feature_type=GeoFeatureType.LIGHTHOUSE,
            geometry=geom,
            source="INCOIS",
        )
    )

    found = geography_service.get_feature("lh_01")
    assert found.feature_id == "lh_01"

    with pytest.raises(FeatureNotFoundError):
        geography_service.get_feature("non_existent_id")


def test_14_list_features(geography_service: GeographyService) -> None:
    """Test 14: List features returns all registered features."""
    for i in range(3):
        geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.0 + i, 18.0])
        geography_service.add_feature(
            GeoFeature(
                feature_id=f"feat_{i}",
                feature_type=GeoFeatureType.LANDING_CENTRE,
                geometry=geom,
                source="INCOIS",
            )
        )

    features, total = geography_service.list_features()
    assert total == 3
    assert len(features) == 3


def test_15_filter_by_feature_type(geography_service: GeographyService) -> None:
    """Test 15: Filter features by specific GeoFeatureType."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.0, 18.0])
    geography_service.add_feature(
        GeoFeature(feature_id="p1", feature_type=GeoFeatureType.PORT, geometry=geom, source="INCOIS")
    )
    geography_service.add_feature(
        GeoFeature(feature_id="p2", feature_type=GeoFeatureType.PORT, geometry=geom, source="INCOIS")
    )
    geography_service.add_feature(
        GeoFeature(feature_id="lh1", feature_type=GeoFeatureType.LIGHTHOUSE, geometry=geom, source="INCOIS")
    )

    ports, total_ports = geography_service.list_features(feature_type=GeoFeatureType.PORT)
    assert total_ports == 2
    assert len(ports) == 2
    assert all(f.feature_type == GeoFeatureType.PORT for f in ports)

    lighthouses, total_lh = geography_service.list_features(feature_type="lighthouse")
    assert total_lh == 1
    assert len(lighthouses) == 1

    with pytest.raises(InvalidFeatureTypeError):
        geography_service.list_features(feature_type="unsupported_type")


def test_16_pagination(geography_service: GeographyService) -> None:
    """Test 16: Feature pagination with limit and offset."""
    for i in range(5):
        geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.0 + (i * 0.1), 18.0])
        geography_service.add_feature(
            GeoFeature(
                feature_id=f"page_feat_{i}",
                feature_type=GeoFeatureType.BATHYMETRY,
                geometry=geom,
                source="INCOIS",
            )
        )

    p1, total = geography_service.list_features(limit=2, offset=0)
    assert total == 5
    assert len(p1) == 2
    assert p1[0].feature_id == "page_feat_0"

    p2, total = geography_service.list_features(limit=2, offset=2)
    assert total == 5
    assert len(p2) == 2
    assert p2[0].feature_id == "page_feat_2"


def test_17_delete_feature(geography_service: GeographyService) -> None:
    """Test 17: Delete feature removes feature from repository."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.0, 18.0])
    geography_service.add_feature(
        GeoFeature(
            feature_id="to_delete",
            feature_type=GeoFeatureType.PORT,
            geometry=geom,
            source="INCOIS",
        )
    )
    assert geography_service.delete_feature("to_delete") is True

    with pytest.raises(FeatureNotFoundError):
        geography_service.get_feature("to_delete")

    with pytest.raises(FeatureNotFoundError):
        geography_service.delete_feature("to_delete")


def test_18_dataset_metadata(geography_service: GeographyService) -> None:
    """Test 18: Registered dataset metadata descriptors for all India marine categories."""
    datasets = geography_service.get_datasets()
    assert len(datasets) == 8

    dataset_ids = {d.dataset_id for d in datasets}
    assert "india_coastline" in dataset_ids
    assert "india_eez" in dataset_ids
    assert "india_marine_area" in dataset_ids
    assert "india_ports" in dataset_ids
    assert "india_harbours" in dataset_ids
    assert "india_landing_centres" in dataset_ids
    assert "india_lighthouses" in dataset_ids
    assert "india_bathymetry" in dataset_ids

    # Query single dataset
    coastline_meta = geography_service.get_datasets(dataset_id="india_coastline")
    assert len(coastline_meta) == 1
    assert coastline_meta[0].feature_type == "coastline"
    assert coastline_meta[0].source == "pending"


def test_19_empty_repository_behaviour(geography_service: GeographyService) -> None:
    """Test 19: Repository starts with 0 features and returns empty lists without error."""
    features, total = geography_service.list_features()
    assert total == 0
    assert len(features) == 0

    with pytest.raises(FeatureNotFoundError):
        geography_service.get_feature("any_id")


# =============================================================================
# API INTEGRATION TESTS (20 - 23)
# =============================================================================


def test_20_api_datasets_endpoint(client: TestClient) -> None:
    """Test 20: GET /geography/datasets and /api/v1/geography/datasets."""
    resp = client.get("/geography/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert "datasets" in data
    assert data["total"] == 8
    assert any(d["dataset_id"] == "india_coastline" for d in data["datasets"])

    resp_v1 = client.get("/api/v1/geography/datasets")
    assert resp_v1.status_code == 200
    data_v1 = resp_v1.json()
    assert data_v1["total"] == 8


def test_21_api_features_endpoint(client: TestClient, geography_service: GeographyService) -> None:
    """Test 21: GET /geography/features with query parameters."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8347, 18.9220])
    geography_service.add_feature(
        GeoFeature(
            feature_id="api_port_01",
            feature_type=GeoFeatureType.PORT,
            name="Mumbai Port",
            geometry=geom,
            source="INCOIS",
        )
    )

    resp = client.get("/geography/features")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["features"][0]["feature_id"] == "api_port_01"

    # Filter by feature_type
    resp_filtered = client.get("/geography/features?feature_type=port")
    assert resp_filtered.status_code == 200
    assert resp_filtered.json()["total"] == 1

    # Filter with no match
    resp_empty = client.get("/geography/features?feature_type=lighthouse")
    assert resp_empty.status_code == 200
    assert resp_empty.json()["total"] == 0

    # Invalid feature type -> 400
    resp_bad = client.get("/geography/features?feature_type=unknown")
    assert resp_bad.status_code == 400


def test_22_api_single_feature_endpoint(
    client: TestClient, geography_service: GeographyService
) -> None:
    """Test 22: GET /geography/features/{feature_id}."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8200, 18.9500])
    geography_service.add_feature(
        GeoFeature(
            feature_id="api_lh_99",
            feature_type=GeoFeatureType.LIGHTHOUSE,
            name="Prongs Lighthouse",
            geometry=geom,
            source="INCOIS",
        )
    )

    resp = client.get("/geography/features/api_lh_99")
    assert resp.status_code == 200
    data = resp.json()
    assert data["feature_id"] == "api_lh_99"
    assert data["name"] == "Prongs Lighthouse"
    assert data["geometry"]["type"] == "Point"

    # 404 for unknown feature
    resp_404 = client.get("/geography/features/non_existent")
    assert resp_404.status_code == 404


def test_23_api_feature_type_endpoint(
    client: TestClient, geography_service: GeographyService
) -> None:
    """Test 23: GET /geography/features/type/{feature_type}."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9])
    geography_service.add_feature(
        GeoFeature(
            feature_id="harbour_mum",
            feature_type=GeoFeatureType.HARBOUR,
            name="Mumbai Harbour",
            geometry=geom,
            source="INCOIS",
        )
    )

    resp = client.get("/geography/features/type/harbour")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["features"][0]["feature_id"] == "harbour_mum"

    # Invalid type -> 400
    resp_invalid = client.get("/geography/features/type/invalid_type")
    assert resp_invalid.status_code == 400
