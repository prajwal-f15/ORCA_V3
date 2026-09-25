import asyncio
import sys
import unittest
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

# Ensure backend directory is in path
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.brain.orchestrator import ORCAOrchestrator
from app.schemas.orchestrator import OrchestrateResponse
from app.schemas.planner import PlanResponse
from app.tools.registry import BaseORCATool, ToolRegistry, tool_registry

sys.stdout.reconfigure(encoding="utf-8")


class FaultyTool(BaseORCATool):
    """Tool stub designed to raise an exception for testing error handling."""
    name = "faulty_tool"
    description = "A broken tool for unit testing."

    async def execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise RuntimeError("Simulated internal tool crash")


class MockRealMarineIntelligenceTool(BaseORCATool):
    """Mock tool simulating real tool execution for safety integration test."""
    name = "mock_real_marine"
    description = "Simulates real model output."

    def __init__(self, marine_risk: float = 20.0, restricted_zone: bool = False):
        self.marine_risk = marine_risk
        self.restricted_zone = restricted_zone

    async def execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "status": "executed",
            "marine_risk": self.marine_risk,
            "location": {"latitude": 15.0, "longitude": 73.0},
            "restricted_zone": self.restricted_zone,
            "critical_data_missing": False,
        }


class TestOrchestrator(unittest.IsolatedAsyncioTestCase):
    """Test suite for Step 3: ORCA Tool Dispatcher / Orchestrator."""

    async def asyncSetUp(self):
        self.mock_planner = AsyncMock()
        self.registry = ToolRegistry()
        self.registry.register_tool(FaultyTool())
        self.orchestrator = ORCAOrchestrator(
            planner=self.mock_planner,
            registry=self.registry,
        )

    async def test_01_english_fishing_request(self):
        """Test Case 1: English fishing potential query."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="fishing_potential",
            tool="marine_intelligence",
            confidence=0.98,
            parameters={"location": None, "date": "today"},
        )

        resp: OrchestrateResponse = await self.orchestrator.orchestrate("Where should I go fishing today?")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "fishing_potential")
        self.assertEqual(resp.tool, "marine_intelligence")
        self.assertEqual(resp.tool_status, "not_implemented")
        self.assertIsNotNone(resp.tool_result)
        self.assertEqual(resp.tool_result.get("status"), "not_implemented")
        self.assertEqual(resp.tool_result.get("tool"), "marine_intelligence")
        self.assertIn("not connected yet", resp.tool_result.get("message", ""))
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_02_marathi_fishing_request(self):
        """Test Case 2: Marathi fishing potential query."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="fishing_potential",
            tool="marine_intelligence",
            confidence=0.96,
            parameters={"location": None, "date": "today"},
        )

        resp = await self.orchestrator.orchestrate("मला आज मासेमारीसाठी कुठे जायला योग्य आहे?")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "fishing_potential")
        self.assertEqual(resp.tool, "marine_intelligence")
        self.assertEqual(resp.tool_status, "not_implemented")
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_03_hindi_fishing_request(self):
        """Test Case 3: Hindi fishing potential query."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="fishing_potential",
            tool="marine_intelligence",
            confidence=0.95,
            parameters={"location": None, "date": "today"},
        )

        resp = await self.orchestrator.orchestrate("आज मछली पकड़ने के लिए कहाँ जाना चाहिए?")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "fishing_potential")
        self.assertEqual(resp.tool, "marine_intelligence")
        self.assertEqual(resp.tool_status, "not_implemented")
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_04_mixed_marathi_english_fishing_request(self):
        """Test Case 4: Mixed Marathi-English fishing query."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="fishing_potential",
            tool="marine_intelligence",
            confidence=0.97,
            parameters={"location": None, "date": "today"},
        )

        resp = await self.orchestrator.orchestrate("आज fishing साठी कोणता area चांगला आहे?")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "fishing_potential")
        self.assertEqual(resp.tool, "marine_intelligence")
        self.assertEqual(resp.tool_status, "not_implemented")
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_05_marine_safety_request(self):
        """Test Case 5: Marine safety inquiry."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="marine_safety",
            tool="safety_governor",
            confidence=0.99,
            parameters={},
        )

        resp = await self.orchestrator.orchestrate("Is it safe to go to sea today?")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "marine_safety")
        self.assertEqual(resp.tool, "safety_governor")
        self.assertEqual(resp.tool_status, "not_implemented")
        self.assertIsNotNone(resp.tool_result)
        self.assertEqual(resp.tool_result.get("tool"), "safety_governor")
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_06_route_request(self):
        """Test Case 6: Navigation route request."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="route_optimization",
            tool="route_engine",
            confidence=0.95,
            parameters={"destination": None},
        )

        resp = await self.orchestrator.orchestrate("मला सुरक्षित route हवा आहे.")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "route_optimization")
        self.assertEqual(resp.tool, "route_engine")
        self.assertEqual(resp.tool_status, "not_implemented")
        self.assertEqual(resp.tool_result.get("tool"), "route_engine")
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_07_general_chat(self):
        """Test Case 7: General chat query (no tool required)."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="general_orca_chat",
            tool=None,
            confidence=1.0,
            parameters={},
        )

        resp = await self.orchestrator.orchestrate("Hello ORCA")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "general_orca_chat")
        self.assertIsNone(resp.tool)
        self.assertEqual(resp.tool_status, "not_required")
        self.assertIsNone(resp.tool_result)
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_08_missing_information(self):
        """Test Case 8: Incomplete query requiring additional info."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="missing_information",
            tool=None,
            confidence=0.85,
            needs_location=True,
            parameters={},
        )

        resp = await self.orchestrator.orchestrate("मला fishing ला जायचं आहे.")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "missing_information")
        self.assertIsNone(resp.tool)
        self.assertEqual(resp.tool_status, "needs_information")
        self.assertIsNone(resp.tool_result)
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_09_unknown_intent(self):
        """Test Case 9: Completely out-of-scope query."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="unknown",
            tool=None,
            confidence=0.1,
            parameters={},
        )

        resp = await self.orchestrator.orchestrate("What is the stock price of Apple?")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "unknown")
        self.assertIsNone(resp.tool)
        self.assertEqual(resp.tool_status, "unknown_intent")
        self.assertIsNone(resp.tool_result)
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_10_tool_failure_handling(self):
        """Test Case 10: Tool execution error handled gracefully without crashing."""
        self.mock_planner.plan.return_value = PlanResponse(
            intent="custom_intent",
            tool="faulty_tool",
            confidence=0.9,
            parameters={},
        )

        resp = await self.orchestrator.orchestrate("Trigger faulty tool")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "custom_intent")
        self.assertEqual(resp.tool, "faulty_tool")
        self.assertEqual(resp.tool_status, "error")
        self.assertIsNotNone(resp.tool_result)
        self.assertEqual(resp.tool_result.get("status"), "error")
        self.assertIn("Simulated internal tool crash", resp.tool_result.get("message", ""))
        self.assertEqual(resp.safety_status, "not_implemented")

    async def test_11_planner_failure_handling(self):
        """Test Case 11: Planner exception handled gracefully with structured response."""
        self.mock_planner.plan.side_effect = RuntimeError("Ollama connection timed out")

        resp = await self.orchestrator.orchestrate("Any query when planner is down")

        self.assertTrue(resp.request_id)
        self.assertEqual(resp.intent, "unknown")
        self.assertIsNone(resp.tool)
        self.assertEqual(resp.tool_status, "error")
        self.assertIsNotNone(resp.tool_result)
        self.assertEqual(resp.tool_result.get("status"), "error")
        self.assertIn("Ollama connection timed out", resp.tool_result.get("message", ""))

    async def test_12_safety_governor_allow_integration(self):
        """Test Case 12: Tool returning clean data evaluates to ALLOW in Safety Governor."""
        self.registry.register_tool(MockRealMarineIntelligenceTool(marine_risk=20.0))
        self.mock_planner.plan.return_value = PlanResponse(
            intent="fishing_potential",
            tool="mock_real_marine",
            confidence=0.95,
            parameters={},
        )

        resp = await self.orchestrator.orchestrate("Test query with clean safety data")
        self.assertEqual(resp.tool_status, "executed")
        self.assertEqual(resp.safety_status, "ALLOW")

    async def test_13_safety_governor_reject_integration(self):
        """Test Case 13: Tool returning dangerous data evaluates to REJECT in Safety Governor."""
        self.registry.register_tool(MockRealMarineIntelligenceTool(marine_risk=88.0))
        self.mock_planner.plan.return_value = PlanResponse(
            intent="fishing_potential",
            tool="mock_real_marine",
            confidence=0.95,
            parameters={},
        )

        resp = await self.orchestrator.orchestrate("Test query with dangerous safety data")
        self.assertEqual(resp.tool_status, "executed")
        self.assertEqual(resp.safety_status, "REJECT")


def main():
    print("=" * 70, flush=True)
    print("ORCA STEP 3: ORCHESTRATOR & TOOL DISPATCHER TEST SUITE", flush=True)
    print("=" * 70, flush=True)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestOrchestrator)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70, flush=True)
    if result.wasSuccessful():
        print(f"FINAL RESULT: ALL {result.testsRun} TESTS PASSED!", flush=True)
    else:
        print(f"FINAL RESULT: {len(result.failures)} FAILURES, {len(result.errors)} ERRORS", flush=True)
    print("=" * 70, flush=True)

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
