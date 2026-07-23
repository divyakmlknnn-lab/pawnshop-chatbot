import unittest
from unittest.mock import patch

from intent import classify_intent

import llm_chat


class ChatRoutingTests(unittest.TestCase):
    def test_ltv_query_is_not_operationally_ready(self):
        classification = classify_intent("What's the LTV of Priya?")
        self.assertFalse(llm_chat._can_execute_operationally(classification))
        self.assertEqual(classification.intent, "CUSTOMER_LOANS")

    def test_named_customer_summary_is_operationally_ready(self):
        classification = classify_intent("Tell me about Priya Nair")
        self.assertTrue(llm_chat._can_execute_operationally(classification))

    def test_overdue_query_is_operationally_ready(self):
        classification = classify_intent("Who is overdue?")
        self.assertTrue(llm_chat._can_execute_operationally(classification))

    @patch("llm_chat._chat_with_gemini")
    @patch("llm_chat._execute_classification")
    def test_incomplete_customer_query_routes_to_gemini(
        self,
        mock_execute,
        mock_gemini,
    ):
        mock_gemini.return_value = {
            "reply": "<p>LTV is 72.5%.</p>",
            "format": "html",
            "history_text": "Answered with Gemini using conversation context.",
            "tools_used": [],
        }

        result = llm_chat.chat("What's the LTV of Priya?")

        mock_execute.assert_not_called()
        mock_gemini.assert_called_once()
        self.assertIn("reply", result)

    @patch("llm_chat._chat_with_gemini")
    @patch("llm_chat._execute_classification")
    def test_complete_customer_summary_uses_operational_fast_path(
        self,
        mock_execute,
        mock_gemini,
    ):
        mock_execute.return_value = {
            "reply": "<p>Summary</p>",
            "format": "html",
            "history_text": "Provided customer summary.",
            "tools_used": [],
        }

        llm_chat.chat("Tell me about Priya Nair")

        mock_execute.assert_called_once()
        mock_gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
