"""Comprehensive test suite for Step 12: Bathymetry + Restricted / No-Go Marine Areas."""

import pytest
from fastapi.testclient import TestClient
from app.db.database import get_db_connection, init_db
from app.main import app
from app.models.geography import (
    CoordinateRestrictionCheckResult,
    DepthQueryResult,
    GeoDataset,
    GeoFeature,
    GeoFeatureType,
    GeoGeometry,
    GeometryType,
    RouteRestrictionCheckResult,
    VesselDraftSafetyResult,
)
from app.models.request import Coordinate, Vessel
from app.repositories.geography_repository import SQLiteGeographyRepository
from app.services.marine_constraint_service import (
    MarineConstraintService,
    line_intersects_polygon_feature,
    point_in_feature_geometry,
    point_in_polygon_geometry,
    point_in_ring,
)


@pytest.fixture
def temp_db(tmp_path):
    """Create a clean isolated SQLite database for testing."""
    db_file = str(tmp_path / "test_bathymetry_restrictions.db")
    init_db(db_file)
    return db_file


@pytest.fixture
def geo_repo(temp_db):
    """Create a SQLiteGeographyRepository instance bound to isolated test database."""
    return SQLiteGeographyRepository(db_path=temp_db)


@pytest.fixture
def constraint_service(geo_repo):
    """Create MarineConstraintService with test repository."""
    return MarineConstraintService(repository=geo_repo)


@pytest.fixture
def test_client(geo_repo, constraint_service):
    """FastAPI TestClient configured with isolated repositories and services."""
    from app.services.geography_service import GeographyService, get_geography_service
    from app.services.marine_constraint_service import get_marine_constraint_service

    geo_service = GeographyService(repository=geo_repo)
    app.dependency_overrides[get_geography_service] = lambda: geo_service
    app.dependency_overrides[get_marine_constraint_service] = lambda: constraint_service

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ==============================================================================
# PART 1: BATHYMETRY MODEL & DEPTH PROPERTY EXTRACTION TESTS
# ==============================================================================


def test_bathymetry_feature_type_enum():
    """Verify GeoFeatureType.BATHYMETRY exists and is serialized correctly."""
    assert GeoFeatureType.BATHYMETRY == "bathymetry"
    assert GeoFeatureType.BATHYMETRY.value == "bathymetry"


def test_bathymetry_depth_extraction():
    """Verify GeoFeature extracts depth_meters, minimum_depth_meters, maximum_depth_meters from properties."""
    feat1 = GeoFeature(
        feature_id="depth_pt_01",
        feature_type=GeoFeatureType.BATHYMETRY,
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9]),
        properties={"depth_meters": 45.5, "min_depth": 40.0, "max_depth": 50.0},
        source="INCOIS",
    )
    assert feat1.depth_meters == 45.5
    assert feat1.minimum_depth_meters == 40.0
    assert feat1.maximum_depth_meters == 50.0

    # Negative elevation in DEM (e.g. -120m underwater) should be converted to positive depth
    feat2 = GeoFeature(
        feature_id="depth_dem_01",
        feature_type=GeoFeatureType.BATHYMETRY,
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[73.0, 15.5]),
        properties={"elevation": -120.0},
    )
    assert feat2.depth_meters == 120.0


def test_bathymetry_property_fallbacks():
    """Verify extraction handles various hydrographic naming conventions (sounding, contour, val, z)."""
    feat_sounding = GeoFeature(
        feature_id="snd_01",
        feature_type=GeoFeatureType.BATHYMETRY,
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[80.0, 13.0]),
        properties={"sounding": 18.2},
    )
    assert feat_sounding.depth_meters == 18.2

    feat_contour = GeoFeature(
        feature_id="cnt_01",
        feature_type=GeoFeatureType.BATHYMETRY,
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[80.0, 13.0]),
        properties={"contour": 200.0},
    )
    assert feat_contour.depth_meters == 200.0


# ==============================================================================
# PART 2: RESTRICTED AREA MODEL & RESTRICTION TYPE EXTRACTION TESTS
# ==============================================================================


def test_restricted_area_feature_type_enum():
    """Verify GeoFeatureType.RESTRICTED_AREA exists and is serialized correctly."""
    assert GeoFeatureType.RESTRICTED_AREA == "restricted_area"
    assert GeoFeatureType.RESTRICTED_AREA.value == "restricted_area"


def test_restricted_area_property_extraction():
    """Verify GeoFeature extracts restriction_type from various property keys."""
    feat = GeoFeature(
        feature_id="restr_mumbai_naval_01",
        feature_type=GeoFeatureType.RESTRICTED_AREA,
        name="Mumbai Naval Firing Range",
        geometry=GeoGeometry(
            type=GeometryType.POLYGON,
            coordinates=[
                [
                    [72.5, 18.8],
                    [72.7, 18.8],
                    [72.7, 19.0],
                    [72.5, 19.0],
                    [72.5, 18.8],
                ]
            ],
        ),
        properties={
            "restriction_type": "military_firing_range",
            "status": "prohibited",
            "legal_status": "official_notice_to_mariners",
        },
        source="Naval Hydrographic Department",
    )
    assert feat.restriction_type == "military_firing_range"
    assert feat.name == "Mumbai Naval Firing Range"
    assert feat.geometry_type == "Polygon"


# ==============================================================================
# PART 3: SPATIAL GEOMETRY ALGORITHMS (POINT-IN-POLYGON & INTERSECTIONS)
# ==============================================================================


def test_point_in_ring_algorithm():
    """Test ray-casting point-in-ring algorithm with interior, exterior, and boundary points."""
    # Box from lon 10 to 20, lat 10 to 20
    ring = [[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0], [10.0, 10.0]]

    # Center is inside
    assert point_in_ring(15.0, 15.0, ring) is True

    # Far outside
    assert point_in_ring(5.0, 15.0, ring) is False
    assert point_in_ring(25.0, 15.0, ring) is False
    assert point_in_ring(15.0, 5.0, ring) is False
    assert point_in_ring(15.0, 25.0, ring) is False


def test_point_in_polygon_with_holes():
    """Test point-in-polygon with outer boundary and interior hole."""
    outer = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    hole = [[3.0, 3.0], [7.0, 3.0], [7.0, 7.0], [3.0, 7.0], [3.0, 3.0]]
    poly_rings = [outer, hole]

    # In outer ring, outside hole -> Inside
    assert point_in_polygon_geometry(1.0, 1.0, poly_rings) is True

    # Inside hole -> Outside (hole punches out space)
    assert point_in_polygon_geometry(5.0, 5.0, poly_rings) is False

    # Outside outer ring -> Outside
    assert point_in_polygon_geometry(15.0, 5.0, poly_rings) is False


def test_line_intersects_polygon_feature():
    """Test line segment intersection with polygon restricted area."""
    feat = GeoFeature(
        feature_id="poly_box",
        feature_type=GeoFeatureType.RESTRICTED_AREA,
        geometry=GeoGeometry(
            type=GeometryType.POLYGON,
            coordinates=[
                [
                    [10.0, 10.0],
                    [20.0, 10.0],
                    [20.0, 20.0],
                    [10.0, 20.0],
                    [10.0, 10.0],
                ]
            ],
        ),
    )

    # Line crossing directly through polygon
    assert (
        line_intersects_polygon_feature(
            start_lon=5.0, start_lat=15.0, end_lon=25.0, end_lat=15.0, feature=feat
        )
        is True
    )

    # Line completely outside and clear
    assert (
        line_intersects_polygon_feature(
            start_lon=5.0, start_lat=5.0, end_lon=25.0, end_lat=5.0, feature=feat
        )
        is False
    )

    # Line starting inside polygon
    assert (
        line_intersects_polygon_feature(
            start_lon=15.0, start_lat=15.0, end_lon=25.0, end_lat=25.0, feature=feat
        )
        is True
    )


# ==============================================================================
# PART 4: MARINE CONSTRAINT SERVICE FUNCTIONALITY
# ==============================================================================


def test_marine_constraint_check_coordinate(geo_repo, constraint_service):
    """Test checking if a coordinate is inside restricted zones."""
    # Register restricted area
    restr_zone = GeoFeature(
        feature_id="restr_goa_marine_park",
        dataset_id="india_restricted_areas",
        feature_type=GeoFeatureType.RESTRICTED_AREA,
        name="Goa Marine Sanctuary Zone",
        geometry=GeoGeometry(
            type=GeometryType.POLYGON,
            coordinates=[
                [
                    [73.5, 15.0],
                    [74.0, 15.0],
                    [74.0, 15.5],
                    [73.5, 15.5],
                    [73.5, 15.0],
                ]
            ],
        ),
        properties={"restriction_type": "marine_protected_area"},
        source="Ministry of Environment, Forest and Climate Change",
    )
    geo_repo.add_feature(restr_zone)

    # Point inside sanctuary (lat 15.25, lon 73.75)
    res_inside = constraint_service.check_coordinate_restrictions(
        latitude=15.25, longitude=73.75
    )
    assert res_inside.is_restricted is True
    assert len(res_inside.matching_restrictions) == 1
    assert res_inside.matching_restrictions[0].feature_id == "restr_goa_marine_park"
    assert res_inside.highest_restriction_type == "marine_protected_area"

    # Point outside sanctuary (lat 16.0, lon 73.0)
    res_outside = constraint_service.check_coordinate_restrictions(
        latitude=16.0, longitude=73.0
    )
    assert res_outside.is_restricted is False
    assert len(res_outside.matching_restrictions) == 0


def test_marine_constraint_check_route(geo_repo, constraint_service):
    """Test checking route waypoints against restricted areas."""
    restr_zone = GeoFeature(
        feature_id="restr_corridor_01",
        dataset_id="india_restricted_areas",
        feature_type=GeoFeatureType.RESTRICTED_AREA,
        name="Restricted Firing Corridor",
        geometry=GeoGeometry(
            type=GeometryType.POLYGON,
            coordinates=[
                [
                    [72.0, 18.0],
                    [73.0, 18.0],
                    [73.0, 19.0],
                    [72.0, 19.0],
                    [72.0, 18.0],
                ]
            ],
        ),
        properties={"restriction_type": "military_prohibited_area"},
    )
    geo_repo.add_feature(restr_zone)

    # Route crossing from (lat 17.5, lon 72.5) to (lat 19.5, lon 72.5)
    waypoints_blocked = [
        Coordinate(latitude=17.5, longitude=72.5),
        Coordinate(latitude=19.5, longitude=72.5),
    ]
    res_blocked = constraint_service.check_route_restrictions(waypoints_blocked)
    assert res_blocked.has_restrictions is True
    assert res_blocked.restricted_segments_count == 1
    assert len(res_blocked.intersecting_restrictions) == 1
    assert len(res_blocked.warnings) == 1

    # Route avoiding the zone
    waypoints_clear = [
        Coordinate(latitude=17.5, longitude=71.0),
        Coordinate(latitude=19.5, longitude=71.0),
    ]
    res_clear = constraint_service.check_route_restrictions(waypoints_clear)
    assert res_clear.has_restrictions is False
    assert res_clear.restricted_segments_count == 0


def test_marine_constraint_get_depth(geo_repo, constraint_service):
    """Test bathymetry depth querying from soundings and polygon depth zones."""
    # Add point sounding
    sounding = GeoFeature(
        feature_id="sounding_mumbai_shelf_01",
        dataset_id="india_bathymetry",
        feature_type=GeoFeatureType.BATHYMETRY,
        name="Mumbai Continental Shelf Sounding",
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.5, 18.5]),
        properties={"depth_meters": 38.0},
        source="National Hydrographic Office",
    )
    geo_repo.add_feature(sounding)

    # Query near sounding (within 10 km)
    res_near = constraint_service.get_depth_at_coordinate(
        latitude=18.52, longitude=72.52, search_radius_km=25.0
    )
    assert res_near.depth_meters == 38.0
    assert res_near.confidence in ("exact", "nearest_sounding")
    assert res_near.distance_to_sounding_km is not None
    assert res_near.distance_to_sounding_km < 10.0

    # Query far from sounding (outside 25 km radius)
    res_far = constraint_service.get_depth_at_coordinate(
        latitude=20.0, longitude=70.0, search_radius_km=25.0
    )
    assert res_far.depth_meters is None
    assert res_far.confidence == "none"


def test_marine_constraint_vessel_draft_validation(geo_repo, constraint_service):
    """Test vessel draft and under-keel clearance safety calculation."""
    sounding = GeoFeature(
        feature_id="snd_shallow_bay",
        dataset_id="india_bathymetry",
        feature_type=GeoFeatureType.BATHYMETRY,
        geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[73.0, 16.0]),
        properties={"depth_meters": 4.0},
    )
    geo_repo.add_feature(sounding)

    # 1. Draft 2.0m in 4.0m water with 1.0m margin -> SAFE (UKC = 2.0m >= 1.0m)
    res_safe = constraint_service.validate_vessel_draft(
        latitude=16.0, longitude=73.0, vessel_draft_meters=2.0, safety_margin_meters=1.0
    )
    assert res_safe.is_safe is True
    assert res_safe.status == "SAFE"
    assert res_safe.under_keel_clearance_meters == 2.0

    # 2. Draft 3.5m in 4.0m water with 1.0m margin -> WARNING (UKC = 0.5m < 1.0m)
    res_warn = constraint_service.validate_vessel_draft(
        latitude=16.0, longitude=73.0, vessel_draft_meters=3.5, safety_margin_meters=1.0
    )
    assert res_warn.is_safe is False
    assert res_warn.status == "WARNING"
    assert res_warn.under_keel_clearance_meters == 0.5

    # 3. Draft 5.0m in 4.0m water -> CRITICAL_DEPTH (Grounding hazard)
    res_crit = constraint_service.validate_vessel_draft(
        latitude=16.0, longitude=73.0, vessel_draft_meters=5.0
    )
    assert res_crit.is_safe is False
    assert res_crit.status == "CRITICAL_DEPTH"

    # 4. Unknown depth area -> UNKNOWN_DEPTH, is_safe=True (backward compatible)
    res_unknown = constraint_service.validate_vessel_draft(
        latitude=10.0, longitude=80.0, vessel_draft_meters=3.0
    )
    assert res_unknown.is_safe is True
    assert res_unknown.status == "UNKNOWN_DEPTH"


# ==============================================================================
# PART 5: VESSEL MODEL EXTENSION (STEP 12 BACKWARD COMPATIBILITY)
# ==============================================================================


def test_vessel_draft_optional_fields():
    """Verify Vessel model supports optional draft_meters and minimum_safe_depth_meters."""
    # Default without draft
    v1 = Vessel(speed_knots=12.0)
    assert v1.draft_meters is None
    assert v1.minimum_safe_depth_meters is None

    # Configured vessel draft
    v2 = Vessel(
        speed_knots=14.5,
        draft_meters=3.2,
        minimum_safe_depth_meters=5.0,
    )
    assert v2.draft_meters == 3.2
    assert v2.minimum_safe_depth_meters == 5.0


# ==============================================================================
# PART 6: API ENDPOINTS FOR BATHYMETRY & RESTRICTIONS
# ==============================================================================


def test_api_list_bathymetry_and_restrictions(test_client, geo_repo):
    """Test GET /geography/features/type/bathymetry and restricted_area."""
    # List when empty
    res_bathy_empty = test_client.get("/geography/features/type/bathymetry")
    assert res_bathy_empty.status_code == 200
    assert res_bathy_empty.json()["total"] == 0

    res_restr_empty = test_client.get("/geography/features/type/restricted_area")
    assert res_restr_empty.status_code == 200
    assert res_restr_empty.json()["total"] == 0

    # Add features
    geo_repo.add_feature(
        GeoFeature(
            feature_id="bathy_api_01",
            feature_type=GeoFeatureType.BATHYMETRY,
            geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[72.8, 18.9]),
            properties={"depth_meters": 55.0},
        )
    )
    geo_repo.add_feature(
        GeoFeature(
            feature_id="restr_api_01",
            feature_type=GeoFeatureType.RESTRICTED_AREA,
            name="Naval Safety Zone",
            geometry=GeoGeometry(
                type=GeometryType.POLYGON,
                coordinates=[
                    [[72.0, 18.0], [73.0, 18.0], [73.0, 19.0], [72.0, 19.0], [72.0, 18.0]]
                ],
            ),
            properties={"restriction_type": "naval_exercise_zone"},
        )
    )

    res_bathy = test_client.get("/geography/features/type/bathymetry")
    assert res_bathy.status_code == 200
    assert res_bathy.json()["total"] == 1

    res_restr = test_client.get("/geography/features/type/restricted_area")
    assert res_restr.status_code == 200
    assert res_restr.json()["total"] == 1


def test_api_check_coordinate_restrictions(test_client, geo_repo):
    """Test GET /geography/restrictions/check endpoint."""
    geo_repo.add_feature(
        GeoFeature(
            feature_id="restr_mumbai_harbour_limit",
            feature_type=GeoFeatureType.RESTRICTED_AREA,
            name="Mumbai Harbour Regulated Zone",
            geometry=GeoGeometry(
                type=GeometryType.POLYGON,
                coordinates=[
                    [[72.7, 18.8], [72.9, 18.8], [72.9, 19.1], [72.7, 19.1], [72.7, 18.8]]
                ],
            ),
            properties={"restriction_type": "traffic_separation_zone"},
        )
    )

    # Test coordinate inside
    res_in = test_client.get(
        "/geography/restrictions/check",
        params={"latitude": 18.95, "longitude": 72.82},
    )
    assert res_in.status_code == 200
    data_in = res_in.json()
    assert data_in["is_restricted"] is True
    assert len(data_in["matching_restrictions"]) == 1

    # Test coordinate outside
    res_out = test_client.get(
        "/geography/restrictions/check",
        params={"latitude": 15.0, "longitude": 70.0},
    )
    assert res_out.status_code == 200
    data_out = res_out.json()
    assert data_out["is_restricted"] is False


def test_api_check_route_restrictions(test_client, geo_repo):
    """Test POST /geography/restrictions/check-route endpoint."""
    geo_repo.add_feature(
        GeoFeature(
            feature_id="restr_channel_01",
            feature_type=GeoFeatureType.RESTRICTED_AREA,
            name="Restricted Shipping Channel",
            geometry=GeoGeometry(
                type=GeometryType.POLYGON,
                coordinates=[
                    [[72.5, 18.0], [73.5, 18.0], [73.5, 18.5], [72.5, 18.5], [72.5, 18.0]]
                ],
            ),
            properties={"restriction_type": "restricted_channel"},
        )
    )

    payload = {
        "coordinates": [
            {"latitude": 17.0, "longitude": 73.0},
            {"latitude": 19.0, "longitude": 73.0},
        ],
        "vessel_draft_meters": 3.0,
    }

    res = test_client.post("/geography/restrictions/check-route", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["has_restrictions"] is True
    assert data["restricted_segments_count"] == 1


def test_api_get_depth_and_validate_draft(test_client, geo_repo):
    """Test GET /geography/depth and GET /geography/depth/validate-draft endpoints."""
    geo_repo.add_feature(
        GeoFeature(
            feature_id="sounding_chennai_01",
            feature_type=GeoFeatureType.BATHYMETRY,
            geometry=GeoGeometry(type=GeometryType.POINT, coordinates=[80.3, 13.1]),
            properties={"depth_meters": 16.5},
        )
    )

    # 1. Query depth
    res_depth = test_client.get(
        "/geography/depth", params={"latitude": 13.1, "longitude": 80.3}
    )
    assert res_depth.status_code == 200
    assert res_depth.json()["depth_meters"] == 16.5

    # 2. Validate draft
    res_draft = test_client.get(
        "/geography/depth/validate-draft",
        params={"latitude": 13.1, "longitude": 80.3, "draft_meters": 2.5},
    )
    assert res_draft.status_code == 200
    assert res_draft.json()["is_safe"] is True
    assert res_draft.json()["status"] == "SAFE"
