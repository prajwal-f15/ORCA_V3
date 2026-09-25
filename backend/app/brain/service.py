import logging
from typing import Optional, Tuple
from app.brain.memory import ConversationMemoryManager, memory_manager
from app.brain.ollama_client import OllamaClient
from app.brain.prompts import ORCA_BRAIN_SYSTEM_PROMPT
from app.config import get_settings

logger = logging.getLogger(__name__)


class BrainService:
    """Service layer managing ORCA Brain interactions, system prompts, and conversation memory."""

    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        memory: Optional[ConversationMemoryManager] = None,
    ):
        self.client = ollama_client or OllamaClient()
        self.memory = memory or memory_manager
        self.settings = get_settings()

    async def generate_response(
        self,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> Tuple[str, str, int]:
        """
        Generate a response for the user's message incorporating multi-turn conversation history.

        Args:
            user_message: Input text from the user.
            session_id: Optional session identifier.

        Returns:
            Tuple containing:
                - response string
                - active session_id
                - total turns count in this session
        """
        active_session_id = await self.memory.get_or_create_session_id(session_id)

        # Retrieve prior context (bounded sliding window)
        prior_messages = await self.memory.get_messages_for_llm(active_session_id)

        # Build full LLM prompt context with streamlined system instructions
        llm_messages = [{"role": "system", "content": ORCA_BRAIN_SYSTEM_PROMPT}]
        llm_messages.extend(prior_messages)
        llm_messages.append({"role": "user", "content": user_message})

        # Call Ollama with optimized parameters (think=False, num_predict bounded, keep_alive warm)
        reply = await self.client.chat(
            messages=llm_messages,
            think=False,
            keep_alive=self.settings.OLLAMA_KEEP_ALIVE,
            options={
                "num_predict": self.settings.OLLAMA_NUM_PREDICT,
                "num_ctx": self.settings.OLLAMA_NUM_CTX,
                "temperature": self.settings.OLLAMA_TEMPERATURE,
                "top_p": 0.8,
            },
        )

        clean_reply = reply.strip()

        # Record turns to memory
        await self.memory.add_message(
            session_id=active_session_id,
            role="user",
            content=user_message,
        )
        await self.memory.add_message(
            session_id=active_session_id,
            role="assistant",
            content=clean_reply,
        )

        total_turns = await self.memory.get_total_turns(active_session_id)
        return clean_reply, active_session_id, total_turns


# Default singleton instance
brain_service = BrainService()
