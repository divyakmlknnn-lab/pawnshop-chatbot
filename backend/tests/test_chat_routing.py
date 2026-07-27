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
            "sql": "SELECT DISTINCT item_type FROM collateral_items LIMIT 100",
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
                        "generate_safe_sql",
                        {"user_question": "What are the different collaterals"},
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
        self.assertIn("generate_safe_sql", tool_names)
        self.assertNotIn("execute_safe_sql", tool_names)
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
    def test_loans_over_amount_uses_generate_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "sql": (
                "SELECT loan_id, current_balance FROM loans "
                "WHERE current_balance > 1000 LIMIT 100"
            ),
            "rows": [
                {"loan_id": 1, "current_balance": 1500.0},
                {"loan_id": 5, "current_balance": 9000.0},
            ],
            "row_count": 2,
        }

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "generate_safe_sql",
                        {"user_question": "Show loans over $1000"},
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
        self.assertIn("generate_safe_sql", tool_names)
        self.assertNotIn("validate_safe_sql", tool_names)
        self.assertNotIn("execute_safe_sql", tool_names)
        self.assertIn("$1,000", result["reply"])
        mock_execute_tool.assert_called_once_with(
            "generate_safe_sql",
            {"user_question": "Show loans over $1000"},
        )

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

    @patch("llm_chat._execute_classification")
    def test_empty_gemini_turn_falls_back_for_executable_overdue(
        self,
        mock_execute,
    ):
        classification = classify_intent("Show me all overdue customers.")
        self.assertTrue(llm_chat._can_execute_operationally(classification))
        mock_execute.return_value = {
            "reply": "<p>4 overdue customers</p>",
            "format": "html",
            "history_text": "Provided overdue customer list.",
            "tools_used": [{"tool": "get_overdue_customers", "args": {}}],
            "query_details": {"queries": [{"rows": [{"full_name": "Asha Patel"}] * 4}]},
        }

        with _patch_gemini_responses([_make_gemini_response(text=None)]):
            result = llm_chat.chat("Show me all overdue customers.")

        mock_execute.assert_called_once()
        self.assertEqual(
            mock_execute.call_args.args[0],
            "Show me all overdue customers.",
        )
        self.assertEqual(mock_execute.call_args.args[1].intent, "OVERDUE_CUSTOMERS")
        self.assertIn("4 overdue customers", result["reply"])
        self.assertEqual(
            result.get("tools_used"),
            [{"tool": "get_overdue_customers", "args": {}}],
        )

    @patch("llm_chat._execute_classification")
    def test_empty_gemini_turn_keeps_clarifying_for_unknown(
        self,
        mock_execute,
    ):
        responses = [_make_gemini_response(text=None)]

        with _patch_gemini_responses(responses):
            with patch("llm_chat.classify_intent") as mock_classify:
                unknown = classify_intent("asdf qwerty zxcv")
                unknown.intent = "UNKNOWN"
                unknown.action = None
                unknown.tool = None
                unknown.confidence = 0.0
                mock_classify.return_value = unknown
                result = llm_chat.chat("asdf qwerty zxcv")

        mock_execute.assert_not_called()
        self.assertIn("portfolio analytics", result["reply"].lower())

    @patch("llm_chat._execute_classification")
    def test_gemini_text_response_skips_operational_fallback(
        self,
        mock_execute,
    ):
        with _patch_gemini_responses(
            [_make_gemini_response(text="There are four overdue accounts.")]
        ):
            result = llm_chat.chat("Show me all overdue customers.")

        mock_execute.assert_not_called()
        self.assertIn("four overdue accounts", result["reply"].lower())

    @patch("llm_chat._execute_classification")
    @patch("llm_chat._execute_tool_call")
    def test_gemini_tool_executions_skip_operational_fallback(
        self,
        mock_execute_tool,
        mock_execute_classification,
    ):
        mock_execute_tool.return_value = {
            "rows": [
                {"full_name": "Asha Patel", "remaining_due": 850.0},
            ]
        }
        responses = [
            _make_gemini_response(
                function_calls=[_make_function_call("get_overdue_customers", {})]
            ),
            _make_gemini_response(text=""),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Show me all overdue customers.")

        mock_execute_classification.assert_not_called()
        mock_execute_tool.assert_called_once()
        self.assertIn("could not compose a final answer", result["reply"].lower())

    @patch("llm_chat._execute_tool_call")
    def test_execution_state_is_request_scoped(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "sql": "SELECT item_type FROM collateral_items LIMIT 100",
            "rows": [{"item_type": "Jewelry"}],
            "row_count": 1,
        }

        first_responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "generate_safe_sql",
                        {"user_question": "What are the different collaterals"},
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
        self.assertEqual(
            first.get("tools_used"),
            [
                {
                    "tool": "generate_safe_sql",
                    "args": {"user_question": "What are the different collaterals"},
                }
            ],
        )
        self.assertEqual(second.get("tools_used"), [])


class GenerateSafeSqlIntegrationTests(unittest.TestCase):
    def test_gemini_declarations_include_generate_safe_sql_not_raw_mcp(self):
        declarations = (
            llm_chat._gemini_function_declarations()
            + llm_chat._orchestration_function_declarations()
        )
        names = {item["name"] for item in declarations}
        self.assertIn("generate_safe_sql", names)
        self.assertNotIn("validate_safe_sql", names)
        self.assertNotIn("execute_safe_sql", names)

        generate_decl = next(
            item for item in declarations if item["name"] == "generate_safe_sql"
        )
        self.assertEqual(generate_decl["parameters"]["required"], ["user_question"])
        self.assertIn("user_question", generate_decl["parameters"]["properties"])

    def test_raw_mcp_tools_are_rejected_as_gemini_tool_calls(self):
        self.assertEqual(
            llm_chat._validate_tool_call("validate_safe_sql"),
            "Unknown tool: validate_safe_sql",
        )
        self.assertEqual(
            llm_chat._validate_tool_call("execute_safe_sql"),
            "Unknown tool: execute_safe_sql",
        )
        self.assertIsNone(llm_chat._validate_tool_call("generate_safe_sql"))
        self.assertIsNone(llm_chat._validate_tool_call("get_overdue_customers"))

    def test_prompt_requires_generate_safe_sql_not_authored_sql(self):
        self.assertIn("generate_safe_sql", llm_chat.SYSTEM_PROMPT)
        self.assertIn("Do not write, invent, or submit SQL yourself", llm_chat.SYSTEM_PROMPT)
        self.assertIn(
            "Never call validate_safe_sql or execute_safe_sql",
            llm_chat.SYSTEM_PROMPT,
        )

    @patch("llm_chat.call_mcp_tool")
    @patch("llm_chat.generate_sql_with_claude")
    def test_generate_safe_sql_validates_then_executes(
        self,
        mock_claude,
        mock_mcp,
    ):
        generated_sql = (
            "SELECT loan_id, current_balance FROM loans "
            "WHERE current_balance > 1000"
        )
        mock_claude.return_value = generated_sql

        def mcp_side_effect(tool_name, arguments=None):
            if tool_name == "validate_safe_sql":
                return {
                    "valid": True,
                    "normalized_sql": generated_sql + " LIMIT 100",
                    "reason": None,
                    "tables_used": ["loans"],
                    "columns_used": ["loan_id", "current_balance"],
                }
            if tool_name == "execute_safe_sql":
                return {
                    "success": True,
                    "sql": generated_sql + " LIMIT 100",
                    "rows": [
                        {"loan_id": 1, "current_balance": 1500.0},
                        {"loan_id": 5, "current_balance": 9000.0},
                    ],
                    "row_count": 2,
                    "validation": {"valid": True, "tables_used": ["loans"]},
                    "trace": {
                        "tables_used": {"loans": []},
                        "sql": generated_sql + " LIMIT 100",
                        "rows": [
                            {"loan_id": 1, "current_balance": 1500.0},
                            {"loan_id": 5, "current_balance": 9000.0},
                        ],
                    },
                }
            raise AssertionError(f"Unexpected MCP tool: {tool_name}")

        mock_mcp.side_effect = mcp_side_effect

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "generate_safe_sql",
                        {"user_question": "Show loans over $1000"},
                    )
                ]
            ),
            _make_gemini_response(text="Two loans have balances over $1,000."),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Show loans over $1000")

        mock_claude.assert_called_once_with("Show loans over $1000")
        self.assertEqual(
            [call.args[0] for call in mock_mcp.call_args_list],
            ["validate_safe_sql", "execute_safe_sql"],
        )
        self.assertEqual(
            mock_mcp.call_args_list[0].args[1],
            {"sql": generated_sql},
        )
        self.assertEqual(
            mock_mcp.call_args_list[1].args[1],
            {"sql": generated_sql},
        )
        self.assertIn("$1,000", result["reply"])
        queries = result.get("query_details", {}).get("queries", [])
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["tool"], "generate_safe_sql")
        self.assertIn("current_balance > 1000", queries[0]["sql"])
        self.assertEqual(queries[0]["row_count"], 2)

    @patch("llm_chat.call_mcp_tool")
    @patch("llm_chat.generate_sql_with_claude")
    def test_invalid_sql_skips_execute_safe_sql(self, mock_claude, mock_mcp):
        mock_claude.return_value = "SELECT amount FROM loans"
        mock_mcp.return_value = {
            "valid": False,
            "reason": "Unknown column: amount",
            "normalized_sql": None,
            "tables_used": ["loans"],
            "columns_used": [],
        }

        result = llm_chat._execute_generate_safe_sql(
            {"user_question": "Show loans by amount"}
        )

        mock_mcp.assert_called_once_with(
            "validate_safe_sql",
            {"sql": "SELECT amount FROM loans"},
        )
        self.assertFalse(result["success"])
        self.assertIn("Unknown column", result["error"])
        self.assertEqual(result["rows"], [])

    @patch("llm_chat.call_mcp_tool")
    @patch(
        "llm_chat.generate_sql_with_claude",
        side_effect=llm_chat.SqlGenerationError("Claude SQL generation failed."),
    )
    def test_claude_failure_returns_safe_tool_error(self, _mock_claude, mock_mcp):
        result = llm_chat._execute_generate_safe_sql(
            {"user_question": "Show high balance loans"}
        )

        mock_mcp.assert_not_called()
        self.assertEqual(
            result,
            {
                "success": False,
                "error": "Claude SQL generation failed.",
            },
        )

    def test_missing_user_question_returns_safe_error(self):
        result = llm_chat._execute_generate_safe_sql({})
        self.assertFalse(result["success"])
        self.assertIn("user_question", result["error"])

        empty = llm_chat._execute_generate_safe_sql({"user_question": "   "})
        self.assertFalse(empty["success"])
        self.assertIn("user_question", empty["error"])

    @patch("llm_chat.generate_sql_with_claude")
    @patch("llm_chat._execute_tool_call")
    def test_predefined_tools_skip_claude(
        self,
        mock_execute_tool,
        mock_claude,
    ):
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

        mock_claude.assert_not_called()
        mock_execute_tool.assert_called_once_with("get_overdue_customers", {})
        self.assertIn("Asha Patel", result["reply"])


if __name__ == "__main__":
    unittest.main()
