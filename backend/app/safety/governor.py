import logging
import uuid
from typing import Optional

from app.safety.rules import SafetyRuleEngine
from app.safety.schemas import SafetyCheckRequest, SafetyCheckResponse

logger = logging.getLogger(__name__)


class SafetyGovernor:
    """
    ORCA Deterministic Safety Governor.
    
    Enforces hard, immutable safety boundaries for maritime navigation,
    fishing operations, and voyage safety.
    
    Principles:
    - 100% deterministic Python logic
    - Zero LLM/Qwen dependency
    - Evaluates in strict priority order (Coordinates -> Restrictions -> Weather -> High Risk -> Missing Data -> Moderate Risk -> Allow)
    - Decisions: ALLOW, WARN, REJECT, DEGRADED
    """

    def __init__(self):
        self.rule_engine = SafetyRuleEngine()

    def evaluate(self, request: SafetyCheckRequest) -> SafetyCheckResponse:
        """
        Evaluate a safety check request and return a structured, immutable safety response.
        """
        req_id = request.request_id or str(uuid.uuid4())

        decision, status_val, reason_code, reasons, warnings = self.rule_engine.evaluate(request)

        logger.info(
            "[%s] Safety Governor evaluation: decision='%s', status='%s', reason_code='%s'",
            req_id,
            decision.value,
            status_val,
            reason_code,
        )

        return SafetyCheckResponse(
            request_id=req_id,
            decision=decision,
            status=status_val,
            reason_code=reason_code,
            reasons=reasons,
            warnings=warnings,
        )


# Global singleton safety governor
safety_governor = SafetyGovernor()
