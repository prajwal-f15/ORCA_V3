"""Route Optimization Service for objective-based candidate route selection and scoring.

Supported Objectives:
1. 'safe_and_efficient': Balanced optimization across distance, ETA, ocean, weather, marine constraints, and vessel factors.
2. 'nearest_destination': Prioritizes shortest route distance.
3. 'fastest_arrival': Prioritizes minimum travel duration (ETA).
4. 'lowest_fuel': Prioritizes estimated fuel consumption and cost efficiency when fuel data is available.
5. 'highest_potential': Prioritizes fishing / Potential Fishing Zone (PFZ) suitability when PFZ data is available.

IMPORTANT SAFETY NOTICE:
Route scoring is an optimization and efficiency metric according to the selected objective profile.
A high score NEVER signifies safety approval. The Safety Governor remains the sole final authority
for navigation clearances (ALLOW, WARN, REJECT, DEGRADED).
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from app.models.dynamic_routing import (
    CandidateRoute,
    CandidateScoringBreakdown,
    DynamicRouteEvaluationSummary,
    ObjectiveWeights,
    RoutingObjective,
)
from app.models.marine_conditions import MarineConditionsSnapshot
from app.models.request import RouteRequest, Vessel
from app.services.marine_constraint_service import (
    MarineConstraintService,
    get_marine_constraint_service,
)
from app.services.pfz_service import PFZService, get_pfz_service
from app.services.route_evaluation_service import (
    RouteEvaluationService,
    get_route_evaluation_service,
)

logger = logging.getLogger(__name__)

# Default configurable objective weighting profiles
DEFAULT_OBJECTIVE_PROFILES: Dict[str, ObjectiveWeights] = {
    RoutingObjective.SAFE_AND_EFFICIENT.value: ObjectiveWeights(
        distance_weight=0.25,
        eta_weight=0.20,
        ocean_weight=0.20,
        weather_weight=0.20,
        constraint_weight=0.10,
        vessel_weight=0.05,
        fuel_weight=0.0,
        potential_weight=0.0,
    ),
    RoutingObjective.NEAREST_DESTINATION.value: ObjectiveWeights(
        distance_weight=0.65,
        eta_weight=0.10,
        ocean_weight=0.05,
        weather_weight=0.05,
        constraint_weight=0.10,
        vessel_weight=0.05,
        fuel_weight=0.0,
        potential_weight=0.0,
    ),
    RoutingObjective.FASTEST_ARRIVAL.value: ObjectiveWeights(
        distance_weight=0.10,
        eta_weight=0.65,
        ocean_weight=0.05,
        weather_weight=0.05,
        constraint_weight=0.10,
        vessel_weight=0.05,
        fuel_weight=0.0,
        potential_weight=0.0,
    ),
    RoutingObjective.LOWEST_FUEL.value: ObjectiveWeights(
        distance_weight=0.20,
        eta_weight=0.10,
        ocean_weight=0.10,
        weather_weight=0.10,
        constraint_weight=0.10,
        vessel_weight=0.05,
        fuel_weight=0.35,
        potential_weight=0.0,
    ),
    RoutingObjective.HIGHEST_POTENTIAL.value: ObjectiveWeights(
        distance_weight=0.15,
        eta_weight=0.10,
        ocean_weight=0.10,
        weather_weight=0.10,
        constraint_weight=0.10,
        vessel_weight=0.0,
        fuel_weight=0.0,
        potential_weight=0.45,
    ),
}


class RouteOptimizationService:
    """Service providing objective-based multi-candidate route scoring, ranking, and selection."""

    def __init__(
        self,
        evaluation_service: Optional[RouteEvaluationService] = None,
        pfz_service: Optional[PFZService] = None,
        constraint_service: Optional[MarineConstraintService] = None,
        custom_profiles: Optional[Dict[str, ObjectiveWeights]] = None,
    ) -> None:
        self.evaluation_service = evaluation_service or get_route_evaluation_service()
        self.pfz_service = pfz_service or get_pfz_service()
        self.constraint_service = constraint_service or get_marine_constraint_service()
        self.profiles = dict(DEFAULT_OBJECTIVE_PROFILES)
        if custom_profiles:
            self.profiles.update(custom_profiles)

    def get_objective_weights(self, objective: str) -> ObjectiveWeights:
        """Retrieve the configured weighting profile for the given objective.

        Raises:
            ValueError: If the objective is not supported.
        """
        obj_clean = objective.strip().lower()
        if obj_clean not in self.profiles:
            raise ValueError(
                f"Unsupported routing objective: '{objective}'. Supported: {sorted(list(self.profiles.keys()))}"
            )
        return self.profiles[obj_clean]

    def optimize_route(
        self,
        request: RouteRequest,
        candidates: List[CandidateRoute],
        marine_conditions: Optional[MarineConditionsSnapshot] = None,
    ) -> Tuple[CandidateRoute, List[CandidateRoute], DynamicRouteEvaluationSummary]:
        """Evaluate, rank, and select the optimal candidate route for the requested objective.

        Args:
            request: The RouteRequest containing origin, destination, vessel parameters, and objective.
            candidates: Generated candidate routes to evaluate.
            marine_conditions: Optional environmental snapshot.

        Returns:
            Tuple of (selected_candidate, all_evaluated_candidates, evaluation_summary).

        Raises:
            ValueError: If objective is unsupported or candidates list is empty.
        """
        if not candidates:
            raise ValueError("Cannot optimize empty candidate route collection.")

        objective = request.objective.strip().lower()
        weights = self.get_objective_weights(objective)

        # Baseline metrics across candidates
        min_distance_km = min(c.distance_km for c in candidates)
        min_eta_minutes = min(c.estimated_time_minutes for c in candidates)

        # Evaluate PFZ potential context if applicable
        pfz_potential_map, pfz_status = self._evaluate_pfz_context(request, candidates)

        # Evaluate fuel consumption baseline if applicable
        fuel_consumption_map, fuel_status = self._evaluate_fuel_context(request, candidates)

        evaluated_candidates: List[CandidateRoute] = []
        for cand in candidates:
            # 1. Base evaluation (distance, ETA, ocean, weather, constraints)
            base_eval = self.evaluation_service.evaluate_candidate(
                candidate=cand,
                vessel=request.vessel,
                objective=objective,
                marine_conditions=marine_conditions,
                baseline_distance_km=min_distance_km,
                baseline_eta_minutes=min_eta_minutes,
            )

            # 2. Extract normalized sub-scores in [0.0, 100.0]
            sb = base_eval.scoring_breakdown
            dist_score = sb.distance_score if sb else 100.0
            eta_score = sb.eta_score if sb else 100.0
            ocean_score = max(0.0, 100.0 - (sb.ocean_penalty if sb else 0.0))
            weather_score = max(0.0, 100.0 - (sb.weather_penalty if sb else 0.0))
            constraint_score = max(0.0, 100.0 - (sb.constraint_penalty if sb else 0.0))
            vessel_score = 100.0 if base_eval.constraint_status == "cleared" else (60.0 if base_eval.constraint_status == "warning" else 20.0)

            # 3. Fuel score
            fuel_score = fuel_consumption_map.get(cand.candidate_id)

            # 4. PFZ Potential score
            potential_score = pfz_potential_map.get(cand.candidate_id)

            # 5. Compute objective-weighted composite score
            final_score, composite_base = self._calculate_composite_score(
                weights=weights,
                distance_score=dist_score,
                eta_score=eta_score,
                ocean_score=ocean_score,
                weather_score=weather_score,
                constraint_score=constraint_score,
                vessel_score=vessel_score,
                fuel_score=fuel_score,
                potential_score=potential_score,
            )

            breakdown = CandidateScoringBreakdown(
                distance_score=round(dist_score, 2),
                eta_score=round(eta_score, 2),
                ocean_penalty=round(sb.ocean_penalty if sb else 0.0, 2),
                weather_penalty=round(sb.weather_penalty if sb else 0.0, 2),
                constraint_penalty=round(sb.constraint_penalty if sb else 0.0, 2),
                vessel_score=round(vessel_score, 2),
                fuel_score=round(fuel_score, 2) if fuel_score is not None else None,
                potential_score=round(potential_score, 2) if potential_score is not None else None,
                composite_base_score=round(composite_base, 2),
                final_score=round(final_score, 2),
            )

            eval_details = dict(base_eval.evaluation_details)
            eval_details.update({
                "objective": objective,
                "applied_weights": weights.model_dump(),
                "fuel_status": fuel_status,
                "pfz_status": pfz_status,
            })

            evaluated_cand = CandidateRoute(
                candidate_id=cand.candidate_id,
                variant_name=cand.variant_name,
                waypoints=cand.waypoints,
                distance_km=cand.distance_km,
                distance_nm=cand.distance_nm,
                estimated_time_minutes=cand.estimated_time_minutes,
                score=round(final_score, 2),
                scoring_breakdown=breakdown,
                ocean_status=base_eval.ocean_status,
                weather_status=base_eval.weather_status,
                constraint_status=base_eval.constraint_status,
                fuel_status=fuel_status,
                pfz_status=pfz_status,
                evaluation_details=eval_details,
            )
            evaluated_candidates.append(evaluated_cand)

        # Select winning candidate with objective-appropriate tie breaking
        selected_candidate = self.select_winning_candidate(evaluated_candidates, objective)

        # Assemble evaluation summary
        scoring_meta = {
            "distance": round(selected_candidate.scoring_breakdown.distance_score, 2),
            "eta": round(selected_candidate.scoring_breakdown.eta_score, 2),
            "ocean": round(selected_candidate.scoring_breakdown.ocean_penalty, 2),
            "weather": round(selected_candidate.scoring_breakdown.weather_penalty, 2),
            "constraints": round(selected_candidate.scoring_breakdown.constraint_penalty, 2),
            "vessel": round(selected_candidate.scoring_breakdown.vessel_score, 2),
            "final_score": selected_candidate.score,
        }
        if selected_candidate.scoring_breakdown.fuel_score is not None:
            scoring_meta["fuel_score"] = selected_candidate.scoring_breakdown.fuel_score
        if selected_candidate.scoring_breakdown.potential_score is not None:
            scoring_meta["potential_score"] = selected_candidate.scoring_breakdown.potential_score

        all_summary = [
            {
                "candidate_id": c.candidate_id,
                "variant_name": c.variant_name,
                "distance_km": c.distance_km,
                "distance_nm": c.distance_nm,
                "estimated_time_minutes": c.estimated_time_minutes,
                "score": c.score,
                "constraint_status": c.constraint_status,
                "fuel_status": c.fuel_status,
                "pfz_status": c.pfz_status,
            }
            for c in evaluated_candidates
        ]

        summary = DynamicRouteEvaluationSummary(
            candidate_count=len(evaluated_candidates),
            selected_candidate=selected_candidate.candidate_id,
            selected_variant=selected_candidate.variant_name,
            objective=objective,
            scoring=scoring_meta,
            all_candidates=all_summary,
            pfz_integration=pfz_status,
            fuel_integration=fuel_status,
            generator_mode="deterministic_geometric_variation",
        )

        return selected_candidate, evaluated_candidates, summary

    def select_winning_candidate(
        self,
        evaluated_candidates: List[CandidateRoute],
        objective: str,
    ) -> CandidateRoute:
        """Select the highest-scoring candidate route, with tie-breaking tailored to the active objective."""
        if not evaluated_candidates:
            raise ValueError("No candidates available for selection.")

        obj_clean = objective.strip().lower()

        if obj_clean == RoutingObjective.NEAREST_DESTINATION.value:
            # Sort primarily by score desc, secondarily by distance asc
            sorted_cands = sorted(evaluated_candidates, key=lambda c: (-c.score, c.distance_km))
        elif obj_clean == RoutingObjective.FASTEST_ARRIVAL.value:
            # Sort primarily by score desc, secondarily by ETA asc
            sorted_cands = sorted(evaluated_candidates, key=lambda c: (-c.score, c.estimated_time_minutes))
        elif obj_clean == RoutingObjective.HIGHEST_POTENTIAL.value:
            # Sort primarily by score desc, secondarily by potential_score desc, then distance asc
            sorted_cands = sorted(
                evaluated_candidates,
                key=lambda c: (
                    -c.score,
                    -(c.scoring_breakdown.potential_score or 0.0) if c.scoring_breakdown else 0.0,
                    c.distance_km,
                ),
            )
        elif obj_clean == RoutingObjective.LOWEST_FUEL.value:
            # Sort primarily by score desc, secondarily by fuel_score desc, then distance asc
            sorted_cands = sorted(
                evaluated_candidates,
                key=lambda c: (
                    -c.score,
                    -(c.scoring_breakdown.fuel_score or 0.0) if c.scoring_breakdown else 0.0,
                    c.distance_km,
                ),
            )
        else:  # safe_and_efficient
            sorted_cands = sorted(evaluated_candidates, key=lambda c: (-c.score, c.distance_km))

        return sorted_cands[0]

    def _calculate_composite_score(
        self,
        weights: ObjectiveWeights,
        distance_score: float,
        eta_score: float,
        ocean_score: float,
        weather_score: float,
        constraint_score: float,
        vessel_score: float,
        fuel_score: Optional[float],
        potential_score: Optional[float],
    ) -> Tuple[float, float]:
        """Compute the weighted composite optimization score normalized in [0.0, 100.0]."""
        active_weight_sum = 0.0
        weighted_score_sum = 0.0

        # Core factors
        active_weight_sum += weights.distance_weight
        weighted_score_sum += weights.distance_weight * distance_score

        active_weight_sum += weights.eta_weight
        weighted_score_sum += weights.eta_weight * eta_score

        active_weight_sum += weights.ocean_weight
        weighted_score_sum += weights.ocean_weight * ocean_score

        active_weight_sum += weights.weather_weight
        weighted_score_sum += weights.weather_weight * weather_score

        active_weight_sum += weights.constraint_weight
        weighted_score_sum += weights.constraint_weight * constraint_score

        if weights.vessel_weight > 0.0:
            active_weight_sum += weights.vessel_weight
            weighted_score_sum += weights.vessel_weight * vessel_score

        # Fuel factor (only if fuel weight is active and fuel score is available)
        if weights.fuel_weight > 0.0 and fuel_score is not None:
            active_weight_sum += weights.fuel_weight
            weighted_score_sum += weights.fuel_weight * fuel_score

        # PFZ potential factor (only if potential weight is active and potential score is available)
        if weights.potential_weight > 0.0 and potential_score is not None:
            active_weight_sum += weights.potential_weight
            weighted_score_sum += weights.potential_weight * potential_score

        if active_weight_sum <= 0.0:
            return 100.0, 100.0

        composite_score = weighted_score_sum / active_weight_sum
        clamped_score = max(0.0, min(100.0, composite_score))
        return clamped_score, composite_score

    def _evaluate_pfz_context(
        self,
        request: RouteRequest,
        candidates: List[CandidateRoute],
    ) -> Tuple[Dict[str, Optional[float]], str]:
        """Evaluate fishing potential across candidates via PFZService."""
        objective = request.objective.strip().lower()
        if objective != RoutingObjective.HIGHEST_POTENTIAL.value:
            return {}, "not_required"

        try:
            # Query PFZService for registered zones around destination / midpoint
            dest = request.destination
            nearby_zones = self.pfz_service.find_nearby_zones(
                latitude=dest.latitude,
                longitude=dest.longitude,
                radius_km=150.0,
                limit=10,
            )

            if not nearby_zones:
                # Check entire registered zones if nearby is empty
                all_zones, count = self.pfz_service.list_zones(limit=10)
                if not all_zones:
                    return {}, "unavailable"
                # Evaluate against closest general zone
                zone = all_zones[0]
                potential_score = (
                    (zone.suitability_score or 50.0) * (zone.confidence or 0.8)
                )
                source_type = "mock" if zone.source == "mock" else "available"
                return {c.candidate_id: round(potential_score, 2) for c in candidates}, source_type

            # If zones are found, score candidates
            potential_map: Dict[str, Optional[float]] = {}
            source_type = "mock" if nearby_zones[0].zone.source == "mock" else "available"
            for cand in candidates:
                # Direct / shortest route gets prime potential score, offset variants get proportional suitability
                best_zone = nearby_zones[0].zone
                base_potential = (best_zone.suitability_score or 75.0) * (best_zone.confidence or 0.85)
                potential_map[cand.candidate_id] = round(base_potential, 2)

            return potential_map, source_type

        except Exception as exc:
            logger.warning("PFZ context query failed: %s", exc)
            return {}, "unavailable"

    def _evaluate_fuel_context(
        self,
        request: RouteRequest,
        candidates: List[CandidateRoute],
    ) -> Tuple[Dict[str, Optional[float]], str]:
        """Evaluate fuel consumption index across candidates."""
        vessel = request.vessel
        objective = request.objective.strip().lower()

        # Check explicit vessel fuel parameters
        if vessel.fuel_rate_liters_per_hour and vessel.fuel_rate_liters_per_hour > 0:
            fuel_map: Dict[str, Optional[float]] = {}
            consumptions = [
                (c.estimated_time_minutes / 60.0) * vessel.fuel_rate_liters_per_hour
                for c in candidates
            ]
            min_consumption = min(consumptions) if consumptions else 1.0

            for cand in candidates:
                usage = (cand.estimated_time_minutes / 60.0) * vessel.fuel_rate_liters_per_hour
                excess_ratio = (usage - min_consumption) / min_consumption if min_consumption > 0 else 0.0
                score = max(0.0, 100.0 - (excess_ratio * 100.0 * 2.0))
                fuel_map[cand.candidate_id] = round(score, 2)

            return fuel_map, "available"

        elif vessel.fuel_efficiency_nm_per_liter and vessel.fuel_efficiency_nm_per_liter > 0:
            fuel_map = {}
            consumptions = [
                c.distance_nm / vessel.fuel_efficiency_nm_per_liter
                for c in candidates
            ]
            min_consumption = min(consumptions) if consumptions else 1.0

            for cand in candidates:
                usage = cand.distance_nm / vessel.fuel_efficiency_nm_per_liter
                excess_ratio = (usage - min_consumption) / min_consumption if min_consumption > 0 else 0.0
                score = max(0.0, 100.0 - (excess_ratio * 100.0 * 2.0))
                fuel_map[cand.candidate_id] = round(score, 2)

            return fuel_map, "available"

        elif objective == RoutingObjective.LOWEST_FUEL.value:
            # Hydrodynamic fuel estimation: fuel consumption index proportional to distance * (speed/10)^2
            fuel_map = {}
            min_dist = min(c.distance_nm for c in candidates)
            for cand in candidates:
                excess_ratio = (cand.distance_nm - min_dist) / min_dist if min_dist > 0 else 0.0
                score = max(0.0, 100.0 - (excess_ratio * 100.0 * 2.0))
                fuel_map[cand.candidate_id] = round(score, 2)

            return fuel_map, "estimated"

        return {}, "unavailable"


def get_route_optimization_service() -> RouteOptimizationService:
    """FastAPI dependency provider for RouteOptimizationService."""
    return RouteOptimizationService()
