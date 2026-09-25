import json
import logging
import re
from typing import Any, Dict, Optional

from app.brain.ollama_client import OllamaClient
from app.config import get_settings
from app.schemas.planner import IntentType, PlanResponse
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# Concise, high-precision prompt (~80 tokens) for instant CPU inference
FAST_INTENT_SYSTEM_PROMPT = """You are ORCA Brain Intent Router.
Classify the user query into a concise JSON object.
Allowed intents:
- "fishing_potential": where/when to fish, best fishing spots, fishing conditions
- "marine_safety": is it safe to sail, danger alerts
- "route_optimization": navigation routes, waypoints, directions
- "weather_information": wind, waves, rain, cyclone forecasts
- "pfz_analysis": PFZ coordinates, INCOIS map
- "ocean_analysis": sea temperature, ocean currents, salinity
- "marine_risk": hazards, rough sea warnings
- "historical_productivity": past catch records
- "marine_suitability": trip suitability
- "general_orca_chat": greetings, identity
- "missing_information": incomplete fragments
- "unknown": unrelated topics

Rules:
1. "parameters" must ONLY contain entities explicitly mentioned in the query. Never invent fields.
2. Return ONLY: {"intent": "<name>", "confidence": 0.95, "needs_location": false, "needs_date": false, "parameters": {}}"""

# Backward compatibility alias
INTENT_ROUTER_SYSTEM_PROMPT = FAST_INTENT_SYSTEM_PROMPT


class IntentPlanner:
    """Classifies user messages into structured ORCA intents using fast, optimized LLM inference."""

    def __init__(self, ollama_client: Optional[OllamaClient] = None):
        self.client = ollama_client or OllamaClient()
        self.settings = get_settings()

    def _clean_llm_output(self, raw_text: str) -> str:
        """Strip think tags, markdown fences, and repair JSON structure."""
        if not raw_text:
            return ""

        text = raw_text

        # Strip think blocks if any
        if "</think>" in text:
            text = text.split("</think>")[-1].strip()

        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.DOTALL).strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        if "{" in cleaned:
            start = cleaned.find("{")
            cleaned = cleaned[start:]

        # Clean trailing incomplete keys
        cleaned = re.sub(r',\s*"[^"]*":\s*([,}])', r'\1', cleaned)
        cleaned = re.sub(r',\s*"[^"]*":\s*$', '}', cleaned)
        cleaned = re.sub(r'{\s*"[^"]*":\s*$', '{}', cleaned)

        if not cleaned.endswith("}"):
            if cleaned.count("{") > cleaned.count("}"):
                cleaned = cleaned.rstrip(", :\"") + "}"

        return cleaned.strip()

    def _parse_and_validate(self, raw_text: str) -> Optional[PlanResponse]:
        """Attempt to parse JSON string into a validated PlanResponse with regex fallback."""
        if not raw_text:
            return None

        cleaned = self._clean_llm_output(raw_text)

        # 1. Full JSON parse attempt
        try:
            data = json.loads(cleaned)
            intent_val = str(data.get("intent", "unknown")).strip().lower()
            try:
                valid_intent = IntentType(intent_val).value
            except ValueError:
                valid_intent = "unknown"

            mapped_tool = tool_registry.get_tool_for_intent(valid_intent)
            return PlanResponse(
                intent=valid_intent,
                tool=mapped_tool,
                confidence=float(data.get("confidence", 0.95)),
                needs_location=bool(data.get("needs_location", False)),
                needs_date=bool(data.get("needs_date", False)),
                parameters=dict(data.get("parameters", {})),
            )
        except Exception:
            pass

        # 2. Resilient Regex Fallback for truncated/token-capped responses
        intent_match = re.search(r'"intent"\s*:\s*"([a-zA-Z_]+)"', raw_text)
        if intent_match:
            intent_val = intent_match.group(1).strip().lower()
            try:
                valid_intent = IntentType(intent_val).value
            except ValueError:
                valid_intent = "unknown"

            mapped_tool = tool_registry.get_tool_for_intent(valid_intent)
            conf = 0.95
            conf_match = re.search(r'"confidence"\s*:\s*([0-9.]+)', raw_text)
            if conf_match:
                try:
                    conf = float(conf_match.group(1))
                except ValueError:
                    conf = 0.95

            needs_loc = bool(re.search(r'"needs_location"\s*:\s*true', raw_text, re.IGNORECASE))
            needs_dt = bool(re.search(r'"needs_date"\s*:\s*true', raw_text, re.IGNORECASE))

            return PlanResponse(
                intent=valid_intent,
                tool=mapped_tool,
                confidence=conf,
                needs_location=needs_loc,
                needs_date=needs_dt,
                parameters={},
            )

        return None

    async def plan(self, user_message: str) -> PlanResponse:
        """
        Analyze the user's natural language message and return a structured PlanResponse.
        Uses direct /api/generate with think=False, low context, and bounded tokens for fast CPU inference.
        """
        prompt = f"{FAST_INTENT_SYSTEM_PROMPT}\n\nQuery: {user_message}"

        try:
            # 1. Fast direct JSON inference pass (512 ctx, low token budget)
            raw_response = await self.client.generate(
                prompt=prompt,
                format="json",
                think=False,
                keep_alive=self.settings.OLLAMA_KEEP_ALIVE,
                options={
                    "temperature": 0.0,
                    "num_predict": self.settings.OLLAMA_PLANNER_NUM_PREDICT,
                    "num_ctx": 512,
                    "top_p": 0.1,
                },
            )
            parsed = self._parse_and_validate(raw_response)
            if parsed is not None:
                return parsed

            # 2. Fast chat fallback if generate failed parsing
            logger.info("Retrying intent classification with chat fallback for: %s", user_message)
            messages = [
                {"role": "system", "content": FAST_INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Query: {user_message}"},
            ]
            chat_response = await self.client.chat(
                messages=messages,
                format="json",
                think=False,
                keep_alive=self.settings.OLLAMA_KEEP_ALIVE,
                options={
                    "temperature": 0.0,
                    "num_predict": self.settings.OLLAMA_PLANNER_NUM_PREDICT,
                    "num_ctx": 512,
                },
            )
            retry_parsed = self._parse_and_validate(chat_response)
            if retry_parsed is not None:
                return retry_parsed

        except Exception as exc:
            logger.error("Error during intent planning for '%s': %s", user_message, exc)

        # 3. Safe fallback if passes fail
        return PlanResponse(
            intent=IntentType.UNKNOWN.value,
            tool=None,
            confidence=0.0,
            needs_location=False,
            needs_date=False,
            parameters={"raw_message": user_message},
        )


# Global singleton planner instance
intent_planner = IntentPlanner()
