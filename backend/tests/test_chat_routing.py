import unittest
from unittest.mock import MagicMock, patch

from intent import classify_intent

import llm_chat


def _make_function_call(name: str, args: dict | None = None):
    call = MagicMock()
    call.name = name
    call.args = args or {}
    return call


def _make_gemini_response(*, text: str | None = None, function_calls: list | None = None):
    response = MagicMock()
    response.text = text
    response.function_calls = function_calls or []
    if function_calls:
        candidate = MagicMock()
        candidate.content = MagicMock()
        response.candidates = [candidate]
    else:
        response.candidates = []
    return response


def _patch_gemini_responses(responses: list):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = responses
    return patch("llm_chat._get_gemini_client", return_value=mock_client)


class ChatRoutingTests(unittest.TestCase):
    def test_classifier_hint_is_untrusted_metadata_only(self):
        classification = classify_intent("What are the different collaterals")
        hint = llm_chat._classification_planning_hint(classification)
        self.assertIn("Untrusted classifier hint", hint)
        self.assertIn("intent=", hint)

        instruction = llm_chat._gemini_system_instruction(classification)
        self.assertIn(hint, instruction)
        self.assertIn("collateral_items", instruction)

    def test_all_natural_language_requests_route_to_gemini(self):
        with patch("llm_chat._chat_with_gemini") as mock_gemini:
            mock_gemini.return_value = {
                "reply": "<p>ok</p>",
                "format": "html",
                "history_text": "Answered with Gemini using conversation context.",
                "tools_used": [],
            }
            for message in (
                "What are the different collaterals",
                "Show overdue customers",
                "Tell me about Priya Nair",
            ):
                with self.subTest(message=message):
                    mock_gemini.reset_mock()
                    llm_chat.chat(message)
                    mock_gemini.assert_called_once()

    @patch("llm_chat._execute_classification")
    @patch("llm_chat._chat_with_gemini")
    def test_chat_never_executes_classifier_directly(
        self,
        mock_gemini,
        mock_execute,
    ):
        mock_gemini.return_value = {
            "reply": "<p>ok</p>",
            "format": "html",
            "history_text": "Answered with Gemini using conversation context.",
            "tools_used": [],
        }

        llm_chat.chat("What are the different collaterals")

        mock_execute.assert_not_called()
        mock_gemini.assert_called_once()

    @patch("llm_chat._execute_tool_call")
    def test_collateral_query_uses_gemini_and_not_forced_overdue_tool(
        self,
        mock_execute_tool,
    ):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [
                {"item_type": "Jewelry"},
                {"item_type": "Vehicle"},
                {"item_type": "Electronics"},
            ],
            "row_count": 3,
        }

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {"sql": "SELECT DISTINCT item_type FROM collateral_items"},
                    )
                ]
            ),
            _make_gemini_response(
                text="The different collateral types are Jewelry, Vehicle, and Electronics."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("What are the different collaterals")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertNotIn("get_overdue_customers", tool_names)
        self.assertIn("execute_safe_sql", tool_names)
        self.assertIn("Jewelry", result["reply"])
        self.assertNotIn("overdue accounts requiring follow-up", result["reply"])

    @patch("llm_chat._execute_tool_call")
    def test_ltv_query_uses_customer_loans_tool(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "rows": [
                {
                    "loan_type": "Personal Loan",
                    "ltv_percent": 75.0,
                    "current_balance": 9000.0,
                    "collateral_value": 12000.0,
                }
            ]
        }

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "get_customer_loans",
                        {"customer_name": "Priya Nair"},
                    )
                ]
            ),
            _make_gemini_response(
                text="Priya Nair's Personal Loan has an LTV of 75%."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Can you tell me the LTV of Priya Nair?")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("get_customer_loans", tool_names)
        self.assertIn("75", result["reply"])

    @patch("llm_chat._execute_tool_call")
    def test_loans_over_amount_recovers_from_invalid_column(self, mock_execute_tool):
        def execute_side_effect(tool_name, tool_args):
            if tool_name == "validate_safe_sql" and "amount" in tool_args.get("sql", ""):
                return {
                    "valid": False,
                    "reason": "Unknown column: amount",
                    "normalized_sql": None,
                    "tables_used": ["loans"],
                    "columns_used": [],
                }
            if tool_name == "execute_safe_sql":
                return {
                    "success": True,
                    "rows": [
                        {"loan_id": 1, "current_balance": 1500.0},
                        {"loan_id": 5, "current_balance": 9000.0},
                    ],
                    "row_count": 2,
                }
            return {"success": False, "error": "unexpected tool"}

        mock_execute_tool.side_effect = execute_side_effect

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "validate_safe_sql",
                        {"sql": "SELECT loan_id FROM loans WHERE amount > 1000"},
                    )
                ]
            ),
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {"sql": "SELECT loan_id, current_balance FROM loans WHERE current_balance > 1000"},
                    )
                ]
            ),
            _make_gemini_response(
                text="Two loans have balances over $1,000."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Show loans over $1000")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("validate_safe_sql", tool_names)
        self.assertIn("execute_safe_sql", tool_names)
        self.assertIn("$1,000", result["reply"])

    @patch("llm_chat._execute_tool_call")
    def test_overdue_query_uses_predefined_tool_via_gemini(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "rows": [{"full_name": "Asha Patel", "remaining_due": 850.0}]
        }

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call("get_overdue_customers", {})
                ]
            ),
            _make_gemini_response(
                text="There are overdue accounts requiring follow-up, including Asha Patel."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Show overdue customers")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("get_overdue_customers", tool_names)
        self.assertIn("Asha Patel", result["reply"])

    def test_general_knowledge_question_can_answer_without_tools(self):
        responses = [
            _make_gemini_response(
                text=(
                    "LTV means loan-to-value ratio: the loan balance divided by "
                    "collateral value, expressed as a percentage."
                )
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("What does LTV mean?")

        self.assertEqual(result.get("tools_used"), [])
        self.assertIn("loan-to-value", result["reply"].lower())

    def test_ambiguous_customer_request_returns_clarification(self):
        responses = [
            _make_gemini_response(
                text="Which customer did you mean? Please provide a full name or customer ID."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Tell me about Priya")

        self.assertIn("customer", result["reply"].lower())
        self.assertNotIn("portfolio analytics", result["reply"].lower())

    def test_finalize_gemini_turn_does_not_auto_format_tool_results(self):
        classification = classify_intent("Show overdue customers")
        executions = [
            (
                "get_overdue_customers",
                {},
                {"rows": [{"full_name": "Asha Patel"}]},
            )
        ]
        response = _make_gemini_response(text="")

        result = llm_chat._finalize_gemini_turn(
            response,
            classification,
            [{"tool": "get_overdue_customers", "args": {}}],
            executions,
        )

        self.assertIn("could not compose a final answer", result["reply"].lower())

    @patch("llm_chat._execute_tool_call")
    def test_execution_state_is_request_scoped(self, mock_execute_tool):
        mock_execute_tool.return_value = {"rows": [{"item_type": "Jewelry"}]}

        first_responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {"sql": "SELECT item_type FROM collateral_items"},
                    )
                ]
            ),
            _make_gemini_response(text="Collateral types include Jewelry."),
        ]
        second_responses = [
            _make_gemini_response(text="Two loans have balances over $1,000."),
        ]

        with _patch_gemini_responses(first_responses):
            first = llm_chat.chat("What are the different collaterals")

        with _patch_gemini_responses(second_responses):
            second = llm_chat.chat("Show loans over $1000")

        self.assertIn("Jewelry", first["reply"])
        self.assertEqual(first.get("tools_used"), [{"tool": "execute_safe_sql", "args": {"sql": "SELECT item_type FROM collateral_items"}}])
        self.assertEqual(second.get("tools_used"), [])


if __name__ == "__main__":
    unittest.main()
