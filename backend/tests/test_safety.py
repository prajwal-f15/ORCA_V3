import os
import sys
import unittest

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.safety.governor import SafetyGovernor, safety_governor
from app.safety.schemas import (
    LocationCoordinate,
    SafetyCheckRequest,
    SafetyDecision,
    SafetyReasonCode,
    SafetyStatus,
    WeatherCondition,
)

sys.stdout.reconfigure(encoding="utf-8")


class TestSafetyGovernor(unittest.TestCase):
    """Unit test suite for ORCA V3 Step 4: Safety Governor."""

    def setUp(self):
        self.governor = SafetyGovernor()

    def test_01_high_marine_risk_85(self):
        """Test Case 1: marine_risk = 85 -> REJECT / TRIP_NOT_RECOMMENDED."""
        req = SafetyCheckRequest(
            request_id="test-01",
            marine_risk=85.0,
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.REJECT)
        self.assertEqual(resp.status, SafetyStatus.TRIP_NOT_RECOMMENDED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.HIGH_MARINE_RISK.value)
        self.assertTrue(any("85" in r for r in resp.reasons))

    def test_02_high_marine_risk_boundary_80(self):
        """Test Case 2: marine_risk = 80 (boundary) -> REJECT."""
        req = SafetyCheckRequest(
            request_id="test-02",
            marine_risk=80.0,
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.REJECT)
        self.assertEqual(resp.status, SafetyStatus.TRIP_NOT_RECOMMENDED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.HIGH_MARINE_RISK.value)

    def test_03_moderate_marine_risk_boundary_79(self):
        """Test Case 3: marine_risk = 79 -> WARN / CAUTION_REQUIRED."""
        req = SafetyCheckRequest(
            request_id="test-03",
            marine_risk=79.0,
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.WARN)
        self.assertEqual(resp.status, SafetyStatus.CAUTION_REQUIRED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.MODERATE_MARINE_RISK.value)
        self.assertTrue(len(resp.warnings) > 0)

    def test_04_moderate_marine_risk_boundary_50(self):
        """Test Case 4: marine_risk = 50 -> WARN / CAUTION_REQUIRED."""
        req = SafetyCheckRequest(
            request_id="test-04",
            marine_risk=50.0,
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.WARN)
        self.assertEqual(resp.status, SafetyStatus.CAUTION_REQUIRED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.MODERATE_MARINE_RISK.value)

    def test_05_low_marine_risk_49(self):
        """Test Case 5: marine_risk = 49 -> ALLOW with valid safety data."""
        req = SafetyCheckRequest(
            request_id="test-05",
            marine_risk=49.0,
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.ALLOW)
        self.assertEqual(resp.status, SafetyStatus.SAFETY_CHECK_PASSED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.NO_BLOCKING_CONDITION.value)

    def test_06_extreme_weather(self):
        """Test Case 6: weather.extreme = True -> REJECT."""
        req = SafetyCheckRequest(
            request_id="test-06",
            weather=WeatherCondition(extreme=True),
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.REJECT)
        self.assertEqual(resp.status, SafetyStatus.TRIP_NOT_RECOMMENDED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.EXTREME_WEATHER.value)

    def test_07_restricted_zone(self):
        """Test Case 7: restricted_zone = True -> REJECT / ROUTE_NOT_ALLOWED."""
        req = SafetyCheckRequest(
            request_id="test-07",
            restricted_zone=True,
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.REJECT)
        self.assertEqual(resp.status, SafetyStatus.ROUTE_NOT_ALLOWED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.RESTRICTED_ZONE.value)

    def test_08_invalid_latitude(self):
        """Test Case 8: latitude > 90 -> REJECT / INVALID_LOCATION."""
        req = SafetyCheckRequest(
            request_id="test-08",
            location=LocationCoordinate(latitude=95.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.REJECT)
        self.assertEqual(resp.status, SafetyStatus.INVALID_LOCATION.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.INVALID_COORDINATES.value)

    def test_09_invalid_longitude(self):
        """Test Case 9: longitude < -180 -> REJECT / INVALID_LOCATION."""
        req = SafetyCheckRequest(
            request_id="test-09",
            location=LocationCoordinate(latitude=15.0, longitude=-185.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.REJECT)
        self.assertEqual(resp.status, SafetyStatus.INVALID_LOCATION.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.INVALID_COORDINATES.value)

    def test_10_missing_critical_data(self):
        """Test Case 10: critical_data_missing = True -> DEGRADED."""
        req = SafetyCheckRequest(
            request_id="test-10",
            critical_data_missing=True,
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.DEGRADED)
        self.assertEqual(resp.status, SafetyStatus.SAFETY_DATA_UNAVAILABLE.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.CRITICAL_DATA_MISSING.value)

    def test_11_missing_marine_risk_when_required(self):
        """Test Case 11: missing marine_risk when required -> DEGRADED (NOT ALLOW)."""
        req = SafetyCheckRequest(
            request_id="test-11",
            marine_risk=None,
            require_marine_risk=True,
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.DEGRADED)
        self.assertEqual(resp.status, SafetyStatus.SAFETY_DATA_UNAVAILABLE.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.CRITICAL_DATA_MISSING.value)
        self.assertNotEqual(resp.decision, SafetyDecision.ALLOW)

    def test_12_multiple_dangerous_conditions_priority(self):
        """Test Case 12: Multiple danger conditions -> deterministic highest-priority REJECT."""
        # Invalid coordinates (P1) + Restricted zone (P2) + Extreme weather (P3) + High risk (P4)
        req = SafetyCheckRequest(
            request_id="test-12-p1",
            location=LocationCoordinate(latitude=105.0, longitude=73.0),  # P1
            restricted_zone=True,  # P2
            weather=WeatherCondition(extreme=True),  # P3
            marine_risk=90.0,  # P4
        )
        resp = self.governor.evaluate(req)
        self.assertEqual(resp.decision, SafetyDecision.REJECT)
        self.assertEqual(resp.reason_code, SafetyReasonCode.INVALID_COORDINATES.value)

        # Restricted zone (P2) + Extreme weather (P3) + High risk (P4)
        req2 = SafetyCheckRequest(
            request_id="test-12-p2",
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
            restricted_zone=True,  # P2
            weather=WeatherCondition(extreme=True),  # P3
            marine_risk=90.0,  # P4
        )
        resp2 = self.governor.evaluate(req2)
        self.assertEqual(resp2.decision, SafetyDecision.REJECT)
        self.assertEqual(resp2.reason_code, SafetyReasonCode.RESTRICTED_ZONE.value)

        # Extreme weather (P3) + High risk (P4)
        req3 = SafetyCheckRequest(
            request_id="test-12-p3",
            location=LocationCoordinate(latitude=15.0, longitude=73.0),
            weather=WeatherCondition(extreme=True),  # P3
            marine_risk=90.0,  # P4
        )
        resp3 = self.governor.evaluate(req3)
        self.assertEqual(resp3.decision, SafetyDecision.REJECT)
        self.assertEqual(resp3.reason_code, SafetyReasonCode.EXTREME_WEATHER.value)

    def test_13_safe_valid_input(self):
        """Test Case 13: Clean input with marine_risk=20, extreme=False -> ALLOW."""
        req = SafetyCheckRequest(
            request_id="test-13",
            location=LocationCoordinate(latitude=15.5, longitude=73.8),
            marine_risk=20.0,
            weather=WeatherCondition(extreme=False),
            restricted_zone=False,
            critical_data_missing=False,
        )
        resp = self.governor.evaluate(req)

        self.assertEqual(resp.decision, SafetyDecision.ALLOW)
        self.assertEqual(resp.status, SafetyStatus.SAFETY_CHECK_PASSED.value)
        self.assertEqual(resp.reason_code, SafetyReasonCode.NO_BLOCKING_CONDITION.value)
        self.assertEqual(len(resp.warnings), 0)


def main():
    print("=" * 70, flush=True)
    print("ORCA STEP 4: SAFETY GOVERNOR TEST SUITE", flush=True)
    print("=" * 70, flush=True)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestSafetyGovernor)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70, flush=True)
    if result.wasSuccessful():
        print(f"FINAL RESULT: ALL {result.testsRun} SAFETY TESTS PASSED!", flush=True)
    else:
        print(f"FINAL RESULT: {len(result.failures)} FAILURES, {len(result.errors)} ERRORS", flush=True)
    print("=" * 70, flush=True)

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
