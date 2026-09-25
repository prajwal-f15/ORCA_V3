from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class OrchestrateRequest(BaseModel):
    """Schema for an incoming query to be orchestrated."""

    message: str = Field(..., min_length=1, description="User query to plan and dispatch to ORCA tools")
    session_id: Optional[str] = Field(default=None, description="Optional session identifier for context")


class OrchestrateResponse(BaseModel):
    """Structured response from the ORCA Orchestrator layer."""

    request_id: str = Field(..., description="Unique traceability UUID for this orchestration cycle")
    intent: str = Field(..., description="Classified intent identifier")
    tool: Optional[str] = Field(default=None, description="Target tool dispatched, or None if no tool is required")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score of intent planning")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted or inferred query parameters",
    )
    tool_status: str = Field(
        ...,
        description="Execution status of the tool: 'executed', 'not_implemented', 'not_required', 'needs_information', 'unknown_intent', or 'error'",
    )
    tool_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured execution result returned by the tool, or null if no tool was executed",
    )
    safety_status: str = Field(
        default="not_implemented",
        description="Safety verification layer status placeholder ('not_implemented')",
    )
