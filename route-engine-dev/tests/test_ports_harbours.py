"""Comprehensive unit and integration tests for Step 11 India Ports, Harbours, Landing Centres & Lighthouses."""

import json
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.ingestion.geo_data_loader import GeoDataLoader
from app.ingestion.geo_data_validator import GeoDataValidator, GeoValidationError
from app.models.geography import (
    GeoBoundingBox,
    GeoDataset,
    GeoFeature,
    GeoFeatureType,
    GeoGeometry,
    GeometryType,
    GeoNearbyFeature,
    GeoNearbyResponse,
)
from app.models.request import Coordinate
from app.repositories.geography_repository import (
    DuplicateFeatureError,
    InMemoryGeographyRepository,
    SQLiteGeographyRepository,
)
from app.services.geo_service import GeoService
from app.services.geography_service import (
    FeatureNotFoundError,
    GeographyService,
    InvalidFeatureTypeError,
    get_geography_service,
)


@pytest.fixture
def temp_db_path(tmp_path):
    """Fixture providing temporary SQLite database path."""
    db_file = tmp_path / "test_marine_locations.db"
    return str(db_file)


@pytest.fixture
def sqlite_repo(temp_db_path):
    """Fixture providing isolated SQLiteGeographyRepository."""
    return SQLiteGeographyRepository(db_path=temp_db_path)


@pytest.fixture
def in_memory_repo():
    """Fixture providing isolated InMemoryGeographyRepository."""
    repo = InMemoryGeographyRepository()
    repo.clear()
    return repo


@pytest.fixture
def geography_service(in_memory_repo):
    """Fixture providing GeographyService backed by isolated in-memory repository."""
    return GeographyService(repository=in_memory_repo)


@pytest.fixture
def client(geography_service):
    """Fixture providing FastAPI TestClient with overridden geography service."""
    app.dependency_overrides[get_geography_service] = lambda: geography_service
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# =============================================================================
# 1. MODEL & PROPERTY ACCESSOR TESTS (Port, Harbour, Landing Centre, Lighthouse)
# =============================================================================


def test_port_model_properties():
    """Test GeoFeature configured as PORT extracts lat, lon, state, district, code."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8500, 18.9400])
    feature = GeoFeature(
        feature_id="in_mum_port",
        dataset_id="india_ports",
        feature_type=GeoFeatureType.PORT,
        name="Mumbai Port Trust",
        geometry=geom,
        properties={
            "state": "Maharashtra",
            "district": "Mumbai City",
            "code": "INBOM",
            "port_type": "Major Port",
        },
        source="Ministry of Ports, Shipping and Waterways",
    )
    assert feature.feature_type == GeoFeatureType.PORT
    assert feature.name == "Mumbai Port Trust"
    assert feature.latitude == 18.9400
    assert feature.longitude == 72.8500
    assert feature.state == "Maharashtra"
    assert feature.district == "Mumbai City"
    assert feature.code == "INBOM"


def test_harbour_model_properties():
    """Test GeoFeature configured as HARBOUR extracts properties."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8250, 18.9100])
    feature = GeoFeature(
        feature_id="in_sassoon_dock",
        dataset_id="india_harbours",
        feature_type=GeoFeatureType.HARBOUR,
        name="Sassoon Fishing Harbour",
        geometry=geom,
        properties={
            "state_name": "Maharashtra",
            "district_name": "Mumbai",
            "berths": 12,
        },
        source="INCOIS MFAS/PFZ Geoportal",
    )
    assert feature.feature_type == GeoFeatureType.HARBOUR
    assert feature.latitude == 18.9100
    assert feature.longitude == 72.8250
    assert feature.state == "Maharashtra"
    assert feature.district == "Mumbai"


def test_landing_centre_model_properties():
    """Test GeoFeature configured as LANDING_CENTRE extracts properties."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8100, 19.1200])
    feature = GeoFeature(
        feature_id="in_versova_lc",
        dataset_id="india_landing_centres",
        feature_type=GeoFeatureType.LANDING_CENTRE,
        name="Versova Fish Landing Centre",
        geometry=geom,
        properties={
            "state": "Maharashtra",
            "district": "Mumbai Suburban",
            "craft_count": 250,
        },
        source="INCOIS",
    )
    assert feature.feature_type == GeoFeatureType.LANDING_CENTRE
    assert feature.latitude == 19.1200
    assert feature.longitude == 72.8100
    assert feature.state == "Maharashtra"
    assert feature.district == "Mumbai Suburban"


def test_lighthouse_model_properties():
    """Test GeoFeature configured as LIGHTHOUSE extracts properties."""
    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8180, 18.8950])
    feature = GeoFeature(
        feature_id="in_prongs_light",
        dataset_id="india_lighthouses",
        feature_type=GeoFeatureType.LIGHTHOUSE,
        name="Prongs Reef Lighthouse",
        geometry=geom,
        properties={
            "state": "Maharashtra",
            "district": "Mumbai",
            "light_number": "F0512",
            "range_nm": 17,
        },
        source="DGLL - Directorate General of Lighthouses and Lightships",
    )
    assert feature.feature_type == GeoFeatureType.LIGHTHOUSE
    assert feature.latitude == 18.8950
    assert feature.longitude == 72.8180
    assert feature.code == "F0512"


# =============================================================================
# 2. POINT INGESTION & COORDINATE VALIDATION TESTS
# =============================================================================


def test_ingest_points_geojson(in_memory_repo):
    """Test ingesting multiple Point features representing ports and lighthouses."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "port-001",
                "geometry": {
                    "type": "Point",
                    "coordinates": [72.9500, 18.9500],
                },
                "properties": {
                    "name": "JNPT Port",
                    "feature_type": "port",
                    "state": "Maharashtra",
                    "code": "INNSA",
                },
            },
            {
                "type": "Feature",
                "id": "light-001",
                "geometry": {
                    "type": "Point",
                    "coordinates": [72.8180, 18.8950],
                },
                "properties": {
                    "name": "Prongs Lighthouse",
                    "feature_type": "lighthouse",
                    "state": "Maharashtra",
                    "code": "F0512",
                },
            },
        ],
    }

    loader = GeoDataLoader(repository=in_memory_repo, save_processed=False)
    result = loader.ingest_geojson_data(
        geojson_data=geojson,
        dataset_id="india_ports",
        name="Official India Ports & Aids",
        source="INCOIS / Ministry of Ports",
        version="2026.1",
        default_feature_type="port",
    )

    assert result.success is True
    assert result.features_ingested == 2

    # Check that individual feature types were preserved from properties
    p_feat = in_memory_repo.get_feature("port-001")
    assert p_feat is not None
    assert p_feat.feature_type == GeoFeatureType.PORT
    assert p_feat.latitude == 18.9500
    assert p_feat.longitude == 72.9500

    l_feat = in_memory_repo.get_feature("light-001")
    assert l_feat is not None
    assert l_feat.feature_type == GeoFeatureType.LIGHTHOUSE
    assert l_feat.latitude == 18.8950
    assert l_feat.longitude == 72.8180


def test_reject_out_of_bounds_point_coordinates(in_memory_repo):
    """Test validator rejects points with coordinates outside WGS 84 bounds."""
    bad_point_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [195.0, 18.0],
                },
                "properties": {"name": "Invalid Port"},
            }
        ],
    }
    loader = GeoDataLoader(repository=in_memory_repo, save_processed=False)
    result = loader.ingest_geojson_data(
        geojson_data=bad_point_geojson,
        dataset_id="bad_ds",
        default_feature_type="port",
    )
    assert result.success is False
    assert len(result.errors) > 0
    assert "out of range" in result.errors[0].lower()


def test_sqlite_persistence_for_point_locations(temp_db_path):
    """Test that SQLiteGeographyRepository persists and retrieves marine point features across instances."""
    repo1 = SQLiteGeographyRepository(db_path=temp_db_path)

    geom = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8347, 18.9220])
    feature = GeoFeature(
        id="gateway_dock",
        dataset_id="india_harbours",
        feature_type=GeoFeatureType.HARBOUR,
        name="Gateway Harbour Jetty",
        geometry=geom,
        properties={"state": "Maharashtra", "district": "Mumbai"},
        source="INCOIS",
    )
    repo1.add_feature(feature)

    # Reconnect using second repository instance
    repo2 = SQLiteGeographyRepository(db_path=temp_db_path)
    loaded = repo2.get_feature("gateway_dock")
    assert loaded is not None
    assert loaded.name == "Gateway Harbour Jetty"
    assert loaded.feature_type == GeoFeatureType.HARBOUR
    assert loaded.latitude == 18.9220
    assert loaded.longitude == 72.8347
    assert loaded.state == "Maharashtra"


# =============================================================================
# 3. SERVICE CONVENIENCE METHODS & FEATURE-TYPE QUERIES
# =============================================================================


def test_service_category_queries(in_memory_repo, geography_service):
    """Test get_ports, get_harbours, get_landing_centres, get_lighthouses service methods."""
    pt = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9])

    in_memory_repo.add_feature(
        GeoFeature(id="p1", feature_type=GeoFeatureType.PORT, geometry=pt, name="Port 1")
    )
    in_memory_repo.add_feature(
        GeoFeature(id="h1", feature_type=GeoFeatureType.HARBOUR, geometry=pt, name="Harbour 1")
    )
    in_memory_repo.add_feature(
        GeoFeature(
            id="lc1",
            feature_type=GeoFeatureType.LANDING_CENTRE,
            geometry=pt,
            name="Landing Centre 1",
        )
    )
    in_memory_repo.add_feature(
        GeoFeature(
            id="l1", feature_type=GeoFeatureType.LIGHTHOUSE, geometry=pt, name="Lighthouse 1"
        )
    )

    ports, p_count = geography_service.get_ports()
    assert p_count == 1
    assert ports[0].id == "p1"

    harbours, h_count = geography_service.get_harbours()
    assert h_count == 1
    assert harbours[0].id == "h1"

    lcs, lc_count = geography_service.get_landing_centres()
    assert lc_count == 1
    assert lcs[0].id == "lc1"

    lighthouses, l_count = geography_service.get_lighthouses()
    assert l_count == 1
    assert lighthouses[0].id == "l1"


# =============================================================================
# 4. NEARBY FEATURE SEARCH & DISTANCE CALCULATION TESTS
# =============================================================================


def test_find_nearby_features_ordering_and_distance(in_memory_repo, geography_service):
    """Test find_nearby_features returns features ordered by distance with accurate distance/bearing."""
    # Reference origin: 18.9000 N, 72.8000 E
    # Feature 1: ~2.2 km away
    f1 = GeoFeature(
        id="near_harbour",
        feature_type=GeoFeatureType.HARBOUR,
        name="Close Harbour",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.8200, 18.9100]),
    )
    # Feature 2: ~11.2 km away
    f2 = GeoFeature(
        id="mid_port",
        feature_type=GeoFeatureType.PORT,
        name="Mid-distance Port",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.8500, 18.9900]),
    )
    # Feature 3: ~120 km away
    f3 = GeoFeature(
        id="far_lighthouse",
        feature_type=GeoFeatureType.LIGHTHOUSE,
        name="Far Lighthouse",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[73.5000, 19.8000]),
    )
    in_memory_repo.add_feature(f1)
    in_memory_repo.add_feature(f2)
    in_memory_repo.add_feature(f3)

    # Search with 50 km radius: should return f1 and f2, ordered by distance
    results = geography_service.find_nearby_features(
        latitude=18.9000,
        longitude=72.8000,
        radius_km=50.0,
    )

    assert len(results) == 2
    assert results[0].feature.id == "near_harbour"
    assert results[1].feature.id == "mid_port"
    assert results[0].distance_km < results[1].distance_km
    assert results[0].distance_nm == GeoService.km_to_nautical_miles(results[0].distance_km)
    assert 0.0 <= results[0].bearing_degrees < 360.0


def test_find_nearby_features_type_filter(in_memory_repo, geography_service):
    """Test find_nearby_features filtering specifically by feature_type."""
    f_port = GeoFeature(
        id="test_port",
        feature_type=GeoFeatureType.PORT,
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.82, 18.91]),
    )
    f_harbour = GeoFeature(
        id="test_harbour",
        feature_type=GeoFeatureType.HARBOUR,
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.83, 18.92]),
    )
    in_memory_repo.add_feature(f_port)
    in_memory_repo.add_feature(f_harbour)

    # Filter only harbours
    results = geography_service.find_nearby_features(
        latitude=18.90,
        longitude=72.80,
        feature_type=GeoFeatureType.HARBOUR,
        radius_km=50.0,
    )
    assert len(results) == 1
    assert results[0].feature.id == "test_harbour"


def test_find_nearby_features_invalid_arguments(geography_service):
    """Test validation errors on invalid coordinates or radius."""
    with pytest.raises(ValueError, match="Latitude 95.0 out of valid range"):
        geography_service.find_nearby_features(latitude=95.0, longitude=72.0)

    with pytest.raises(ValueError, match="Radius must be greater than zero"):
        geography_service.find_nearby_features(latitude=18.0, longitude=72.0, radius_km=0.0)


# =============================================================================
# 5. API ENDPOINT TESTS (Step 11 Routes & Nearby Endpoint)
# =============================================================================


def test_api_get_features_by_type_endpoints(client, in_memory_repo):
    """Test GET /geography/features/type/{type} for port, harbour, landing_centre, lighthouse."""
    pt = GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9])
    in_memory_repo.add_feature(
        GeoFeature(id="p-1", feature_type=GeoFeatureType.PORT, geometry=pt, name="Port A")
    )
    in_memory_repo.add_feature(
        GeoFeature(id="h-1", feature_type=GeoFeatureType.HARBOUR, geometry=pt, name="Harbour A")
    )
    in_memory_repo.add_feature(
        GeoFeature(
            id="lc-1",
            feature_type=GeoFeatureType.LANDING_CENTRE,
            geometry=pt,
            name="Landing Centre A",
        )
    )
    in_memory_repo.add_feature(
        GeoFeature(id="l-1", feature_type=GeoFeatureType.LIGHTHOUSE, geometry=pt, name="Light A")
    )

    resp_p = client.get("/geography/features/type/port")
    assert resp_p.status_code == 200
    assert resp_p.json()["total"] == 1
    assert resp_p.json()["features"][0]["feature_id"] == "p-1"

    resp_h = client.get("/geography/features/type/harbour")
    assert resp_h.status_code == 200
    assert resp_h.json()["total"] == 1
    assert resp_h.json()["features"][0]["feature_id"] == "h-1"

    resp_lc = client.get("/geography/features/type/landing_centre")
    assert resp_lc.status_code == 200
    assert resp_lc.json()["total"] == 1
    assert resp_lc.json()["features"][0]["feature_id"] == "lc-1"

    resp_l = client.get("/geography/features/type/lighthouse")
    assert resp_l.status_code == 200
    assert resp_l.json()["total"] == 1
    assert resp_l.json()["features"][0]["feature_id"] == "l-1"


def test_api_get_nearby_features_success(client, in_memory_repo):
    """Test GET /geography/nearby returns 200 OK with formatted nearby features."""
    f1 = GeoFeature(
        id="nearby_harbour_api",
        feature_type=GeoFeatureType.HARBOUR,
        name="Nearby Harbour",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.83, 18.92]),
        properties={"state": "Maharashtra"},
    )
    in_memory_repo.add_feature(f1)

    response = client.get("/geography/nearby?latitude=18.90&longitude=72.80&radius_km=30")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["origin_latitude"] == 18.90
    assert data["origin_longitude"] == 72.80
    assert data["radius_km"] == 30.0
    item = data["features"][0]
    assert item["feature"]["feature_id"] == "nearby_harbour_api"
    assert item["distance_km"] > 0.0
    assert item["distance_nm"] > 0.0
    assert "bearing_degrees" in item


def test_api_get_nearby_features_validation_errors(client):
    """Test GET /geography/nearby returns 422 for missing or invalid query parameters."""
    # Missing required coordinates
    resp1 = client.get("/geography/nearby")
    assert resp1.status_code == 422

    # Latitude out of bounds
    resp2 = client.get("/geography/nearby?latitude=999&longitude=72")
    assert resp2.status_code == 422

    # Radius <= 0
    resp3 = client.get("/geography/nearby?latitude=18.9&longitude=72.8&radius_km=0")
    assert resp3.status_code == 422
