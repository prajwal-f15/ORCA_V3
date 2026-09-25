"""Comprehensive test suite for Step 13: PFZ (Potential Fishing Zone) Model Integration."""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from app.adapters.pfz.base import IncoisPFZAdapter
from app.db.database import init_db
from app.main import app
from app.models.geography import GeoGeometry, GeometryType
from app.models.pfz import (
    PFZDatasetStatus,
    PFZFreshness,
    PFZObservation,
    PFZRouteTargetRequest,
    PFZRouteTargetResponse,
    PFZStatus,
    PFZZone,
)
from app.models.request import Coordinate, Vessel
from app.repositories.pfz_repository import (
    InMemoryPFZRepository,
    SQLitePFZRepository,
)
from app.services.pfz_service import (
    PFZService,
    PFZZoneNotFoundError,
    get_pfz_service,
)


@pytest.fixture
def temp_db(tmp_path):
    """Create a clean isolated SQLite database for PFZ testing."""
    db_file = str(tmp_path / "test_pfz.db")
    init_db(db_file)
    return db_file


@pytest.fixture
def sqlite_repo(temp_db):
    """Create SQLitePFZRepository instance bound to isolated database."""
    return SQLitePFZRepository(db_path=temp_db)


@pytest.fixture
def in_memory_repo():
    """Create InMemoryPFZRepository instance."""
    return InMemoryPFZRepository()


@pytest.fixture
def pfz_service(sqlite_repo):
    """Create PFZService with SQLite test repository."""
    return PFZService(repository=sqlite_repo)


@pytest.fixture
def client(pfz_service):
    """FastAPI TestClient with overridden PFZ service."""
    app.dependency_overrides[get_pfz_service] = lambda: pfz_service
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# ==============================================================================
# PART 1: PFZ DOMAIN MODELS & PROPERTY EXTRACTION TESTS
# ==============================================================================


def test_pfz_zone_point_model():
    """Verify PFZZone with Point geometry computes centroid and extracts properties."""
    zone = PFZZone(
        pfz_id="in_pfz_veraval_01",
        name="Veraval Offshore Zone 1",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[70.25, 20.85]),
        confidence=0.88,
        suitability_score=85.0,
        properties={
            "species": "Indian Mackerel / Ribbonfish",
            "sst": 28.4,
            "chlorophyll": 1.65,
            "depth_range": "30-60m",
        },
        source="INCOIS",
    )
    assert zone.pfz_id == "in_pfz_veraval_01"
    assert zone.id == "in_pfz_veraval_01"
    assert zone.geometry_type == "Point"
    assert zone.centroid is not None
    assert zone.latitude == 20.85
    assert zone.longitude == 70.25
    assert zone.species == "Indian Mackerel / Ribbonfish"
    assert zone.sst_celsius == 28.4
    assert zone.chlorophyll_mg_m3 == 1.65
    assert zone.depth_range == "30-60m"


def test_pfz_zone_polygon_centroid_computation():
    """Verify PFZZone with Polygon geometry automatically computes centroid coordinates."""
    poly_coords = [
        [
            [72.0, 18.0],
            [73.0, 18.0],
            [73.0, 19.0],
            [72.0, 19.0],
            [72.0, 18.0],
        ]
    ]
    zone = PFZZone(
        pfz_id="in_pfz_mumbai_poly_01",
        name="Mumbai High Pelagic Sector",
        geometry=GeoGeometry(type=GeometryType.POLYGON, coordinates=poly_coords),
        confidence=0.75,
        suitability_score=78.0,
    )
    assert zone.geometry_type == "Polygon"
    assert zone.centroid is not None
    assert zone.latitude == pytest.approx(18.4, 0.1)
    assert zone.longitude == pytest.approx(72.4, 0.1)


def test_pfz_observation_model():
    """Verify PFZObservation prediction model structure."""
    obs = PFZObservation(
        observation_id="obs_001",
        timestamp=datetime.now(timezone.utc),
        latitude=15.45,
        longitude=73.75,
        fish_potential_score=91.0,
        confidence=0.92,
        species="Sardine",
        sst_celsius=27.8,
        chlorophyll_mg_m3=2.1,
        source="INCOIS",
        model_version="INCOIS-PFZ-v3",
    )
    assert obs.observation_id == "obs_001"
    assert obs.fish_potential_score == 91.0
    assert obs.confidence == 0.92


# ==============================================================================
# PART 2: ADAPTER LAYER & PENDING DATA STATUS TESTS
# ==============================================================================


def test_incois_adapter_pending_state():
    """Verify IncoisPFZAdapter reports PENDING status when no official files are ingested."""
    adapter = IncoisPFZAdapter()
    status = adapter.get_feed_status()
    assert status.dataset_status == PFZDatasetStatus.PENDING
    assert status.freshness == PFZFreshness.PENDING
    assert status.feature_count == 0
    assert "Pending official dataset" in status.message


def test_incois_adapter_loaded_state():
    """Verify IncoisPFZAdapter reports AVAILABLE status when zones are loaded."""
    adapter = IncoisPFZAdapter()
    zone = PFZZone(
        pfz_id="pfz_test_01",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[70.0, 20.0]),
        confidence=0.8,
        suitability_score=75.0,
        valid_until=datetime.now(timezone.utc) + timedelta(days=2),
    )
    adapter.load_zones([zone])
    status = adapter.get_feed_status()
    assert status.dataset_status == PFZDatasetStatus.AVAILABLE
    assert status.freshness == PFZFreshness.FRESH
    assert status.feature_count == 1


# ==============================================================================
# PART 3: REPOSITORY LAYER (SQLITE & IN-MEMORY)
# ==============================================================================


def test_sqlite_repository_crud(sqlite_repo):
    """Test saving, retrieving, listing, and deleting PFZ zones in SQLite."""
    now = datetime.now(timezone.utc)
    zone1 = PFZZone(
        pfz_id="pfz_sql_01",
        name="Kochi Offshore Zone",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[76.0, 9.8]),
        confidence=0.90,
        suitability_score=88.0,
        valid_from=now,
        valid_until=now + timedelta(hours=36),
        source="INCOIS",
    )
    zone2 = PFZZone(
        pfz_id="pfz_sql_02",
        name="Goa Offshore Zone",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[73.5, 15.2]),
        confidence=0.60,
        suitability_score=62.0,
        valid_from=now,
        valid_until=now + timedelta(hours=36),
        source="INCOIS",
    )

    # Save
    sqlite_repo.save_zone(zone1)
    sqlite_repo.save_zone(zone2)
    assert sqlite_repo.count_zones() == 2

    # Get
    retrieved = sqlite_repo.get_zone("pfz_sql_01")
    assert retrieved is not None
    assert retrieved.name == "Kochi Offshore Zone"
    assert retrieved.confidence == 0.90
    assert retrieved.suitability_score == 88.0

    # Filter by confidence
    high_conf_zones, count = sqlite_repo.list_zones(min_confidence=0.80)
    assert count == 1
    assert high_conf_zones[0].pfz_id == "pfz_sql_01"

    # Delete
    assert sqlite_repo.delete_zone("pfz_sql_02") is True
    assert sqlite_repo.count_zones() == 1
    assert sqlite_repo.get_zone("pfz_sql_02") is None


def test_sqlite_repository_observations(sqlite_repo):
    """Test saving and retrieving PFZ prediction observations in SQLite."""
    obs = PFZObservation(
        observation_id="obs_sql_01",
        timestamp=datetime.now(timezone.utc),
        latitude=18.5,
        longitude=72.2,
        fish_potential_score=77.5,
        confidence=0.82,
        species="Tuna",
    )
    sqlite_repo.save_observation(obs)
    observations = sqlite_repo.get_observations()
    assert len(observations) == 1
    assert observations[0].observation_id == "obs_sql_01"
    assert observations[0].species == "Tuna"


# ==============================================================================
# PART 4: PFZ SERVICE NEARBY SEARCH & RANKING ALGORITHMS
# ==============================================================================


def test_pfz_service_nearby_zones(pfz_service):
    """Test finding nearby PFZ zones within radius."""
    # Add zones
    # Mumbai Coast (lat 18.9, lon 72.8)
    # Zone A: 30 km west of Mumbai (lat 18.9, lon 72.5) -> ~31.6 km
    # Zone B: 300 km south of Mumbai (lat 16.0, lon 73.0) -> ~325 km
    zone_a = PFZZone(
        pfz_id="zone_mumbai_near",
        name="Mumbai Close Sector",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.5, 18.9]),
        confidence=0.85,
        suitability_score=80.0,
    )
    zone_b = PFZZone(
        pfz_id="zone_mumbai_far",
        name="Goa Deep Sector",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[73.0, 16.0]),
        confidence=0.95,
        suitability_score=95.0,
    )
    pfz_service.save_zone(zone_a)
    pfz_service.save_zone(zone_b)

    # Search within 100 km radius
    nearby = pfz_service.find_nearby_zones(
        latitude=18.9220, longitude=72.8347, radius_km=100.0
    )
    assert len(nearby) == 1
    assert nearby[0].zone.pfz_id == "zone_mumbai_near"
    assert nearby[0].distance_km < 40.0
    assert nearby[0].distance_nm > 0.0
    assert nearby[0].bearing_degrees >= 0.0


def test_pfz_destination_scoring_formula(pfz_service):
    """Verify deterministic ranking formula across different routing objectives."""
    # Zone 1: Close (20 km), moderate suitability (70), high confidence (0.9)
    # Zone 2: Far (80 km), very high suitability (95), moderate confidence (0.7)
    origin_lat, origin_lon = 18.9, 72.8

    z_close = PFZZone(
        pfz_id="z_close",
        name="Close Moderate Zone",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.7, 18.7]),  # ~24 km
        confidence=0.90,
        suitability_score=70.0,
    )
    z_far = PFZZone(
        pfz_id="z_far",
        name="Far High Potential Zone",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.2, 18.3]),  # ~88 km
        confidence=0.70,
        suitability_score=95.0,
    )
    pfz_service.save_zone(z_close)
    pfz_service.save_zone(z_far)

    # 1. Objective: 'nearest_distance' should prioritize z_close
    req_nearest = PFZRouteTargetRequest(
        current_position=Coordinate(latitude=origin_lat, longitude=origin_lon),
        radius_km=100.0,
        objective="nearest_distance",
        vessel=Vessel(speed_knots=12.0),
    )
    res_nearest = pfz_service.get_best_pfz_targets(req_nearest)
    assert res_nearest.total_candidates == 2
    assert res_nearest.targets[0].pfz_id == "z_close"
    assert res_nearest.targets[0].estimated_travel_time_minutes is not None

    # 2. Objective: 'highest_potential' should prioritize z_far
    req_potential = PFZRouteTargetRequest(
        current_position=Coordinate(latitude=origin_lat, longitude=origin_lon),
        radius_km=100.0,
        objective="highest_potential",
        vessel=Vessel(speed_knots=12.0),
    )
    res_potential = pfz_service.get_best_pfz_targets(req_potential)
    assert res_potential.targets[0].pfz_id == "z_far"


# ==============================================================================
# PART 5: ROUTE ENGINE INTEGRATION & PENDING DATASET BEHAVIOR
# ==============================================================================


def test_pfz_empty_dataset_pending_behavior(pfz_service):
    """Verify Route Engine requesting PFZ targets when dataset is empty returns clean pending response."""
    # Ensure database is empty
    pfz_service._repository.clear()

    req = PFZRouteTargetRequest(
        current_position=Coordinate(latitude=18.9220, longitude=72.8347),
        radius_km=100.0,
    )
    res = pfz_service.get_best_pfz_targets(req)
    assert res.total_candidates == 0
    assert len(res.targets) == 0
    assert res.dataset_status == PFZDatasetStatus.PENDING


def test_pfz_safety_separation_principle(pfz_service):
    """Verify PFZ target returns destination coordinates without declaring final safety approval."""
    zone = PFZZone(
        pfz_id="pfz_high_potential",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.5, 18.5]),
        confidence=0.99,
        suitability_score=99.0,
    )
    pfz_service.save_zone(zone)

    req = PFZRouteTargetRequest(
        current_position=Coordinate(latitude=18.9, longitude=72.8),
        radius_km=100.0,
    )
    res = pfz_service.get_best_pfz_targets(req)
    target = res.targets[0]
    # PFZ outputs destination target for Route Engine & Safety Governor to evaluate
    assert target.destination.latitude == 18.5
    assert target.destination.longitude == 72.5
    assert target.ranking_score > 80.0


# ==============================================================================
# PART 6: API ENDPOINTS
# ==============================================================================


def test_api_get_pfz_status(client):
    """Test GET /pfz/status endpoint."""
    res = client.get("/pfz/status")
    assert res.status_code == 200
    data = res.json()
    assert "source" in data
    assert "dataset_status" in data


def test_api_pfz_zones_crud(client, pfz_service):
    """Test GET /pfz/zones and GET /pfz/zones/{pfz_id} endpoints."""
    zone = PFZZone(
        pfz_id="pfz_api_test_01",
        name="Mangalore Coastal PFZ",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[74.5, 12.8]),
        confidence=0.82,
        suitability_score=84.0,
    )
    pfz_service.save_zone(zone)

    # List
    res_list = client.get("/pfz/zones")
    assert res_list.status_code == 200
    assert res_list.json()["total"] == 1

    # Get by ID
    res_get = client.get("/pfz/zones/pfz_api_test_01")
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "Mangalore Coastal PFZ"

    # Get non-existent
    res_404 = client.get("/pfz/zones/unknown_id")
    assert res_404.status_code == 404


def test_api_pfz_zones_nearby(client, pfz_service):
    """Test GET /pfz/zones/nearby endpoint."""
    zone = PFZZone(
        pfz_id="pfz_api_nearby_01",
        name="Chennai Offshore PFZ",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[80.5, 13.1]),
        confidence=0.87,
        suitability_score=86.0,
    )
    pfz_service.save_zone(zone)

    res = client.get(
        "/pfz/zones/nearby",
        params={"latitude": 13.08, "longitude": 80.27, "radius_km": 50.0},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["zones"][0]["zone"]["pfz_id"] == "pfz_api_nearby_01"


def test_api_get_best_pfz(client, pfz_service):
    """Test GET /pfz/best and POST /pfz/best endpoints."""
    zone = PFZZone(
        pfz_id="pfz_best_01",
        name="Porbandar Pelagic Sector",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[69.3, 21.5]),
        confidence=0.89,
        suitability_score=91.0,
    )
    pfz_service.save_zone(zone)

    # 1. Test GET /pfz/best
    res_get = client.get(
        "/pfz/best",
        params={
            "latitude": 21.64,
            "longitude": 69.60,
            "radius_km": 100.0,
            "vessel_speed_knots": 12.5,
            "objective": "balanced",
        },
    )
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert data_get["total_candidates"] == 1
    assert data_get["targets"][0]["pfz_id"] == "pfz_best_01"

    # 2. Test POST /pfz/best
    payload = {
        "current_position": {"latitude": 21.64, "longitude": 69.60},
        "radius_km": 100.0,
        "vessel": {"speed_knots": 12.5},
        "objective": "highest_potential",
        "limit": 3,
    }
    res_post = client.post("/pfz/best", json=payload)
    assert res_post.status_code == 200
    data_post = res_post.json()
    assert data_post["total_candidates"] == 1
    assert data_post["targets"][0]["ranking_score"] > 0.0
