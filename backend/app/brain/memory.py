import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from app.schemas.brain import ChatMessage


class ConversationMemoryManager:
    """In-memory conversation history manager with sliding window retention."""

    def __init__(self, max_history_messages: int = 8):
        self.max_history_messages = max_history_messages
        self._sessions: Dict[str, List[ChatMessage]] = {}
        self._lock = asyncio.Lock()

    async def get_or_create_session_id(self, session_id: Optional[str] = None) -> str:
        """Return the provided session_id or generate a new UUID4 string."""
        if session_id and session_id.strip():
            return session_id.strip()
        return str(uuid.uuid4())

    async def get_history(self, session_id: str) -> List[ChatMessage]:
        """Retrieve all messages for a given session."""
        async with self._lock:
            return list(self._sessions.get(session_id, []))

    async def get_messages_for_llm(self, session_id: str) -> List[Dict[str, str]]:
        """Retrieve previous messages formatted as role/content dicts for Ollama."""
        async with self._lock:
            history = self._sessions.get(session_id, [])
            return [{"role": msg.role, "content": msg.content} for msg in history]

    async def add_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        """
        Append a new message to the session history.
        Enforces max_history_messages limit by discarding oldest messages.
        """
        message = ChatMessage(
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc),
        )

        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []

            self._sessions[session_id].append(message)

            # Apply sliding window truncation
            if len(self._sessions[session_id]) > self.max_history_messages:
                self._sessions[session_id] = self._sessions[session_id][-self.max_history_messages:]

        return message

    async def clear_session(self, session_id: str) -> bool:
        """Clear conversation history for a given session."""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    async def get_total_turns(self, session_id: str) -> int:
        """Return the total number of messages in the session."""
        async with self._lock:
            return len(self._sessions.get(session_id, []))


# Global singleton instance
memory_manager = ConversationMemoryManager(max_history_messages=20)
