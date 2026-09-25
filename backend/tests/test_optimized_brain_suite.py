import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.brain.memory import ConversationMemoryManager
from app.brain.ollama_client import OllamaClient, OllamaServiceError
from app.brain.planner import IntentPlanner, FAST_INTENT_SYSTEM_PROMPT
from app.brain.service import BrainService
from app.config import get_settings
from app.schemas.planner import IntentType


class TestOptimizedBrainUnit(unittest.IsolatedAsyncioTestCase):
    """Unit tests for optimized ORCA Brain, memory bounding, and intent planner."""

    async def asyncSetUp(self):
        self.mock_client = MagicMock()
        self.memory = ConversationMemoryManager(max_history_messages=8)
        self.service = BrainService(ollama_client=self.mock_client, memory=self.memory)

    async def test_multiturn_memory_retention(self):
        """Verify multi-turn conversation maintains user context across consecutive turns."""
        session_id = "test-multiturn-session"
        
        # Turn 1
        self.mock_client.chat = AsyncMock(
            return_value="मुंबईजवळ मासेमारीसाठी नक्की कोणत्या वेळेची माहिती हवी आहे?"
        )
        reply1, sess1, turns1 = await self.service.generate_response(
            user_message="मला मुंबईजवळ fishing करायची आहे.",
            session_id=session_id,
        )
        self.assertEqual(sess1, session_id)
        self.assertEqual(turns1, 2)  # 1 user + 1 assistant

        # Check call arguments for Turn 1
        call_args1 = self.mock_client.chat.call_args[1]
        messages1 = call_args1["messages"]
        self.assertEqual(len(messages1), 2)  # System + User1
        self.assertIn("मला मुंबईजवळ fishing करायची आहे.", messages1[1]["content"])

        # Turn 2 (contextual follow-up)
        self.mock_client.chat = AsyncMock(
            return_value="उद्या सकाळी मुंबईजवळ वारे 8-10 knots असतील, परिस्थिती अनुकूल आहे."
        )
        reply2, sess2, turns2 = await self.service.generate_response(
            user_message="उद्या सकाळी.",
            session_id=session_id,
        )
        self.assertEqual(sess2, session_id)
        self.assertEqual(turns2, 4)  # 2 user + 2 assistant

        # Check call arguments for Turn 2
        call_args2 = self.mock_client.chat.call_args[1]
        messages2 = call_args2["messages"]
        self.assertEqual(len(messages2), 4)  # System + User1 + Assistant1 + User2
        self.assertEqual(messages2[1]["content"], "मला मुंबईजवळ fishing करायची आहे.")
        self.assertEqual(messages2[2]["content"], "मुंबईजवळ मासेमारीसाठी नक्की कोणत्या वेळेची माहिती हवी आहे?")
        self.assertEqual(messages2[3]["content"], "उद्या सकाळी.")

    async def test_memory_sliding_window_bound(self):
        """Verify memory limits to max_history_messages (8 messages)."""
        session_id = "bounded-session"
        self.mock_client.chat = AsyncMock(return_value="Acknowledged")

        for i in range(10):
            await self.service.generate_response(
                user_message=f"Query {i}",
                session_id=session_id,
            )

        history = await self.memory.get_messages_for_llm(session_id)
        self.assertLessEqual(len(history), 8)

    async def test_planner_options_and_classification(self):
        """Verify planner uses think=False and correct intent mapping."""
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(
            return_value='{"intent": "route_optimization", "confidence": 0.96, "needs_location": true, "needs_date": false, "parameters": {"origin": "Mumbai", "destination": "Goa"}}'
        )
        planner = IntentPlanner(ollama_client=mock_client)

        plan = await planner.plan("Mumbai se Goa ka safe route dikhao")
        self.assertEqual(plan.intent, "route_optimization")
        self.assertEqual(plan.tool, "route_engine")
        self.assertTrue(plan.needs_location)
        self.assertEqual(plan.parameters["origin"], "Mumbai")

        # Verify options passed to client.generate
        call_kwargs = mock_client.generate.call_args[1]
        self.assertFalse(call_kwargs["think"])
        self.assertEqual(call_kwargs["format"], "json")
        self.assertEqual(call_kwargs["options"]["num_predict"], 64)

    def test_ollama_client_default_options(self):
        """Verify OllamaClient initializes with optimized default parameters."""
        client = OllamaClient()
        settings = get_settings()
        self.assertFalse(client.default_think)
        self.assertEqual(client.default_keep_alive, "1h")
        self.assertEqual(client.default_num_predict, 128)
        self.assertEqual(client.default_num_ctx, 1024)

        opts = client._build_effective_options({"temperature": 0.0})
        self.assertEqual(opts["num_predict"], 128)
        self.assertEqual(opts["num_ctx"], 1024)
        self.assertEqual(opts["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()
