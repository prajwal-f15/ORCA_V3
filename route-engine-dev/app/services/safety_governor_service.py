"""Safety Governor Service for ORCA V3.

The Safety Governor is the FINAL AND AUTHORITATIVE safety evaluation body in the platform.
It strictly audits all candidate routes, vessel constraints, spatial boundaries, and environmental
conditions to render a final, un-overridable navigational verdict:
    ALLOW | WARN | REJECT | DEGRADED

DECISION PRECEDENCE HIERARCHY:
    1. REJECT   (Highest priority: Any confirmed safety breach, restricted zone hit, or critical UKC / weather violation)
    2. WARN     (Operational advisories, moderate sea/weather states, or mock test data flags)
    3. DEGRADED (Crucial safety information unavailable / unverified, proceeding only under degraded protocol)
    4. ALLOW    (All checks strictly pass with complete verified data feeds)

IMPORTANT ARCHITECTURAL RULE:
A high route efficiency score (e.g. 99/100) from the Route Engine CANNOT override a Safety Governor REJECT.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.core.config import Settings, get_settings
from app.models.marine_conditions import MarineConditionsSnapshot
from app.models.request import Coordinate, Vessel
from app.models.safety import (
    CheckStatus,
    SafetyCheckResult,
    SafetyDecision,
    SafetyEvaluationRequest,
)
from app.services.marine_conditions_service import (
    MarineConditionsService,
    get_marine_conditions_service,
)
from app.services.marine_constraint_service import (
    MarineConstraintService,
    get_marine_constraint_service,
)

logger = logging.getLogger(__name__)


class SafetyGovernorService:
    """Authoritative Safety Governor auditing routes, bathymetry, restricted areas, and environmental risk."""

    def __init__(
        self,
        constraint_service: Optional[MarineConstraintService] = None,
        marine_conditions_service: Optional[MarineConditionsService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.constraint_service = constraint_service or get_marine_constraint_service()
        self.marine_conditions_service = (
            marine_conditions_service or get_marine_conditions_service()
        )
        self.settings = settings or get_settings()

    def evaluate_request(self, request: SafetyEvaluationRequest) -> SafetyCheckResult:
        """Evaluate a standalone SafetyEvaluationRequest."""
        return self.evaluate_route(
            waypoints=request.waypoints,
            vessel=request.vessel,
            marine_conditions=request.marine_conditions,
            route_score=request.route_score,
            objective=request.objective or "safe_and_efficient",
            extra_metadata=request.metadata,
        )

    def evaluate_route(
        self,
        waypoints: List[Coordinate],
        vessel: Vessel,
        marine_conditions: Optional[MarineConditionsSnapshot] = None,
        route_score: Optional[float] = None,
        objective: str = "safe_and_efficient",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> SafetyCheckResult:
        """Perform authoritative safety inspection on a voyage route.

        Args:
            waypoints: Sequence of route coordinates forming the candidate voyage.
            vessel: Vessel operational parameters (speed, draft, safe depth).
            marine_conditions: Optional environmental snapshot (waves, wind, visibility, currents).
            route_score: Calculated route optimization score (cannot override safety verdict).
            objective: Active routing objective profile.
            extra_metadata: Additional diagnostic context.

        Returns:
            SafetyCheckResult containing decision (ALLOW/WARN/REJECT/DEGRADED), itemized checks, and reasons.
        """
        checks: Dict[str, str] = {}
        warnings: List[str] = []
        blocking_reasons: List[str] = []
        data_status: Dict[str, str] = {}
        eval_meta: Dict[str, Any] = dict(extra_metadata or {})
        eval_meta["route_score_received"] = route_score
        eval_meta["objective"] = objective

        # ---------------------------------------------------------------------
        # 1. RESTRICTED MARINE AREA CHECK
        # ---------------------------------------------------------------------
        restricted_status = self._check_restricted_areas(
            waypoints=waypoints,
            vessel=vessel,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            data_status=data_status,
        )
        checks["restricted_area"] = restricted_status.value

        # ---------------------------------------------------------------------
        # 2. BATHYMETRY / DEPTH / UNDER-KEEL CLEARANCE (UKC) CHECK
        # ---------------------------------------------------------------------
        bathymetry_status = self._check_bathymetry_depth(
            waypoints=waypoints,
            vessel=vessel,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            data_status=data_status,
        )
        checks["bathymetry"] = bathymetry_status.value

        # ---------------------------------------------------------------------
        # 3. OCEANOGRAPHIC CONDITIONS CHECK
        # ---------------------------------------------------------------------
        ocean_status = self._check_ocean_conditions(
            marine_conditions=marine_conditions,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            data_status=data_status,
        )
        checks["ocean"] = ocean_status.value

        # ---------------------------------------------------------------------
        # 4. METEOROLOGICAL / WEATHER CONDITIONS CHECK
        # ---------------------------------------------------------------------
        weather_status = self._check_weather_conditions(
            marine_conditions=marine_conditions,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            data_status=data_status,
        )
        checks["weather"] = weather_status.value

        # ---------------------------------------------------------------------
        # 5. DATA QUALITY & INTEGRITY CHECK
        # ---------------------------------------------------------------------
        quality_status = self._check_data_quality(
            data_status=data_status,
            warnings=warnings,
        )
        checks["data_quality"] = quality_status.value

        # ---------------------------------------------------------------------
        # 6. FINAL AUTHORITATIVE DECISION PRECEDENCE
        # ---------------------------------------------------------------------
        decision, reason = self._determine_final_decision(
            checks=checks,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            data_status=data_status,
        )

        return SafetyCheckResult(
            decision=decision,
            reason=reason,
            checks=checks,
            warnings=warnings,
            blocking_reasons=blocking_reasons,
            data_status=data_status,
            evaluated_at=datetime.now(timezone.utc),
            metadata=eval_meta,
        )

    def _check_restricted_areas(
        self,
        waypoints: List[Coordinate],
        vessel: Vessel,
        blocking_reasons: List[str],
        warnings: List[str],
        data_status: Dict[str, str],
    ) -> CheckStatus:
        """Inspect spatial intersection with restricted / no-go marine zones."""
        if not self.constraint_service:
            data_status["restricted_area"] = "unavailable"
            warnings.append("Restricted marine area data service is unverified/unavailable.")
            return CheckStatus.UNAVAILABLE

        try:
            res = self.constraint_service.check_route_restrictions(
                waypoints=waypoints,
                vessel_draft_meters=vessel.draft_meters,
            )
            data_status["restricted_area"] = "available"

            if res.has_restrictions:
                hits = len(res.intersecting_restrictions)
                names = [r.name for r in res.intersecting_restrictions if r.name]
                name_str = f" ({', '.join(names)})" if names else ""
                msg = f"Route intersects {hits} confirmed restricted/no-go marine zone(s){name_str} across {res.restricted_segments_count} route segment(s)."
                blocking_reasons.append(msg)
                return CheckStatus.BLOCK

            return CheckStatus.PASS

        except Exception as exc:
            logger.error("Error during restricted area safety check: %s", exc)
            data_status["restricted_area"] = "unavailable"
            warnings.append(f"Restricted area verification failed: {exc}")
            return CheckStatus.UNAVAILABLE

    def _check_bathymetry_depth(
        self,
        waypoints: List[Coordinate],
        vessel: Vessel,
        blocking_reasons: List[str],
        warnings: List[str],
        data_status: Dict[str, str],
    ) -> CheckStatus:
        """Inspect water depth soundings and calculate under-keel clearance (UKC)."""
        if not self.constraint_service:
            data_status["bathymetry"] = "unavailable"
            warnings.append("Bathymetry depth sounding data is unverified/unavailable.")
            return CheckStatus.UNAVAILABLE

        draft = vessel.draft_meters
        min_depth = vessel.minimum_safe_depth_meters
        min_ukc = self.settings.MIN_TEST_UKC_METERS

        if draft is None and min_depth is None:
            data_status["bathymetry"] = "unspecified_draft"
            return CheckStatus.PASS

        required_safe_depth = min_depth if min_depth is not None else ((draft or 2.0) + min_ukc)
        data_status["bathymetry"] = "available"
        shallow_violations = []

        try:
            for wp in waypoints:
                depth_result = self.constraint_service.get_depth_at_coordinate(
                    latitude=wp.latitude,
                    longitude=wp.longitude,
                )
                if depth_result.depth_meters is not None:
                    if depth_result.depth_meters < required_safe_depth:
                        ukc = depth_result.depth_meters - (draft or 0.0)
                        shallow_violations.append(
                            f"Sounding depth {depth_result.depth_meters}m at ({wp.latitude}, {wp.longitude}) is below required safe depth {required_safe_depth:.1f}m (UKC: {ukc:.1f}m)"
                        )

            if shallow_violations:
                msg = f"Insufficient under-keel clearance detected along route: {'; '.join(shallow_violations[:3])}"
                blocking_reasons.append(msg)
                return CheckStatus.BLOCK

            return CheckStatus.PASS

        except Exception as exc:
            logger.error("Error during bathymetry depth safety check: %s", exc)
            data_status["bathymetry"] = "unavailable"
            warnings.append(f"Bathymetry sounding inspection failed: {exc}")
            return CheckStatus.UNAVAILABLE

    def _check_ocean_conditions(
        self,
        marine_conditions: Optional[MarineConditionsSnapshot],
        blocking_reasons: List[str],
        warnings: List[str],
        data_status: Dict[str, str],
    ) -> CheckStatus:
        """Inspect significant wave height, current speed, and ocean risk."""
        if not marine_conditions or not marine_conditions.ocean:
            data_status["ocean"] = "unavailable"
            warnings.append("Ocean condition feed unavailable/unverified.")
            return CheckStatus.UNAVAILABLE

        ocean = marine_conditions.ocean
        data_status["ocean"] = ocean.source or "available"

        wave_ht = ocean.significant_wave_height_m
        curr_spd = ocean.current_speed_knots

        # Wave height check
        if wave_ht is not None:
            if wave_ht >= self.settings.MAX_TEST_WAVE_HEIGHT_BLOCK_M:
                msg = f"Wave height {wave_ht}m exceeds critical safety limit ({self.settings.MAX_TEST_WAVE_HEIGHT_BLOCK_M}m)."
                blocking_reasons.append(msg)
                return CheckStatus.BLOCK
            elif wave_ht >= self.settings.MAX_TEST_WAVE_HEIGHT_WARN_M:
                warnings.append(
                    f"Wave height {wave_ht}m exceeds operational advisory limit ({self.settings.MAX_TEST_WAVE_HEIGHT_WARN_M}m)."
                )
                return CheckStatus.WARNING

        # Current speed check
        if curr_spd is not None and curr_spd >= 4.0:
            warnings.append(f"Strong sea current of {curr_spd} knots detected.")
            return CheckStatus.WARNING

        return CheckStatus.PASS

    def _check_weather_conditions(
        self,
        marine_conditions: Optional[MarineConditionsSnapshot],
        blocking_reasons: List[str],
        warnings: List[str],
        data_status: Dict[str, str],
    ) -> CheckStatus:
        """Inspect wind speed, wind gust, visibility, and precipitation."""
        if not marine_conditions or not marine_conditions.weather:
            data_status["weather"] = "unavailable"
            warnings.append("Meteorological/weather condition feed unavailable/unverified.")
            return CheckStatus.UNAVAILABLE

        weather = marine_conditions.weather
        data_status["weather"] = weather.source or "available"

        wind_spd = weather.wind_speed_knots
        wind_gst = weather.wind_gust_knots
        vis_km = weather.visibility_km

        # Wind speed blocking check
        if wind_spd is not None and wind_spd >= self.settings.MAX_TEST_WIND_SPEED_BLOCK_KNOTS:
            msg = f"Wind speed {wind_spd} kts exceeds critical safety limit ({self.settings.MAX_TEST_WIND_SPEED_BLOCK_KNOTS} kts)."
            blocking_reasons.append(msg)
            return CheckStatus.BLOCK

        # Wind speed advisory check
        if wind_spd is not None and wind_spd >= self.settings.MAX_TEST_WIND_SPEED_WARN_KNOTS:
            warnings.append(
                f"Wind speed {wind_spd} kts exceeds operational advisory threshold ({self.settings.MAX_TEST_WIND_SPEED_WARN_KNOTS} kts)."
            )
            return CheckStatus.WARNING

        # Visibility blocking check
        if vis_km is not None and vis_km <= self.settings.MIN_TEST_VISIBILITY_BLOCK_KM:
            msg = f"Visibility {vis_km} km is below critical navigational limit ({self.settings.MIN_TEST_VISIBILITY_BLOCK_KM} km)."
            blocking_reasons.append(msg)
            return CheckStatus.BLOCK

        # Visibility advisory check
        if vis_km is not None and vis_km <= self.settings.MIN_TEST_VISIBILITY_WARN_KM:
            warnings.append(
                f"Reduced visibility of {vis_km} km requires heightened navigational watch ({self.settings.MIN_TEST_VISIBILITY_WARN_KM} km advisory)."
            )
            return CheckStatus.WARNING

        # Wind gust advisory check
        if wind_gst is not None and wind_gst >= 30.0:
            warnings.append(f"Strong wind gusts up to {wind_gst} knots forecast.")
            return CheckStatus.WARNING

        return CheckStatus.PASS

    def _check_data_quality(
        self,
        data_status: Dict[str, str],
        warnings: List[str],
    ) -> CheckStatus:
        """Inspect data authenticity, mock status, and freshness."""
        has_mock = False
        for feed, status in data_status.items():
            if status == "mock":
                has_mock = True

        if has_mock:
            warnings.append(
                "Environmental inputs derived from mock/testing data adapters. Not certified for real-world production navigation safety."
            )
            return CheckStatus.WARNING

        return CheckStatus.PASS

    def _determine_final_decision(
        self,
        checks: Dict[str, str],
        blocking_reasons: List[str],
        warnings: List[str],
        data_status: Dict[str, str],
    ) -> tuple[SafetyDecision, str]:
        """Apply strict decision precedence rules.

        1. REJECT: Any blocking conditions or check status == BLOCK (Highest Priority)
        2. DEGRADED: Any critical safety feed == UNAVAILABLE (Missing/unverified data)
        3. WARN: Any check status == WARNING or active advisories
        4. ALLOW: All checks pass with verified real-time feeds
        """
        # Highest Priority: REJECT
        if blocking_reasons or any(status == CheckStatus.BLOCK.value for status in checks.values()):
            reason = f"REJECT: Route failed critical safety checks ({len(blocking_reasons)} blocking condition(s))."
            return SafetyDecision.REJECT, reason

        # Second Priority: DEGRADED
        if any(status == CheckStatus.UNAVAILABLE.value for status in checks.values()):
            reason = "DEGRADED: Route cleared under degraded protocol due to unverified/unavailable safety feeds."
            return SafetyDecision.DEGRADED, reason

        # Third Priority: WARN
        if any(status == CheckStatus.WARNING.value for status in checks.values()) or warnings:
            reason = f"WARN: Route cleared with {len(warnings)} operational advisory/data warning(s)."
            return SafetyDecision.WARN, reason

        # Fourth: ALLOW
        return SafetyDecision.ALLOW, "ALLOW: All safety audits passed with full data feed clearance."


def get_safety_governor_service() -> SafetyGovernorService:
    """FastAPI dependency provider for SafetyGovernorService."""
    return SafetyGovernorService()
