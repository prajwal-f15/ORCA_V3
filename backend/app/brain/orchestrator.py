import logging
import uuid
from typing import Any, Dict, Optional

from app.brain.planner import IntentPlanner, intent_planner
from app.safety.governor import SafetyGovernor, safety_governor
from app.safety.schemas import (
    LocationCoordinate,
    SafetyCheckRequest,
    SafetyDecision,
    WeatherCondition,
)
from app.schemas.orchestrator import OrchestrateResponse
from app.schemas.planner import IntentType, PlanResponse
from app.tools.registry import ToolRegistry, tool_registry

logger = logging.getLogger(__name__)


class ORCAOrchestrator:
    """
    Orchestration layer for ORCA Brain with deterministic Safety Governance.
    
    Flow:
    User Request
        ↓
    Intent Planner (Step 2)
        ↓
    Tool Dispatcher (Deterministic routing)
        ↓
    Selected Tool Execution (Stub / Future Real Models)
        ↓
    Safety Governor (Deterministic rule enforcement)
        ↓
    Structured Orchestration Response
    """

    def __init__(
        self,
        planner: Optional[IntentPlanner] = None,
        registry: Optional[ToolRegistry] = None,
        governor: Optional[SafetyGovernor] = None,
    ):
        self.planner = planner or intent_planner
        self.registry = registry or tool_registry
        self.governor = governor or safety_governor

    async def _apply_safety_check(
        self,
        tool_result: Optional[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> str:
        """
        Evaluate deterministic Safety Governor layer.
        Ensures all tool results pass through safety verification before final response preparation.
        
        If the tool is not implemented / stub / error, does NOT invent a fake safety decision and returns 'not_implemented'.
        If real safety data is present, runs deterministic safety rules.
        """
        # If tool execution was stubbed, in error state, or no tool executed, preserve not_implemented
        if not tool_result or tool_result.get("status") in ("not_implemented", "error"):
            return "not_implemented"

        try:
            # Build safety request from tool result data
            loc = None
            if "location" in tool_result and isinstance(tool_result["location"], dict):
                loc = LocationCoordinate(
                    latitude=tool_result["location"].get("latitude"),
                    longitude=tool_result["location"].get("longitude"),
                )

            weather_cond = None
            if "weather" in tool_result and isinstance(tool_result["weather"], dict):
                weather_cond = WeatherCondition(
                    extreme=bool(tool_result["weather"].get("extreme", False))
                )

            safety_req = SafetyCheckRequest(
                request_id=context.get("request_id"),
                location=loc,
                marine_risk=tool_result.get("marine_risk"),
                weather=weather_cond,
                restricted_zone=bool(tool_result.get("restricted_zone", False)),
                critical_data_missing=bool(tool_result.get("critical_data_missing", False)),
            )

            safety_eval = self.governor.evaluate(safety_req)
            return safety_eval.decision.value
        except Exception as exc:
            logger.error("[%s] Safety evaluation error: %s", context.get("request_id"), exc)
            return "not_implemented"

    async def orchestrate(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> OrchestrateResponse:
        """
        Orchestrate a user query from intent classification to tool dispatching and response preparation.
        """
        # 1. Generate or maintain traceable request_id
        req_id = request_id or str(uuid.uuid4())
        logger.info("[%s] Starting orchestration for query: '%s'", req_id, user_message)

        # 2. Step 2 Intent Planning
        try:
            plan: PlanResponse = await self.planner.plan(user_message=user_message)
        except Exception as exc:
            logger.error("[%s] Planner failure for query '%s': %s", req_id, user_message, exc)
            return OrchestrateResponse(
                request_id=req_id,
                intent=IntentType.UNKNOWN.value,
                tool=None,
                confidence=0.0,
                parameters={"raw_message": user_message},
                tool_status="error",
                tool_result={"status": "error", "message": f"Planner error: {exc}"},
                safety_status="not_implemented",
            )

        logger.info(
            "[%s] Plan result: intent='%s', tool='%s', confidence=%.2f",
            req_id,
            plan.intent,
            plan.tool,
            plan.confidence,
        )

        intent = plan.intent
        tool_name = plan.tool
        tool_status: str
        tool_result: Optional[Dict[str, Any]] = None

        # 3. Deterministic Tool Dispatching Strategy
        if intent == IntentType.GENERAL_ORCA_CHAT.value:
            tool_name = None
            tool_status = "not_required"
            tool_result = None

        elif intent == IntentType.MISSING_INFORMATION.value:
            tool_name = None
            tool_status = "needs_information"
            tool_result = None

        elif intent == IntentType.UNKNOWN.value or not tool_name:
            tool_name = None
            tool_status = "unknown_intent"
            tool_result = None

        else:
            # Look up tool in registry
            tool = self.registry.get_tool(tool_name)
            if not tool:
                logger.warning("[%s] Tool '%s' not found in registry", req_id, tool_name)
                tool_status = "error"
                tool_result = {
                    "status": "error",
                    "tool": tool_name,
                    "message": f"Tool '{tool_name}' is not registered in ORCA tool registry.",
                }
            else:
                try:
                    logger.info("[%s] Executing tool: '%s'", req_id, tool_name)
                    context = {
                        "request_id": req_id,
                        "session_id": session_id,
                        "intent": intent,
                    }
                    tool_result = await tool.execute(parameters=plan.parameters, context=context)
                    tool_status = tool_result.get("status", "executed")
                except Exception as exc:
                    logger.error("[%s] Tool execution failure for '%s': %s", req_id, tool_name, exc)
                    tool_status = "error"
                    tool_result = {
                        "status": "error",
                        "tool": tool_name,
                        "message": f"Tool execution failed: {exc}",
                    }

        # 4. Mandatory Deterministic Safety Verification Layer
        safety_status = await self._apply_safety_check(
            tool_result=tool_result,
            context={"request_id": req_id, "intent": intent, "tool": tool_name},
        )

        # 5. Build and return structured OrchestrateResponse
        response = OrchestrateResponse(
            request_id=req_id,
            intent=intent,
            tool=tool_name,
            confidence=plan.confidence,
            parameters=plan.parameters,
            tool_status=tool_status,
            tool_result=tool_result,
            safety_status=safety_status,
        )

        logger.info(
            "[%s] Orchestration completed: intent='%s', tool='%s', tool_status='%s', safety_status='%s'",
            req_id,
            response.intent,
            response.tool,
            response.tool_status,
            response.safety_status,
        )
        return response


# Global singleton orchestrator
orchestrator = ORCAOrchestrator()
