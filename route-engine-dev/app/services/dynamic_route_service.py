"""Dynamic Marine Routing Service with multi-candidate generation, evaluation, and selection.

Orchestration Flow:
1. Receive voyage parameters (start, destination, vessel constraints, objective).
2. Retrieve or ingest normalized environmental snapshot via MarineConditionsService.
3. Generate multiple deterministic candidate route geometries.
4. Evaluate and score each candidate via RouteEvaluationService across distance, duration, ocean, weather, and spatial constraints.
5. Select the highest-scoring candidate route.
6. Assemble full RouteResponse with populated summary, constraints, marine snapshot, and candidate evaluation metadata.

IMPORTANT SAFETY NOTICE:
Candidate route selection and scoring represent navigational optimization inputs.
The Safety Governor remains the sole final authority for safety clearances (ALLOW, WARN, REJECT, DEGRADED).
"""

import logging
import math
import uuid
from typing import Any, Dict, List, Optional
from app.models.dynamic_routing import (
    CandidateRoute,
    DynamicRouteEvaluationSummary,
)
from app.models.marine_conditions import MarineConditionsSnapshot
from app.models.request import Coordinate, RouteRequest, Vessel
from app.models.response import RouteConstraints, RouteResponse, RouteSummary
from app.services.geo_service import GeoService
from app.services.marine_conditions_service import (
    MarineConditionsService,
    get_marine_conditions_service,
)
from app.services.route_evaluation_service import (
    RouteEvaluationService,
    get_route_evaluation_service,
)
from app.services.route_optimization_service import (
    RouteOptimizationService,
    get_route_optimization_service,
)
from app.services.safety_governor_service import (
    SafetyGovernorService,
    get_safety_governor_service,
)
from app.services.waypoint_service import WaypointGenerator

logger = logging.getLogger(__name__)


class DynamicRouteService:
    """Dynamic multi-candidate voyage route generation, evaluation, optimization, and safety governor audit service."""

    def __init__(
        self,
        marine_conditions_service: Optional[MarineConditionsService] = None,
        evaluation_service: Optional[RouteEvaluationService] = None,
        optimization_service: Optional[RouteOptimizationService] = None,
        safety_governor_service: Optional[SafetyGovernorService] = None,
        default_intermediate_waypoints: int = 3,
    ) -> None:
        self.marine_conditions_service = (
            marine_conditions_service or get_marine_conditions_service()
        )
        self.evaluation_service = (
            evaluation_service or get_route_evaluation_service()
        )
        self.optimization_service = (
            optimization_service or get_route_optimization_service()
        )
        self.safety_governor_service = (
            safety_governor_service or get_safety_governor_service()
        )
        self.default_intermediate_waypoints = default_intermediate_waypoints

    def calculate_route(self, request: RouteRequest) -> RouteResponse:
        """Execute dynamic route calculation, candidate evaluation, winning route selection, and safety audit.

        Args:
            request: Validated RouteRequest containing origin, destination, vessel, and objective.

        Returns:
            RouteResponse containing the winning candidate path, metrics, constraints, safety decision, and evaluation metadata.
        """
        route_id = f"route-{uuid.uuid4().hex[:8]}"

        # 1. Resolve Marine Conditions Snapshot
        snapshot: Optional[MarineConditionsSnapshot] = None
        if request.environmental_conditions:
            if isinstance(request.environmental_conditions, MarineConditionsSnapshot):
                snapshot = request.environmental_conditions
            elif isinstance(request.environmental_conditions, dict):
                try:
                    env_data = dict(request.environmental_conditions)
                    if "position" not in env_data:
                        env_data["position"] = {
                            "latitude": request.start.latitude,
                            "longitude": request.start.longitude,
                        }
                    # If flat ocean/weather fields were passed, construct nested models
                    if "ocean" not in env_data and any(
                        k in env_data
                        for k in ["significant_wave_height_m", "current_speed_knots", "wave_period_seconds"]
                    ):
                        env_data["ocean"] = {
                            k: env_data[k]
                            for k in [
                                "source",
                                "current_speed_knots",
                                "current_direction_degrees",
                                "significant_wave_height_m",
                                "wave_period_seconds",
                                "wave_direction_degrees",
                                "sea_surface_temperature_c",
                                "salinity_psu",
                            ]
                            if k in env_data
                        }
                    if "weather" not in env_data and any(
                        k in env_data
                        for k in ["wind_speed_knots", "wind_gust_knots", "visibility_km", "air_temperature_c"]
                    ):
                        env_data["weather"] = {
                            k: env_data[k]
                            for k in [
                                "source",
                                "wind_speed_knots",
                                "wind_direction_degrees",
                                "wind_gust_knots",
                                "air_temperature_c",
                                "visibility_km",
                                "pressure_hpa",
                                "precipitation_mm_h",
                                "cloud_cover_percent",
                            ]
                            if k in env_data
                        }
                    snapshot = MarineConditionsSnapshot(**env_data)
                except Exception as exc:
                    logger.warning("Could not parse request environmental_conditions: %s", exc)
                    snapshot = None

        if snapshot is None:
            # Query MarineConditionsService for midpoint or origin coordinate
            mid_lat = (request.start.latitude + request.destination.latitude) / 2.0
            mid_lon = (request.start.longitude + request.destination.longitude) / 2.0
            snapshot = self.marine_conditions_service.get_snapshot(
                latitude=mid_lat,
                longitude=mid_lon,
            )

        # 2. Generate Deterministic Candidate Routes
        candidates = self.generate_candidates(
            start=request.start,
            destination=request.destination,
            vessel_speed_knots=request.vessel.speed_knots,
            num_intermediate=self.default_intermediate_waypoints,
        )

        # 3. Optimize and Score Candidates via RouteOptimizationService
        selected_candidate, evaluated_candidates, eval_summary = self.optimization_service.optimize_route(
            request=request,
            candidates=candidates,
            marine_conditions=snapshot,
        )

        # 4. Perform Authoritative Safety Audit via SafetyGovernorService
        safety_result = self.safety_governor_service.evaluate_route(
            waypoints=selected_candidate.waypoints,
            vessel=request.vessel,
            marine_conditions=snapshot,
            route_score=selected_candidate.score,
            objective=request.objective,
        )

        # 5. Assemble Route Summary
        summary = RouteSummary(
            distance_km=selected_candidate.distance_km,
            distance_nm=selected_candidate.distance_nm,
            estimated_time_minutes=selected_candidate.estimated_time_minutes,
            route_score=selected_candidate.score,
        )

        # 6. Status Checks and Constraint Evaluation
        weather_status = "evaluated" if request.environmental_conditions else "pending"
        restricted_status = (
            selected_candidate.constraint_status
            if selected_candidate.constraint_status in ["warning", "restricted_detected"]
            else "pending"
        )

        constraints = RouteConstraints(
            safety_check="pending",
            weather_check=weather_status,
            restricted_area_check=restricted_status,
        )

        return RouteResponse(
            route_id=route_id,
            status="computed",
            summary=summary,
            waypoints=selected_candidate.waypoints,
            constraints=constraints,
            marine_conditions=snapshot,
            evaluation_metadata=eval_summary.model_dump(),
            safety_decision=safety_result.decision.value,
            safety_evaluation=safety_result.model_dump(),
        )

    def generate_candidates(
        self,
        start: Coordinate,
        destination: Coordinate,
        vessel_speed_knots: float,
        num_intermediate: int = 3,
    ) -> List[CandidateRoute]:
        """Generate deterministic candidate routes using geometric variations around geodesic baseline.

        Candidate 1: 'direct_geodesic' - Direct linear interpolation
        Candidate 2: 'starboard_offset' - Lateral curve displacement to starboard (+ perpendicular offset)
        Candidate 3: 'port_offset' - Lateral curve displacement to port (- perpendicular offset)

        Args:
            start: Origin Coordinate.
            destination: Destination Coordinate.
            vessel_speed_knots: Vessel operational speed.
            num_intermediate: Number of intermediate waypoints.

        Returns:
            List of CandidateRoute objects with calculated distances and ETAs.
        """
        candidates: List[CandidateRoute] = []

        # Candidate 1: Direct Geodesic
        direct_wps = WaypointGenerator.generate_linear_waypoints(
            start=start, destination=destination, num_intermediate=num_intermediate
        )
        dist_km, dist_nm, eta_min = self._compute_path_metrics(direct_wps, vessel_speed_knots)
        candidates.append(
            CandidateRoute(
                candidate_id="candidate-direct",
                variant_name="direct_geodesic",
                waypoints=direct_wps,
                distance_km=dist_km,
                distance_nm=dist_nm,
                estimated_time_minutes=eta_min,
                evaluation_details={"generator": "linear_interpolation", "offset_direction": "none"},
            )
        )

        # If zero distance (start == destination), return single direct candidate
        if dist_km == 0.0:
            return candidates

        # Candidate 2: Starboard offset (+ perpendicular offset)
        starboard_wps = self._generate_offset_waypoints(
            start=start,
            destination=destination,
            num_intermediate=num_intermediate,
            lateral_offset_factor=0.03,  # ~3% lateral sinusoidal arch
        )
        s_km, s_nm, s_eta = self._compute_path_metrics(starboard_wps, vessel_speed_knots)
        candidates.append(
            CandidateRoute(
                candidate_id="candidate-starboard",
                variant_name="starboard_offset",
                waypoints=starboard_wps,
                distance_km=s_km,
                distance_nm=s_nm,
                estimated_time_minutes=s_eta,
                evaluation_details={"generator": "sinusoidal_lateral_offset", "offset_direction": "starboard"},
            )
        )

        # Candidate 3: Port offset (- perpendicular offset)
        port_wps = self._generate_offset_waypoints(
            start=start,
            destination=destination,
            num_intermediate=num_intermediate,
            lateral_offset_factor=-0.03,  # ~ -3% lateral sinusoidal arch
        )
        p_km, p_nm, p_eta = self._compute_path_metrics(port_wps, vessel_speed_knots)
        candidates.append(
            CandidateRoute(
                candidate_id="candidate-port",
                variant_name="port_offset",
                waypoints=port_wps,
                distance_km=p_km,
                distance_nm=p_nm,
                estimated_time_minutes=p_eta,
                evaluation_details={"generator": "sinusoidal_lateral_offset", "offset_direction": "port"},
            )
        )

        return candidates

    def select_best_candidate(self, evaluated_candidates: List[CandidateRoute]) -> CandidateRoute:
        """Select the best candidate based on highest score, breaking ties by shortest distance."""
        if not evaluated_candidates:
            raise ValueError("No candidate routes available for selection.")

        # Sort primarily by score descending, secondarily by distance ascending
        sorted_candidates = sorted(
            evaluated_candidates,
            key=lambda c: (-c.score, c.distance_km),
        )
        return sorted_candidates[0]

    def _generate_offset_waypoints(
        self,
        start: Coordinate,
        destination: Coordinate,
        num_intermediate: int,
        lateral_offset_factor: float,
    ) -> List[Coordinate]:
        """Generate smooth sinusoidal lateral offset waypoints around the geodesic line."""
        waypoints: List[Coordinate] = [
            Coordinate(latitude=round(start.latitude, 6), longitude=round(start.longitude, 6))
        ]

        lat_delta = destination.latitude - start.latitude
        lon_delta = destination.longitude - start.longitude

        # Compute normal vector (-dy, dx)
        # Normal vector perpendicular to trajectory:
        norm_lat = -lon_delta
        norm_lon = lat_delta

        total_segments = num_intermediate + 1
        for i in range(1, num_intermediate + 1):
            fraction = i / total_segments
            # Sinusoidal arch: maximum at midpoint (sin(pi * fraction))
            arch = math.sin(math.pi * fraction)

            base_lat = start.latitude + (fraction * lat_delta)
            base_lon = start.longitude + (fraction * lon_delta)

            offset_lat = base_lat + (lateral_offset_factor * arch * norm_lat)
            offset_lon = base_lon + (lateral_offset_factor * arch * norm_lon)

            # Clamp coordinates to geographic bounds
            clamped_lat = max(-90.0, min(90.0, offset_lat))
            clamped_lon = max(-180.0, min(180.0, offset_lon))

            waypoints.append(
                Coordinate(
                    latitude=round(clamped_lat, 6),
                    longitude=round(clamped_lon, 6),
                )
            )

        waypoints.append(
            Coordinate(latitude=round(destination.latitude, 6), longitude=round(destination.longitude, 6))
        )
        return waypoints

    def _compute_path_metrics(
        self,
        waypoints: List[Coordinate],
        speed_knots: float,
    ) -> tuple[float, float, float]:
        """Calculate total cumulative distance and estimated travel time along waypoints."""
        if len(waypoints) < 2:
            return 0.0, 0.0, 0.0

        total_dist_km = 0.0
        for i in range(len(waypoints) - 1):
            p1 = waypoints[i]
            p2 = waypoints[i + 1]
            seg_dist = GeoService.haversine_distance_km(p1, p2)
            total_dist_km += seg_dist

        total_dist_nm = GeoService.km_to_nautical_miles(total_dist_km)
        eta_minutes = GeoService.calculate_eta_minutes(total_dist_nm, speed_knots) if speed_knots > 0 else 0.0

        return round(total_dist_km, 2), round(total_dist_nm, 2), round(eta_minutes, 2)


def get_dynamic_route_service() -> DynamicRouteService:
    """FastAPI / DI dependency provider for DynamicRouteService."""
    return DynamicRouteService()
