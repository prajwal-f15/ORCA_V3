import logging
from typing import List, Tuple
from app.safety.schemas import (
    SafetyCheckRequest,
    SafetyDecision,
    SafetyReasonCode,
    SafetyStatus,
)

logger = logging.getLogger(__name__)


class SafetyRuleEngine:
    """
    Deterministic Safety Rule Engine.
    
    Evaluates maritime safety conditions in strict priority order:
    1. Invalid Coordinates (REJECT)
    2. Restricted Zone (REJECT)
    3. Extreme Weather (REJECT)
    4. High Marine Risk >= 80 (REJECT)
    5. Critical Data Missing (DEGRADED)
    6. Moderate Marine Risk [50, 80) (WARN)
    7. Low Risk / No Blocking Condition (ALLOW)
    """

    @classmethod
    def evaluate(
        cls, request: SafetyCheckRequest
    ) -> Tuple[SafetyDecision, str, str, List[str], List[str]]:
        """
        Evaluate safety request against deterministic rules in priority order.
        
        Returns:
            Tuple of (decision, status, reason_code, reasons, warnings)
        """
        reasons: List[str] = []
        warnings: List[str] = []

        # -------------------------------------------------------------
        # 1. Invalid Coordinates (Priority 1 - REJECT)
        # -------------------------------------------------------------
        if request.location:
            lat = request.location.latitude
            lon = request.location.longitude

            if lat is not None and (lat < -90.0 or lat > 90.0):
                msg = f"Latitude {lat} is out of valid range [-90.0, 90.0]."
                reasons.append(msg)
                return (
                    SafetyDecision.REJECT,
                    SafetyStatus.INVALID_LOCATION.value,
                    SafetyReasonCode.INVALID_COORDINATES.value,
                    reasons,
                    warnings,
                )

            if lon is not None and (lon < -180.0 or lon > 180.0):
                msg = f"Longitude {lon} is out of valid range [-180.0, 180.0]."
                reasons.append(msg)
                return (
                    SafetyDecision.REJECT,
                    SafetyStatus.INVALID_LOCATION.value,
                    SafetyReasonCode.INVALID_COORDINATES.value,
                    reasons,
                    warnings,
                )

        # -------------------------------------------------------------
        # 2. Restricted Zone (Priority 2 - REJECT)
        # -------------------------------------------------------------
        if request.restricted_zone:
            msg = "Operation or route intersects a restricted maritime zone or security boundary."
            reasons.append(msg)
            return (
                SafetyDecision.REJECT,
                SafetyStatus.ROUTE_NOT_ALLOWED.value,
                SafetyReasonCode.RESTRICTED_ZONE.value,
                reasons,
                warnings,
            )

        # -------------------------------------------------------------
        # 3. Extreme Weather (Priority 3 - REJECT)
        # -------------------------------------------------------------
        if request.weather and request.weather.extreme:
            msg = "Extreme weather or storm/cyclone advisory in operating area."
            reasons.append(msg)
            return (
                SafetyDecision.REJECT,
                SafetyStatus.TRIP_NOT_RECOMMENDED.value,
                SafetyReasonCode.EXTREME_WEATHER.value,
                reasons,
                warnings,
            )

        # -------------------------------------------------------------
        # 4. High Marine Risk >= 80 (Priority 4 - REJECT)
        # -------------------------------------------------------------
        if request.marine_risk is not None and request.marine_risk >= 80.0:
            msg = f"Marine risk score is {request.marine_risk} (>= 80 threshold)."
            reasons.append(msg)
            return (
                SafetyDecision.REJECT,
                SafetyStatus.TRIP_NOT_RECOMMENDED.value,
                SafetyReasonCode.HIGH_MARINE_RISK.value,
                reasons,
                warnings,
            )

        # -------------------------------------------------------------
        # 5. Critical Data Missing (Priority 5 - DEGRADED)
        # -------------------------------------------------------------
        if request.critical_data_missing:
            msg = "Critical maritime safety data is missing or unverified."
            reasons.append(msg)
            return (
                SafetyDecision.DEGRADED,
                SafetyStatus.SAFETY_DATA_UNAVAILABLE.value,
                SafetyReasonCode.CRITICAL_DATA_MISSING.value,
                reasons,
                warnings,
            )

        if request.require_marine_risk and request.marine_risk is None:
            msg = "Marine risk evaluation is required but risk data is missing."
            reasons.append(msg)
            return (
                SafetyDecision.DEGRADED,
                SafetyStatus.SAFETY_DATA_UNAVAILABLE.value,
                SafetyReasonCode.CRITICAL_DATA_MISSING.value,
                reasons,
                warnings,
            )

        # -------------------------------------------------------------
        # 6. Moderate Marine Risk [50, 80) (Priority 6 - WARN)
        # -------------------------------------------------------------
        if request.marine_risk is not None and 50.0 <= request.marine_risk < 80.0:
            warn_msg = f"Moderate marine risk detected: {request.marine_risk}."
            warnings.append(warn_msg)
            reasons.append(warn_msg)
            return (
                SafetyDecision.WARN,
                SafetyStatus.CAUTION_REQUIRED.value,
                SafetyReasonCode.MODERATE_MARINE_RISK.value,
                reasons,
                warnings,
            )

        # -------------------------------------------------------------
        # 7. Low Risk / No Blocking Condition (Priority 7 - ALLOW)
        # -------------------------------------------------------------
        reasons.append("All deterministic safety checks passed.")
        return (
            SafetyDecision.ALLOW,
            SafetyStatus.SAFETY_CHECK_PASSED.value,
            SafetyReasonCode.NO_BLOCKING_CONDITION.value,
            reasons,
            warnings,
        )
