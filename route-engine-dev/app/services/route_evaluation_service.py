"""Route evaluation and scoring service for dynamic multi-candidate routing.

Evaluates candidates based on:
1. Navigational efficiency (distance, ETA relative to baseline)
2. Oceanographic penalties (wave height, opposing currents, sea surface state)
3. Meteorological penalties (wind speed, wind gusts, visibility, precipitation)
4. Marine spatial constraint penalties (restricted zones, shallow depth / under-keel safety)

IMPORTANT SAFETY DISCLAIMER:
A high route score is an optimization and efficiency metric, NOT a final safety clearance.
The Safety Governor remains the sole final authority for navigation safety decisions.
"""

import logging
import math
from typing import Any, Dict, List, Optional
from app.models.dynamic_routing import (
    CandidateRoute,
    CandidateScoringBreakdown,
)
from app.models.marine_conditions import MarineConditionsSnapshot
from app.models.request import Vessel
from app.services.marine_constraint_service import (
    MarineConstraintService,
    get_marine_constraint_service,
)

logger = logging.getLogger(__name__)


class RouteEvaluationService:
    """Service evaluating and scoring candidate routes across navigational and environmental metrics."""

    def __init__(
        self,
        constraint_service: Optional[MarineConstraintService] = None,
    ) -> None:
        self.constraint_service = constraint_service or get_marine_constraint_service()

    def evaluate_candidates(
        self,
        candidates: List[CandidateRoute],
        vessel: Vessel,
        objective: str = "safe_and_efficient",
        marine_conditions: Optional[MarineConditionsSnapshot] = None,
    ) -> List[CandidateRoute]:
        """Evaluate and score a collection of candidate routes against shared baselines.

        Args:
            candidates: List of generated candidate routes.
            vessel: Vessel specifications and operational limits.
            objective: Routing optimization objective ('safe_and_efficient', 'fastest', 'fuel_saving', 'balanced').
            marine_conditions: Optional environmental conditions snapshot.

        Returns:
            List of evaluated CandidateRoute instances with populated scores and breakdowns.
        """
        if not candidates:
            return []

        # Find baseline minimum distance and ETA across the candidates
        baseline_distance_km = min(c.distance_km for c in candidates)
        baseline_eta_minutes = min(c.estimated_time_minutes for c in candidates)

        evaluated: List[CandidateRoute] = []
        for cand in candidates:
            evaluated_cand = self.evaluate_candidate(
                candidate=cand,
                vessel=vessel,
                objective=objective,
                marine_conditions=marine_conditions,
                baseline_distance_km=baseline_distance_km,
                baseline_eta_minutes=baseline_eta_minutes,
            )
            evaluated.append(evaluated_cand)

        return evaluated

    def evaluate_candidate(
        self,
        candidate: CandidateRoute,
        vessel: Vessel,
        objective: str = "safe_and_efficient",
        marine_conditions: Optional[MarineConditionsSnapshot] = None,
        baseline_distance_km: Optional[float] = None,
        baseline_eta_minutes: Optional[float] = None,
    ) -> CandidateRoute:
        """Evaluate a single candidate route and calculate normalized score [0.0, 100.0].

        Args:
            candidate: Candidate route to evaluate.
            vessel: Vessel parameters.
            objective: Routing objective profile.
            marine_conditions: Optional environmental conditions snapshot.
            baseline_distance_km: Shortest candidate distance among group (defaults to candidate distance).
            baseline_eta_minutes: Shortest candidate ETA among group (defaults to candidate ETA).

        Returns:
            CandidateRoute with populated score, scoring_breakdown, and status fields.
        """
        base_dist = baseline_distance_km if baseline_distance_km is not None else candidate.distance_km
        base_eta = baseline_eta_minutes if baseline_eta_minutes is not None else candidate.estimated_time_minutes

        # 1. Distance score (0 to 100)
        distance_score = self._compute_distance_score(candidate.distance_km, base_dist)

        # 2. ETA score (0 to 100)
        eta_score = self._compute_eta_score(candidate.estimated_time_minutes, base_eta)

        # 3. Ocean penalty (0 to 50) and status
        ocean_penalty, ocean_status, ocean_details = self._evaluate_ocean_conditions(marine_conditions)

        # 4. Weather penalty (0 to 50) and status
        weather_penalty, weather_status, weather_details = self._evaluate_weather_conditions(marine_conditions)

        # 5. Marine constraint penalty (0 to 80) and status
        constraint_penalty, constraint_status, constraint_details = self._evaluate_marine_constraints(
            candidate=candidate,
            vessel=vessel,
        )

        # 6. Composite base score calculation based on objective
        composite_base = self._compute_composite_base_score(distance_score, eta_score, objective)

        # 7. Final normalized route score calculation
        total_penalties = ocean_penalty + weather_penalty + constraint_penalty
        raw_score = composite_base - total_penalties
        final_score = round(max(0.0, min(100.0, raw_score)), 2)

        breakdown = CandidateScoringBreakdown(
            distance_score=round(distance_score, 2),
            eta_score=round(eta_score, 2),
            ocean_penalty=round(ocean_penalty, 2),
            weather_penalty=round(weather_penalty, 2),
            constraint_penalty=round(constraint_penalty, 2),
            composite_base_score=round(composite_base, 2),
            final_score=final_score,
        )

        evaluation_details = dict(candidate.evaluation_details)
        evaluation_details.update({
            "objective": objective,
            "ocean_details": ocean_details,
            "weather_details": weather_details,
            "constraint_details": constraint_details,
        })

        return CandidateRoute(
            candidate_id=candidate.candidate_id,
            variant_name=candidate.variant_name,
            waypoints=candidate.waypoints,
            distance_km=candidate.distance_km,
            distance_nm=candidate.distance_nm,
            estimated_time_minutes=candidate.estimated_time_minutes,
            score=final_score,
            scoring_breakdown=breakdown,
            ocean_status=ocean_status,
            weather_status=weather_status,
            constraint_status=constraint_status,
            evaluation_details=evaluation_details,
        )

    def _compute_distance_score(self, distance_km: float, baseline_distance_km: float) -> float:
        """Compute distance efficiency score in [0.0, 100.0]."""
        if baseline_distance_km <= 0.0 or distance_km <= 0.0:
            return 100.0
        # If candidate is longer than baseline, apply proportional penalty
        excess_ratio = (distance_km - baseline_distance_km) / baseline_distance_km
        score = 100.0 - (excess_ratio * 100.0 * 2.0)
        return max(0.0, min(100.0, score))

    def _compute_eta_score(self, eta_minutes: float, baseline_eta_minutes: float) -> float:
        """Compute ETA efficiency score in [0.0, 100.0]."""
        if baseline_eta_minutes <= 0.0 or eta_minutes <= 0.0:
            return 100.0
        excess_ratio = (eta_minutes - baseline_eta_minutes) / baseline_eta_minutes
        score = 100.0 - (excess_ratio * 100.0 * 2.0)
        return max(0.0, min(100.0, score))

    def _compute_composite_base_score(self, distance_score: float, eta_score: float, objective: str) -> float:
        """Calculate weighted base score before environmental and constraint penalties."""
        obj_clean = objective.lower().strip()
        if obj_clean == "fastest":
            return (0.20 * distance_score) + (0.80 * eta_score)
        elif obj_clean == "fuel_saving":
            return (0.75 * distance_score) + (0.25 * eta_score)
        else:  # safe_and_efficient, balanced, or default
            return (0.50 * distance_score) + (0.50 * eta_score)

    def _evaluate_ocean_conditions(
        self,
        snapshot: Optional[MarineConditionsSnapshot],
    ) -> tuple[float, str, Dict[str, Any]]:
        """Evaluate oceanographic metrics and calculate penalty points.

        Never treat missing/unavailable data as safe: unverified data incurs an explicit data penalty.
        """
        if snapshot is None or snapshot.ocean is None:
            return 8.0, "unavailable", {"note": "Ocean conditions unavailable; missing data is not assumed safe."}

        ocean = snapshot.ocean
        status = "mock" if ocean.source == "mock" else "evaluated"
        penalty = 0.0
        details: Dict[str, Any] = {"source": ocean.source}

        # 1. Significant wave height penalty (Hs in meters)
        if ocean.significant_wave_height_m is not None:
            hs = ocean.significant_wave_height_m
            details["significant_wave_height_m"] = hs
            if hs > 4.0:
                penalty += 20.0 + (hs - 4.0) * 10.0
            elif hs > 2.5:
                penalty += 6.0 + (hs - 2.5) * 8.0
            elif hs > 1.5:
                penalty += (hs - 1.5) * 4.0

        # 2. Surface current speed penalty (knots)
        if ocean.current_speed_knots is not None:
            curr_spd = ocean.current_speed_knots
            details["current_speed_knots"] = curr_spd
            if curr_spd > 2.0:
                penalty += (curr_spd - 2.0) * 5.0

        # Cap ocean penalty at 40.0
        final_ocean_penalty = min(40.0, penalty)
        return final_ocean_penalty, status, details

    def _evaluate_weather_conditions(
        self,
        snapshot: Optional[MarineConditionsSnapshot],
    ) -> tuple[float, str, Dict[str, Any]]:
        """Evaluate meteorological metrics and calculate penalty points.

        Never treat missing/unavailable data as safe: unverified data incurs an explicit data penalty.
        """
        if snapshot is None or snapshot.weather is None:
            return 8.0, "unavailable", {"note": "Weather conditions unavailable; missing data is not assumed safe."}

        weather = snapshot.weather
        status = "mock" if weather.source == "mock" else "evaluated"
        penalty = 0.0
        details: Dict[str, Any] = {"source": weather.source}

        # 1. Wind speed penalty (knots)
        if weather.wind_speed_knots is not None:
            wind = weather.wind_speed_knots
            details["wind_speed_knots"] = wind
            if wind > 30.0:
                penalty += 18.0 + (wind - 30.0) * 2.5
            elif wind > 20.0:
                penalty += 6.0 + (wind - 20.0) * 1.2
            elif wind > 12.0:
                penalty += (wind - 12.0) * 0.6

        # 2. Wind gust penalty
        if weather.wind_gust_knots is not None:
            gust = weather.wind_gust_knots
            details["wind_gust_knots"] = gust
            if gust > 25.0:
                penalty += (gust - 25.0) * 0.8

        # 3. Visibility penalty (km)
        if weather.visibility_km is not None:
            vis = weather.visibility_km
            details["visibility_km"] = vis
            if vis < 1.0:
                penalty += 15.0 + (1.0 - vis) * 10.0
            elif vis < 5.0:
                penalty += (5.0 - vis) * 2.0

        # 4. Precipitation rate penalty (mm/h)
        if weather.precipitation_mm_h is not None and weather.precipitation_mm_h > 2.0:
            penalty += min(10.0, weather.precipitation_mm_h * 1.5)

        final_weather_penalty = min(40.0, penalty)
        return final_weather_penalty, status, details

    def _evaluate_marine_constraints(
        self,
        candidate: CandidateRoute,
        vessel: Vessel,
    ) -> tuple[float, str, Dict[str, Any]]:
        """Inspect spatial restrictions and depth constraints along candidate waypoints."""
        if not self.constraint_service:
            return 0.0, "pending", {"note": "MarineConstraintService unavailable."}

        try:
            check_result = self.constraint_service.check_route_restrictions(
                waypoints=candidate.waypoints,
                vessel_draft_meters=vessel.draft_meters,
            )

            if check_result.has_restrictions:
                hits = len(check_result.intersecting_restrictions)
                penalty = min(70.0, 25.0 + (hits * 15.0))
                return (
                    penalty,
                    "restricted_detected",
                    {
                        "restricted_segments_count": check_result.restricted_segments_count,
                        "restrictions_count": hits,
                        "warnings": check_result.warnings,
                    },
                )

            # Check under-keel depth clearance if vessel specifies depth requirements
            if vessel.draft_meters or vessel.minimum_safe_depth_meters:
                required_depth = vessel.minimum_safe_depth_meters or (vessel.draft_meters * 1.2 if vessel.draft_meters else 2.0)
                # Sample depth along intermediate waypoints
                shallow_hits = 0
                for wp in candidate.waypoints:
                    depth_res = self.constraint_service.get_depth_at_coordinate(wp.latitude, wp.longitude)
                    if depth_res.depth_meters is not None and depth_res.depth_meters < required_depth:
                        shallow_hits += 1

                if shallow_hits > 0:
                    depth_penalty = min(40.0, 15.0 + shallow_hits * 10.0)
                    return depth_penalty, "warning", {"shallow_sounding_points": shallow_hits}

            return 0.0, "cleared", {"restrictions_count": 0}

        except Exception as exc:
            logger.warning("Error during constraint evaluation for candidate %s: %s", candidate.candidate_id, exc)
            return 0.0, "pending", {"error": str(exc)}


def get_route_evaluation_service() -> RouteEvaluationService:
    """FastAPI / DI provider for RouteEvaluationService."""
    return RouteEvaluationService()
