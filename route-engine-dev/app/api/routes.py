from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.models.geography import (
    CoordinateRestrictionCheckResult,
    DepthQueryResult,
    GeoDatasetListResponse,
    GeoDatasetMetadata,
    GeoFeature,
    GeoFeatureListResponse,
    GeoNearbyFeature,
    GeoNearbyResponse,
    RouteRestrictionCheckRequest,
    RouteRestrictionCheckResult,
    VesselDraftSafetyResult,
)
from app.models.marine_conditions import MarineConditionsSnapshot
from app.models.pfz import (
    PFZNearbyResponse,
    PFZRouteTargetRequest,
    PFZRouteTargetResponse,
    PFZStatus,
    PFZZone,
    PFZZoneListResponse,
)
from app.models.request import Coordinate, NavigationRequest, RouteRequest, Vessel
from app.models.response import HealthResponse, NavigationState, RouteResponse
from app.models.trip import (
    ReturnCancelResponse,
    ReturnNavigationState,
    ReturnTripRequest,
    ReturnUpdateRequest,
    TripDeleteResponse,
    TripHistoryResponse,
    TripResponse,
    TripStartRequest,
    TripStopRequest,
    TripSummary,
    TripTrackResponse,
    TripUpdateRequest,
)
from app.services.geography_service import (
    DatasetNotFoundError,
    FeatureNotFoundError,
    GeographyService,
    InvalidFeatureTypeError,
    get_geography_service,
)
from app.services.marine_conditions_service import (
    MarineConditionsService,
    get_marine_conditions_service,
)
from app.services.marine_constraint_service import (
    MarineConstraintService,
    get_marine_constraint_service,
)
from app.services.pfz_service import (
    PFZService,
    PFZZoneNotFoundError,
    get_pfz_service,
)
from app.models.safety import SafetyCheckResult, SafetyEvaluationRequest
from app.models.provider import SystemProvidersStatusResponse
from app.services.provider_status_service import (
    ProviderStatusService,
    get_provider_status_service,
)
from app.services.safety_governor_service import (
    SafetyGovernorService,
    get_safety_governor_service,
)
from app.services.route_service import RouteService, get_route_service
from app.services.return_service import ReturnNavigationNotActiveError
from app.services.trip_service import (
    InvalidTimestampError,
    TripInactiveError,
    TripNotFoundError,
    TripService,
    get_trip_service,
)

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Check if the route engine service is up and operational.",
    tags=["System"],
)
async def health_check() -> HealthResponse:
    """Return health status of the service."""
    return HealthResponse(status="ok", service="orca-route-engine")


@router.get(
    "/readiness",
    summary="Application Readiness Probe",
    description="Check whether the application is fully initialized and ready to process route calculations.",
    tags=["System"],
)
async def readiness_probe() -> dict:
    """Return readiness status indicating database and services are initialized."""
    return {"status": "ready", "service": "orca-route-engine"}


@router.get(
    "/provider-status",
    response_model=SystemProvidersStatusResponse,
    summary="External Provider Availability Status",
    description="Return operational status of external data feed providers (Ocean, Weather, PFZ, Geography) without exposing credentials.",
    tags=["System"],
)
async def provider_status_check(
    provider_service: ProviderStatusService = Depends(get_provider_status_service),
) -> SystemProvidersStatusResponse:
    """Return aggregated health and configuration status for all external integrations."""
    return provider_service.get_system_status()


@router.post(
    "/route",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Calculate Maritime Route",
    description="Calculate and optimize a maritime voyage route based on origin, destination, vessel constraints, and objectives.",
    tags=["Routing"],
)
async def calculate_route(
    request: RouteRequest,
    route_service: RouteService = Depends(get_route_service),
) -> RouteResponse:
    """Validate request through Pydantic models and compute route via RouteService."""
    return route_service.calculate_route(request)


@router.post(
    "/navigation/state",
    response_model=NavigationState,
    status_code=status.HTTP_200_OK,
    summary="Get Vessel Navigation State",
    description="Calculate live navigation state including remaining distance, ETA, bearing, progress, and next waypoint.",
    tags=["Navigation"],
)
async def get_navigation_state(
    request: NavigationRequest,
    route_service: RouteService = Depends(get_route_service),
) -> NavigationState:
    """Validate navigation request and calculate current navigation state via RouteService."""
    return route_service.calculate_navigation_state(request)


# =============================================================================
# TRIP TRACKING ENDPOINTS
# =============================================================================


@router.post(
    "/trips/start",
    response_model=TripResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a New Voyage Trip",
    description="Initialize a new vessel trip, storing origin, destination, planned waypoints, and initial GPS position.",
    tags=["Trip Tracking"],
)
async def start_trip(
    request: TripStartRequest,
    trip_service: TripService = Depends(get_trip_service),
) -> TripResponse:
    """Initialize a trip and return initial tracking state."""
    return trip_service.start_trip(request)


@router.post(
    "/trips/{trip_id}/update",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="Record GPS Position Update",
    description="Record a live GPS coordinate update, accumulating segment distance and updating navigation state.",
    tags=["Trip Tracking"],
)
async def update_trip(
    trip_id: str,
    request: TripUpdateRequest,
    trip_service: TripService = Depends(get_trip_service),
) -> TripResponse:
    """Record incremental GPS track point for active trip."""
    try:
        return trip_service.update_trip(trip_id, request)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (TripInactiveError, InvalidTimestampError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/trips/{trip_id}/stop",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop and Complete a Trip",
    description="Finalize an active trip, recording optional final GPS point and marking voyage as completed.",
    tags=["Trip Tracking"],
)
async def stop_trip(
    trip_id: str,
    request: TripStopRequest = None,
    trip_service: TripService = Depends(get_trip_service),
) -> TripResponse:
    """Stop an active trip and compute final voyage metrics."""
    try:
        return trip_service.stop_trip(trip_id, request)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (TripInactiveError, InvalidTimestampError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/trips",
    response_model=TripHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List Saved Trip History",
    description="Retrieve a paginated list of recorded voyages with optional status filtering.",
    tags=["Trip Tracking"],
)
async def list_trips(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    trip_service: TripService = Depends(get_trip_service),
) -> TripHistoryResponse:
    """Retrieve paginated voyage history."""
    return trip_service.list_trips(status=status, limit=limit, offset=offset)


@router.get(
    "/trips/{trip_id}",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Full Trip Details",
    description="Retrieve the complete tracking record, distance travelled, track point count, and live navigation state.",
    tags=["Trip Tracking"],
)
async def get_trip(
    trip_id: str,
    trip_service: TripService = Depends(get_trip_service),
) -> TripResponse:
    """Retrieve full details of a recorded trip."""
    try:
        return trip_service.get_trip(trip_id)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/trips/{trip_id}/summary",
    response_model=TripSummary,
    status_code=status.HTTP_200_OK,
    summary="Get High-Level Trip Summary",
    description="Retrieve high-level summary metrics for a voyage including total distance, elapsed time, and status.",
    tags=["Trip Tracking"],
)
async def get_trip_summary(
    trip_id: str,
    trip_service: TripService = Depends(get_trip_service),
) -> TripSummary:
    """Retrieve summarized metrics of a trip."""
    try:
        return trip_service.get_trip_summary(trip_id)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/trips/{trip_id}/track",
    response_model=TripTrackResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Ordered Trip Track Points",
    description="Retrieve full list of ordered GPS coordinates recorded for the trip in chronological sequence.",
    tags=["Trip Tracking"],
)
async def get_trip_track(
    trip_id: str,
    trip_service: TripService = Depends(get_trip_service),
) -> TripTrackResponse:
    """Retrieve ordered track points of a voyage."""
    try:
        return trip_service.get_trip_track(trip_id)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete(
    "/trips/{trip_id}",
    response_model=TripDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a Trip",
    description="Delete a trip and cascade delete all associated GPS track points.",
    tags=["Trip Tracking"],
)
async def delete_trip(
    trip_id: str,
    trip_service: TripService = Depends(get_trip_service),
) -> TripDeleteResponse:
    """Delete a recorded trip by ID."""
    try:
        return trip_service.delete_trip(trip_id)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# =============================================================================
# RETURN NAVIGATION ENDPOINTS
# =============================================================================


@router.post(
    "/trips/{trip_id}/return/start",
    response_model=ReturnNavigationState,
    status_code=status.HTTP_200_OK,
    summary="Start Return-to-Start or Return-to-Harbour Navigation",
    description="Switch an active voyage to return navigation mode heading to original start or harbour.",
    tags=["Return Navigation"],
)
async def start_return(
    trip_id: str,
    request: ReturnTripRequest,
    trip_service: TripService = Depends(get_trip_service),
) -> ReturnNavigationState:
    """Start return navigation for an active trip."""
    try:
        return trip_service.start_return(trip_id, request)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (TripInactiveError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/trips/{trip_id}/return/update",
    response_model=ReturnNavigationState,
    status_code=status.HTTP_200_OK,
    summary="Update GPS Position During Return Navigation",
    description="Record a GPS coordinate update during return navigation, accumulating distance and updating return ETA/bearing.",
    tags=["Return Navigation"],
)
async def update_return(
    trip_id: str,
    request: ReturnUpdateRequest,
    trip_service: TripService = Depends(get_trip_service),
) -> ReturnNavigationState:
    """Record GPS update for active return navigation."""
    try:
        return trip_service.update_return(trip_id, request)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ReturnNavigationNotActiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (TripInactiveError, InvalidTimestampError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/trips/{trip_id}/return/cancel",
    response_model=ReturnCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel Return Navigation",
    description="Cancel active return navigation and return to normal destination navigation mode.",
    tags=["Return Navigation"],
)
async def cancel_return(
    trip_id: str,
    trip_service: TripService = Depends(get_trip_service),
) -> ReturnCancelResponse:
    """Cancel return navigation for an active trip."""
    try:
        return trip_service.cancel_return(trip_id)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ReturnNavigationNotActiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except TripInactiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/trips/{trip_id}/return",
    response_model=ReturnNavigationState,
    status_code=status.HTTP_200_OK,
    summary="Get Active Return Navigation State",
    description="Retrieve the current return navigation state for an active trip.",
    tags=["Return Navigation"],
)
async def get_return_state(
    trip_id: str,
    trip_service: TripService = Depends(get_trip_service),
) -> ReturnNavigationState:
    """Retrieve return navigation metrics for a trip."""
    try:
        return trip_service.get_return_state(trip_id)
    except TripNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ReturnNavigationNotActiveError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# =============================================================================
# GEOGRAPHY & SPATIAL DATA ENDPOINTS
# =============================================================================


@router.get(
    "/geography/datasets",
    response_model=GeoDatasetListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Registered Marine Geographic Datasets",
    description="Retrieve list of registered geographic dataset metadata descriptors for India coastal and marine domains.",
    tags=["Geography"],
)
async def list_datasets(
    geography_service: GeographyService = Depends(get_geography_service),
) -> GeoDatasetListResponse:
    """Retrieve registered dataset descriptors."""
    datasets = geography_service.get_datasets()
    return GeoDatasetListResponse(datasets=datasets, total=len(datasets))


@router.get(
    "/geography/datasets/{dataset_id}",
    response_model=GeoDatasetMetadata,
    status_code=status.HTTP_200_OK,
    summary="Get Single Geographic Dataset Metadata",
    description="Retrieve metadata descriptor for a specific registered marine geographic dataset by ID.",
    tags=["Geography"],
)
async def get_dataset(
    dataset_id: str,
    geography_service: GeographyService = Depends(get_geography_service),
) -> GeoDatasetMetadata:
    """Retrieve metadata for a specific dataset."""
    try:
        dataset = geography_service.get_dataset(dataset_id)
        return dataset.to_metadata()
    except DatasetNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/geography/features",
    response_model=GeoFeatureListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Geographic Features",
    description="Query geographic features with optional category or dataset filter and pagination.",
    tags=["Geography"],
)
async def list_features(
    dataset_id: Optional[str] = Query(
        None,
        description="Filter by parent dataset identifier (e.g. india_coastline, india_eez)",
    ),
    feature_type: Optional[str] = Query(
        None,
        description="Filter by geographic feature type (e.g. coastline, port, harbour, eez, marine_area, etc.)",
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of features to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    geography_service: GeographyService = Depends(get_geography_service),
) -> GeoFeatureListResponse:
    """List geographic features with optional dataset/type filter and pagination."""
    try:
        features, total = geography_service.list_features(
            dataset_id=dataset_id, feature_type=feature_type, limit=limit, offset=offset
        )
        return GeoFeatureListResponse(
            features=features, total=total, limit=limit, offset=offset
        )
    except InvalidFeatureTypeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/geography/features/type/{feature_type}",
    response_model=GeoFeatureListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Geographic Features by Type",
    description="Query geographic features of a specific category type with pagination.",
    tags=["Geography"],
)
async def list_features_by_type(
    feature_type: str,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of features to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    geography_service: GeographyService = Depends(get_geography_service),
) -> GeoFeatureListResponse:
    """Query features by specific feature type."""
    try:
        features, total = geography_service.get_features_by_type(
            feature_type=feature_type, limit=limit, offset=offset
        )
        return GeoFeatureListResponse(
            features=features, total=total, limit=limit, offset=offset
        )
    except InvalidFeatureTypeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/geography/features/{feature_id}",
    response_model=GeoFeature,
    status_code=status.HTTP_200_OK,
    summary="Get Single Geographic Feature",
    description="Retrieve a single geographic feature by its unique feature identifier.",
    tags=["Geography"],
)
async def get_feature(
    feature_id: str,
    geography_service: GeographyService = Depends(get_geography_service),
) -> GeoFeature:
    """Retrieve a single geographic feature by ID."""
    try:
        return geography_service.get_feature(feature_id)
    except FeatureNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/geography/nearby",
    response_model=GeoNearbyResponse,
    status_code=status.HTTP_200_OK,
    summary="Find Nearby Marine Geographic Features",
    description="Locate nearby ports, harbours, landing centres, or lighthouses within a specified radius using authoritative Haversine calculations.",
    tags=["Geography"],
)
async def find_nearby(
    latitude: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description="Reference or vessel latitude in decimal degrees (-90 to 90)",
        examples=[18.9220],
    ),
    longitude: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description="Reference or vessel longitude in decimal degrees (-180 to 180)",
        examples=[72.8347],
    ),
    feature_type: Optional[str] = Query(
        None,
        description="Optional category filter (port, harbour, landing_centre, lighthouse, etc.)",
    ),
    dataset_id: Optional[str] = Query(
        None,
        description="Optional dataset filter (e.g. india_ports, india_harbours)",
    ),
    radius_km: float = Query(
        50.0,
        gt=0.0,
        le=20000.0,
        description="Search radius in kilometers",
        examples=[50.0],
    ),
    limit: int = Query(
        50,
        ge=1,
        le=500,
        description="Maximum number of nearby features to return",
    ),
    geography_service: GeographyService = Depends(get_geography_service),
) -> GeoNearbyResponse:
    """Find nearby geographic features within a given search radius."""
    try:
        nearby_items = geography_service.find_nearby_features(
            latitude=latitude,
            longitude=longitude,
            feature_type=feature_type,
            dataset_id=dataset_id,
            radius_km=radius_km,
            limit=limit,
        )
        return GeoNearbyResponse(
            origin_latitude=latitude,
            origin_longitude=longitude,
            radius_km=radius_km,
            total=len(nearby_items),
            features=nearby_items,
        )
    except (InvalidFeatureTypeError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/geography/restrictions/check",
    response_model=CoordinateRestrictionCheckResult,
    status_code=status.HTTP_200_OK,
    summary="Check Coordinate for Marine Restrictions",
    description="Inspect whether a given GPS coordinate is located inside any restricted or no-go marine zones.",
    tags=["Marine Safety & Constraints"],
)
async def check_coordinate_restriction(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (-180 to 180)"
    ),
    marine_constraint_service: MarineConstraintService = Depends(
        get_marine_constraint_service
    ),
) -> CoordinateRestrictionCheckResult:
    """Check if GPS coordinate intersects any restricted or no-go marine areas."""
    try:
        return marine_constraint_service.check_coordinate_restrictions(
            latitude=latitude, longitude=longitude
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/geography/restrictions/nearby",
    response_model=GeoNearbyResponse,
    status_code=status.HTTP_200_OK,
    summary="Find Nearby Restricted Marine Areas",
    description="Locate restricted or no-go marine areas within a specified radius of a reference coordinate.",
    tags=["Marine Safety & Constraints"],
)
async def find_nearby_restrictions(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (-180 to 180)"
    ),
    radius_km: float = Query(
        50.0, gt=0.0, le=20000.0, description="Search radius in kilometers"
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of features to return"),
    marine_constraint_service: MarineConstraintService = Depends(
        get_marine_constraint_service
    ),
) -> GeoNearbyResponse:
    """Find nearby restricted marine zones within a search radius."""
    try:
        nearby_items = marine_constraint_service.get_nearby_restricted_areas(
            latitude=latitude, longitude=longitude, radius_km=radius_km, limit=limit
        )
        return GeoNearbyResponse(
            origin_latitude=latitude,
            origin_longitude=longitude,
            radius_km=radius_km,
            total=len(nearby_items),
            features=nearby_items,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/geography/restrictions/check-route",
    response_model=RouteRestrictionCheckResult,
    status_code=status.HTTP_200_OK,
    summary="Check Route Sequence Against Restricted Areas",
    description="Inspect a sequence of planned route coordinates to detect if any line segments cross restricted or no-go marine zones.",
    tags=["Marine Safety & Constraints"],
)
async def check_route_restrictions(
    payload: RouteRestrictionCheckRequest,
    marine_constraint_service: MarineConstraintService = Depends(
        get_marine_constraint_service
    ),
) -> RouteRestrictionCheckResult:
    """Check full route waypoints against restricted marine zones."""
    return marine_constraint_service.check_route_restrictions(
        waypoints=payload.coordinates,
        vessel_draft_meters=payload.vessel_draft_meters,
        buffer_distance_km=payload.buffer_distance_km,
    )


@router.get(
    "/geography/bathymetry/nearby",
    response_model=GeoNearbyResponse,
    status_code=status.HTTP_200_OK,
    summary="Find Nearby Bathymetry Soundings",
    description="Locate bathymetric depth sounding points near a coordinate within a specified radius.",
    tags=["Marine Safety & Constraints"],
)
async def find_nearby_bathymetry(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (-180 to 180)"
    ),
    radius_km: float = Query(
        50.0, gt=0.0, le=20000.0, description="Search radius in kilometers"
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of features to return"),
    marine_constraint_service: MarineConstraintService = Depends(
        get_marine_constraint_service
    ),
) -> GeoNearbyResponse:
    """Find nearby bathymetry sounding points within a search radius."""
    try:
        nearby_items = marine_constraint_service.get_nearby_bathymetry(
            latitude=latitude, longitude=longitude, radius_km=radius_km, limit=limit
        )
        return GeoNearbyResponse(
            origin_latitude=latitude,
            origin_longitude=longitude,
            radius_km=radius_km,
            total=len(nearby_items),
            features=nearby_items,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/geography/depth",
    response_model=DepthQueryResult,
    status_code=status.HTTP_200_OK,
    summary="Query Bathymetric Sea Depth at Coordinate",
    description="Get sea depth in meters from polygon depth zones or nearest point soundings.",
    tags=["Marine Safety & Constraints"],
)
async def get_depth_at_coordinate(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (-180 to 180)"
    ),
    radius_km: float = Query(
        25.0, gt=0.0, le=500.0, description="Search radius for nearest soundings in km"
    ),
    marine_constraint_service: MarineConstraintService = Depends(
        get_marine_constraint_service
    ),
) -> DepthQueryResult:
    """Query sea depth / sounding at a given GPS coordinate."""
    try:
        return marine_constraint_service.get_depth_at_coordinate(
            latitude=latitude, longitude=longitude, search_radius_km=radius_km
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/geography/depth/validate-draft",
    response_model=VesselDraftSafetyResult,
    status_code=status.HTTP_200_OK,
    summary="Validate Vessel Draft Safety",
    description="Validate vessel draft and calculate under-keel clearance against sea depth at a location.",
    tags=["Marine Safety & Constraints"],
)
async def validate_vessel_draft(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (-180 to 180)"
    ),
    draft_meters: float = Query(
        ..., gt=0.0, description="Vessel draft (submerged depth) in meters"
    ),
    min_safe_depth: Optional[float] = Query(
        None, gt=0.0, description="Optional minimum required depth in meters"
    ),
    safety_margin: float = Query(
        1.0, ge=0.0, description="Under-keel clearance safety margin in meters (default 1.0m)"
    ),
    marine_constraint_service: MarineConstraintService = Depends(
        get_marine_constraint_service
    ),
) -> VesselDraftSafetyResult:
    """Validate vessel draft and under-keel clearance at a given coordinate."""
    try:
        return marine_constraint_service.validate_vessel_draft(
            latitude=latitude,
            longitude=longitude,
            vessel_draft_meters=draft_meters,
            minimum_safe_depth_meters=min_safe_depth,
            safety_margin_meters=safety_margin,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# PFZ (POTENTIAL FISHING ZONE) API ENDPOINTS (STEP 13)
# ==============================================================================


@router.get(
    "/pfz/status",
    response_model=PFZStatus,
    status_code=status.HTTP_200_OK,
    summary="Get PFZ Feed & Advisory Status",
    description="Retrieve operational availability, advisory freshness, and feature counts of the PFZ data feed.",
    tags=["Potential Fishing Zones (PFZ)"],
)
async def get_pfz_status(
    pfz_service: PFZService = Depends(get_pfz_service),
) -> PFZStatus:
    """Query current PFZ dataset availability and freshness."""
    return pfz_service.get_pfz_status()


@router.get(
    "/pfz/zones",
    response_model=PFZZoneListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Registered PFZ Zones",
    description="Query registered Potential Fishing Zone advisories with optional confidence and validity filters.",
    tags=["Potential Fishing Zones (PFZ)"],
)
async def list_pfz_zones(
    limit: int = Query(50, ge=1, le=500, description="Maximum number of zones to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    min_confidence: Optional[float] = Query(
        None, ge=0.0, le=1.0, description="Optional minimum confidence threshold (0.0 to 1.0)"
    ),
    valid_only: bool = Query(
        False, description="If true, only return active non-expired advisories"
    ),
    pfz_service: PFZService = Depends(get_pfz_service),
) -> PFZZoneListResponse:
    """List registered PFZ zones."""
    zones, total = pfz_service.list_zones(
        limit=limit,
        offset=offset,
        min_confidence=min_confidence,
        valid_only=valid_only,
    )
    return PFZZoneListResponse(zones=zones, total=total, limit=limit, offset=offset)


@router.get(
    "/pfz/zones/nearby",
    response_model=PFZNearbyResponse,
    status_code=status.HTTP_200_OK,
    summary="Find Nearby PFZ Zones",
    description="Locate Potential Fishing Zones within a search radius of a vessel or reference coordinate.",
    tags=["Potential Fishing Zones (PFZ)"],
)
async def find_nearby_pfz_zones(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Reference latitude (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Reference longitude (-180 to 180)"
    ),
    radius_km: float = Query(
        100.0, gt=0.0, le=2000.0, description="Search radius in kilometers"
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of zones to return"),
    min_confidence: Optional[float] = Query(
        None, ge=0.0, le=1.0, description="Optional minimum confidence threshold (0.0 to 1.0)"
    ),
    pfz_service: PFZService = Depends(get_pfz_service),
) -> PFZNearbyResponse:
    """Find nearby PFZ zones within a search radius."""
    try:
        nearby_items = pfz_service.find_nearby_zones(
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            limit=limit,
            min_confidence=min_confidence,
        )
        return PFZNearbyResponse(
            origin_latitude=latitude,
            origin_longitude=longitude,
            radius_km=radius_km,
            total=len(nearby_items),
            zones=nearby_items,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/pfz/zones/{pfz_id}",
    response_model=PFZZone,
    status_code=status.HTTP_200_OK,
    summary="Get Single PFZ Zone",
    description="Retrieve a single Potential Fishing Zone advisory by its unique identifier.",
    tags=["Potential Fishing Zones (PFZ)"],
)
async def get_pfz_zone(
    pfz_id: str,
    pfz_service: PFZService = Depends(get_pfz_service),
) -> PFZZone:
    """Retrieve single PFZ zone by ID."""
    try:
        return pfz_service.get_zone(pfz_id)
    except PFZZoneNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/pfz/best",
    response_model=PFZRouteTargetResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Best PFZ Candidate Destinations (GET)",
    description="Query ranked candidate PFZ fishing destinations for the vessel's current position using query parameters.",
    tags=["Potential Fishing Zones (PFZ)"],
)
async def get_best_pfz_get(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Current vessel latitude (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Current vessel longitude (-180 to 180)"
    ),
    radius_km: float = Query(
        100.0, gt=0.0, le=2000.0, description="Search radius in kilometers"
    ),
    vessel_speed_knots: Optional[float] = Query(
        None, gt=0.0, description="Optional vessel operational speed in knots"
    ),
    objective: str = Query(
        "balanced",
        description="Scoring objective: 'balanced', 'highest_potential', 'nearest_distance', or 'high_confidence'",
    ),
    min_confidence: Optional[float] = Query(
        None, ge=0.0, le=1.0, description="Optional minimum confidence threshold (0.0 to 1.0)"
    ),
    limit: int = Query(5, ge=1, le=50, description="Maximum number of candidate destinations to return"),
    pfz_service: PFZService = Depends(get_pfz_service),
) -> PFZRouteTargetResponse:
    """Get best PFZ candidate destinations via GET parameters."""
    vessel = Vessel(speed_knots=vessel_speed_knots) if vessel_speed_knots else None
    request = PFZRouteTargetRequest(
        current_position=Coordinate(latitude=latitude, longitude=longitude),
        radius_km=radius_km,
        vessel=vessel,
        objective=objective,
        minimum_confidence=min_confidence,
        limit=limit,
    )
    return pfz_service.get_best_pfz_targets(request)


@router.post(
    "/pfz/best",
    response_model=PFZRouteTargetResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Best PFZ Candidate Destinations (POST)",
    description="Query ranked candidate PFZ fishing destinations using full request payload.",
    tags=["Potential Fishing Zones (PFZ)"],
)
async def get_best_pfz_post(
    request: PFZRouteTargetRequest,
    pfz_service: PFZService = Depends(get_pfz_service),
) -> PFZRouteTargetResponse:
    """Get best PFZ candidate destinations via POST payload."""
    return pfz_service.get_best_pfz_targets(request)


# ============================================================================
# MARINE & WEATHER CONDITIONS INTEGRATION ENDPOINTS
# ============================================================================

@router.get(
    "/marine/conditions",
    response_model=MarineConditionsSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Get Normalized Marine & Weather Conditions",
    description="Query normalized oceanographic (currents, waves, SST) and meteorological (wind, temperature, pressure) conditions for a geographic coordinate.",
    tags=["Marine Conditions"],
)
async def get_marine_conditions(
    latitude: float = Query(
        ..., ge=-90.0, le=90.0, description="Target coordinate latitude (-90 to 90)"
    ),
    longitude: float = Query(
        ..., ge=-180.0, le=180.0, description="Target coordinate longitude (-180 to 180)"
    ),
    timestamp: Optional[datetime] = Query(
        None, description="Optional target UTC timestamp (ISO 8601 format)"
    ),
    marine_service: MarineConditionsService = Depends(get_marine_conditions_service),
) -> MarineConditionsSnapshot:
    """Retrieve normalized environmental conditions snapshot."""
    return marine_service.get_snapshot(
        latitude=latitude,
        longitude=longitude,
        timestamp=timestamp,
    )


# ============================================================================
# SAFETY GOVERNOR INTEGRATION ENDPOINTS
# ============================================================================

@router.post(
    "/safety/evaluate",
    response_model=SafetyCheckResult,
    status_code=status.HTTP_200_OK,
    summary="Evaluate Route Safety (Safety Governor)",
    description="Perform authoritative navigational safety clearance inspection on candidate waypoints against restricted areas, bathymetry, ocean state, and meteorological limits.",
    tags=["Safety Governor"],
)
async def evaluate_safety(
    request: SafetyEvaluationRequest,
    safety_governor: SafetyGovernorService = Depends(get_safety_governor_service),
) -> SafetyCheckResult:
    """Perform authoritative safety audit on route and return SafetyCheckResult."""
    return safety_governor.evaluate_request(request)



