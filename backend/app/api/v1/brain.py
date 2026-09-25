from fastapi import APIRouter, HTTPException, status
from app.brain.memory import memory_manager
from app.brain.ollama_client import OllamaServiceError
from app.brain.orchestrator import orchestrator
from app.brain.planner import intent_planner
from app.brain.service import brain_service
from app.schemas.brain import (
    ChatRequest,
    ChatResponse,
    SessionDeleteResponse,
    SessionHistoryResponse,
)
from app.schemas.orchestrator import OrchestrateRequest, OrchestrateResponse
from app.schemas.planner import PlanRequest, PlanResponse

router = APIRouter(prefix="/brain", tags=["Brain"])


@router.post("/chat", response_model=ChatResponse, summary="Chat with ORCA Brain")
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Process a user message through ORCA Brain with multi-turn session memory.

    Raises:
        HTTPException 503: If Ollama server is unreachable or offline.
    """
    try:
        reply, session_id, turns = await brain_service.generate_response(
            user_message=request.message,
            session_id=request.session_id,
        )
        return ChatResponse(
            response=reply,
            session_id=session_id,
            turns_count=turns,
        )
    except OllamaServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc


@router.post("/plan", response_model=PlanResponse, summary="Generate Intent Plan")
async def plan(request: PlanRequest) -> PlanResponse:
    """
    Classify a natural language mariner query into a structured intent, tool target, and parameters.

    Raises:
        HTTPException 503: If Ollama server is unreachable.
    """
    try:
        return await intent_planner.plan(user_message=request.message)
    except OllamaServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc


@router.post(
    "/orchestrate",
    response_model=OrchestrateResponse,
    summary="Orchestrate Intent & Tool Execution",
)
async def orchestrate_request(request: OrchestrateRequest) -> OrchestrateResponse:
    """
    Orchestrate a mariner query through Intent Planning, Deterministic Tool Dispatching,
    and Safety Layer verification.
    """
    try:
        return await orchestrator.orchestrate(
            user_message=request.message,
            session_id=request.session_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal orchestration error: {exc}",
        ) from exc


@router.get(
    "/sessions/{session_id}",
    response_model=SessionHistoryResponse,
    summary="Get Conversation History",
)
async def get_session_history(session_id: str) -> SessionHistoryResponse:
    """Retrieve full conversation message history for a specific session."""
    history = await memory_manager.get_history(session_id)
    return SessionHistoryResponse(
        session_id=session_id,
        messages=history,
        total_messages=len(history),
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionDeleteResponse,
    summary="Clear Conversation History",
)
async def delete_session(session_id: str) -> SessionDeleteResponse:
    """Purge and reset conversation history for a specific session."""
    await memory_manager.clear_session(session_id)
    return SessionDeleteResponse(session_id=session_id)
