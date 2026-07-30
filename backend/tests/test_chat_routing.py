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
        self.assertIn("Approved joins:", instruction)
        self.assertIn("computed:", instruction)

    def test_classifier_hint_omits_non_mcp_suggested_tool(self):
        classification = classify_intent("How many missed payments are there?")
        self.assertEqual(classification.tool, "get_missed_payments")
        hint = llm_chat._classification_planning_hint(classification)
        self.assertIn("intent=", hint)
        self.assertNotIn("suggested_tool=", hint)
        self.assertNotIn("get_missed_payments", hint)
        self.assertIn("Ignore any suggested_tool", llm_chat.SYSTEM_PROMPT)

    def test_gemini_registers_only_mcp_tools(self):
        self.assertEqual(llm_chat._gemini_function_declarations(), [])
        mcp_names = [item["name"] for item in llm_chat._mcp_function_declarations()]
        self.assertEqual(
            mcp_names,
            ["get_approved_schema", "validate_safe_sql", "execute_safe_sql"],
        )

        classification = classify_intent("Show overdue customers")
        config = llm_chat._gemini_generate_config(classification)
        registered = []
        for declaration in config.tools[0].function_declarations:
            name = getattr(declaration, "name", None)
            if name is None and isinstance(declaration, dict):
                name = declaration.get("name")
            registered.append(name)
        self.assertEqual(
            registered,
            ["get_approved_schema", "validate_safe_sql", "execute_safe_sql"],
        )
        self.assertNotIn("get_overdue_customers", registered)
        self.assertNotIn("get_customer_loans", registered)

    def test_all_natural_language_requests_route_to_gemini(self):
        with patch("llm_chat._chat_with_gemini") as mock_gemini:
            mock_gemini.return_value = {
                "reply": "<p>ok</p>",
                "format": "html",
                "history_text": "ok",
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
            "history_text": "ok",
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
    def test_customer_lookup_uses_execute_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [
                {
                    "customer_id": 5,
                    "full_name": "Priya Nair",
                    "loan_type": "Personal Loan",
                    "current_balance": 9000.0,
                    "ltv_percent": 75.0,
                }
            ],
            "row_count": 1,
        }

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {
                            "sql": (
                                "SELECT c.customer_id, c.full_name, l.loan_type, "
                                "l.current_balance, "
                                "l.current_balance / NULLIF(l.collateral_value, 0) * 100 "
                                "AS ltv_percent "
                                "FROM customers c "
                                "JOIN loans l ON c.customer_id = l.customer_id "
                                "WHERE c.full_name = 'Priya Nair'"
                            )
                        },
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
        self.assertIn("execute_safe_sql", tool_names)
        self.assertNotIn("get_customer_loans", tool_names)
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
    def test_overdue_query_uses_execute_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [{"full_name": "Asha Patel", "remaining_due": 850.0}],
            "row_count": 1,
        }

        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {
                            "sql": (
                                "SELECT c.full_name, p.amount_due - p.amount_paid "
                                "AS remaining_due "
                                "FROM customers c "
                                "JOIN loans l ON c.customer_id = l.customer_id "
                                "JOIN payments p ON l.loan_id = p.loan_id "
                                "WHERE p.due_date < CURDATE() "
                                "AND p.amount_paid < p.amount_due"
                            )
                        },
                    )
                ]
            ),
            _make_gemini_response(
                text="There are overdue accounts requiring follow-up, including Asha Patel."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Show overdue customers")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("execute_safe_sql", tool_names)
        self.assertNotIn("get_overdue_customers", tool_names)
        self.assertIn("Asha Patel", result["reply"])

    def test_system_prompt_steers_database_questions_to_mcp_sql(self):
        self.assertIn("execute_safe_sql", llm_chat.SYSTEM_PROMPT)
        self.assertIn("get_approved_schema", llm_chat.SYSTEM_PROMPT)
        self.assertIn("validate_safe_sql", llm_chat.SYSTEM_PROMPT)
        self.assertIn("Do not use predefined banking lookup tools", llm_chat.SYSTEM_PROMPT)
        self.assertIn("how many", llm_chat.SYSTEM_PROMPT)
        self.assertIn("COUNT", llm_chat.SYSTEM_PROMPT)
        self.assertIn("SUM", llm_chat.SYSTEM_PROMPT)
        self.assertIn("AVG", llm_chat.SYSTEM_PROMPT)
        self.assertIn("MAX", llm_chat.SYSTEM_PROMPT)
        self.assertIn("MIN", llm_chat.SYSTEM_PROMPT)
        self.assertIn("GROUP BY", llm_chat.SYSTEM_PROMPT)
        self.assertIn("ORDER BY", llm_chat.SYSTEM_PROMPT)
        self.assertNotIn("get_overdue_customers", llm_chat.SYSTEM_PROMPT)

        mcp_declarations = {
            item["name"]: item["description"]
            for item in llm_chat._mcp_function_declarations()
        }
        self.assertIn("schema", mcp_declarations["get_approved_schema"].lower())
        execute_desc = mcp_declarations["execute_safe_sql"]
        self.assertIn("COUNT", execute_desc)
        self.assertIn("SUM", execute_desc)
        self.assertIn("AVG", execute_desc)
        self.assertIn("MAX", execute_desc)
        self.assertIn("MIN", execute_desc)
        self.assertIn("GROUP BY", execute_desc)
        self.assertIn("ORDER BY", execute_desc)
        self.assertIn("how many", execute_desc.lower())

    @patch("llm_chat._execute_tool_call")
    def test_how_many_missed_payments_uses_execute_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [{"missed_payment_count": 12}],
            "row_count": 1,
        }
        count_sql = (
            "SELECT COUNT(*) AS missed_payment_count "
            "FROM payments "
            "WHERE due_date < CURDATE() AND amount_paid < amount_due"
        )
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call("execute_safe_sql", {"sql": count_sql})
                ]
            ),
            _make_gemini_response(text="There are 12 missed payments."),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("How many missed payments are there?")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("execute_safe_sql", tool_names)
        self.assertNotIn("get_missed_payments", tool_names)
        self.assertIn("12", result["reply"])
        self.assertTrue(result.get("query_details", {}).get("queries"))

    @patch("llm_chat._execute_tool_call")
    def test_iphone_collateral_question_uses_execute_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [{"full_name": "Asha Patel", "item_type": "iPhone"}],
            "row_count": 1,
        }
        collateral_sql = (
            "SELECT DISTINCT c.full_name, ci.item_type "
            "FROM customers c "
            "JOIN loans l ON c.customer_id = l.customer_id "
            "JOIN collateral_items ci ON l.loan_id = ci.loan_id "
            "WHERE ci.item_type LIKE '%iPhone%'"
        )
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call("execute_safe_sql", {"sql": collateral_sql})
                ]
            ),
            _make_gemini_response(text="Asha Patel has iPhone collateral."),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Who has iPhone as collateral?")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("execute_safe_sql", tool_names)
        self.assertIn("Asha Patel", result["reply"])

    @patch("llm_chat._execute_tool_call")
    def test_which_one_owes_the_most_uses_execute_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [{"full_name": "Asha Patel", "total_owed": 2400.0}],
            "row_count": 1,
        }
        ranking_sql = (
            "SELECT c.full_name, SUM(p.amount_due - p.amount_paid) AS total_owed "
            "FROM customers c "
            "JOIN loans l ON c.customer_id = l.customer_id "
            "JOIN payments p ON l.loan_id = p.loan_id "
            "GROUP BY c.customer_id, c.full_name "
            "ORDER BY total_owed DESC "
            "LIMIT 1"
        )
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call("execute_safe_sql", {"sql": ranking_sql})
                ]
            ),
            _make_gemini_response(
                text="Asha Patel owes the most, with $2,400.00 overdue."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat(
                "Which one owes the most?",
                history=[
                    {"role": "user", "content": "Show overdue customers"},
                    {
                        "role": "assistant",
                        "content": "There are overdue accounts requiring follow-up.",
                    },
                ],
            )

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("execute_safe_sql", tool_names)
        self.assertNotIn("get_overdue_customers", tool_names)
        self.assertIn("Asha Patel", result["reply"])

    @patch("llm_chat._execute_tool_call")
    def test_highest_total_overdue_amount_uses_execute_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [{"full_name": "Priya Nair", "total_owed": 3100.0}],
            "row_count": 1,
        }
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {
                            "sql": (
                                "SELECT c.full_name, "
                                "SUM(p.amount_due - p.amount_paid) AS total_owed "
                                "FROM customers c "
                                "JOIN loans l ON c.customer_id = l.customer_id "
                                "JOIN payments p ON l.loan_id = p.loan_id "
                                "GROUP BY c.customer_id, c.full_name "
                                "ORDER BY total_owed DESC LIMIT 1"
                            )
                        },
                    )
                ]
            ),
            _make_gemini_response(
                text="Priya Nair has the highest total overdue amount at $3,100.00."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Who has the highest total overdue amount?")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("execute_safe_sql", tool_names)
        self.assertNotIn("get_overdue_customers", tool_names)
        self.assertNotIn("get_total_overdue_amount", tool_names)

    @patch("llm_chat._execute_tool_call")
    def test_rank_customers_by_total_overdue_uses_execute_safe_sql(
        self,
        mock_execute_tool,
    ):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [
                {"full_name": "Asha Patel", "total_owed": 2400.0},
                {"full_name": "Priya Nair", "total_owed": 1800.0},
            ],
            "row_count": 2,
        }
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {
                            "sql": (
                                "SELECT c.full_name, "
                                "SUM(p.amount_due - p.amount_paid) AS total_owed "
                                "FROM customers c "
                                "JOIN loans l ON c.customer_id = l.customer_id "
                                "JOIN payments p ON l.loan_id = p.loan_id "
                                "GROUP BY c.customer_id, c.full_name "
                                "ORDER BY total_owed DESC LIMIT 10"
                            )
                        },
                    )
                ]
            ),
            _make_gemini_response(
                text="Ranked by total overdue: Asha Patel, then Priya Nair."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Rank customers by total overdue balance")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("execute_safe_sql", tool_names)
        self.assertNotIn("get_overdue_customers", tool_names)

    @patch("llm_chat._execute_tool_call")
    def test_aggregate_total_overdue_uses_execute_safe_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [{"total_overdue": 5200.0}],
            "row_count": 1,
        }
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {
                            "sql": (
                                "SELECT SUM(amount_due - amount_paid) AS total_overdue "
                                "FROM payments "
                                "WHERE due_date < CURDATE() "
                                "AND amount_paid < amount_due"
                            )
                        },
                    )
                ]
            ),
            _make_gemini_response(
                text="$5,200.00 is overdue across the portfolio."
            ),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("How much is overdue in total?")

        tool_names = [entry["tool"] for entry in result.get("tools_used", [])]
        self.assertIn("execute_safe_sql", tool_names)
        self.assertNotIn("get_total_overdue_amount", tool_names)
        self.assertIn("$5,200.00", result["reply"])

    @patch("llm_chat._execute_tool_call")
    def test_follow_up_question_keeps_history_and_uses_sql(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": True,
            "rows": [{"full_name": "Asha Patel", "total_owed": 2400.0}],
            "row_count": 1,
        }
        history = [
            {"role": "user", "content": "Show overdue customers"},
            {
                "role": "assistant",
                "content": "Asha Patel and Priya Nair have overdue payments.",
            },
        ]
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {
                            "sql": (
                                "SELECT c.full_name, "
                                "SUM(p.amount_due - p.amount_paid) AS total_owed "
                                "FROM customers c "
                                "JOIN loans l ON c.customer_id = l.customer_id "
                                "JOIN payments p ON l.loan_id = p.loan_id "
                                "GROUP BY c.customer_id, c.full_name "
                                "ORDER BY total_owed DESC LIMIT 1"
                            )
                        },
                    )
                ]
            ),
            _make_gemini_response(text="Asha Patel owes the most."),
        ]

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = responses
        with patch("llm_chat._get_gemini_client", return_value=mock_client):
            result = llm_chat.chat("Which one owes the most?", history=history)

        first_call = mock_client.models.generate_content.call_args_list[0]
        first_call_contents = first_call.kwargs.get("contents") or first_call.args[0]
        serialized = " ".join(
            part.text
            for content in first_call_contents
            for part in content.parts
            if getattr(part, "text", None)
        )
        self.assertIn("Show overdue customers", serialized)
        self.assertIn("Asha Patel and Priya Nair have overdue payments.", serialized)
        self.assertIn("execute_safe_sql", [entry["tool"] for entry in result["tools_used"]])

    @patch("llm_chat._execute_tool_call")
    def test_rejected_unsafe_sql_returns_friendly_error(self, mock_execute_tool):
        mock_execute_tool.return_value = {
            "success": False,
            "sql": None,
            "rows": [],
            "row_count": 0,
            "validation": {
                "valid": False,
                "reason": "Forbidden SQL keyword: DELETE.",
            },
        }
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {"sql": "DELETE FROM customers"},
                    )
                ]
            ),
            _make_gemini_response(text=""),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Delete all customers")

        self.assertIn("couldn", result["reply"].lower())
        self.assertIn("database request", result["reply"].lower())
        self.assertNotIn("get_overdue_customers", str(result.get("tools_used")))

    def test_predefined_tool_calls_are_rejected(self):
        error = llm_chat._validate_tool_call("get_overdue_customers")
        self.assertIsNotNone(error)
        result = llm_chat._execute_tool_call("get_overdue_customers", {})
        self.assertFalse(result.get("success"))
        self.assertIn("not available", result.get("error", "").lower())

    def test_general_knowledge_question_can_answer_without_tools(self):
        reply_text = (
            "LTV means loan-to-value ratio: the loan balance divided by "
            "collateral value, expressed as a percentage."
        )
        responses = [
            _make_gemini_response(text=reply_text),
        ]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("What does LTV mean?")

        self.assertEqual(result.get("tools_used"), [])
        self.assertIn("loan-to-value", result["reply"].lower())
        self.assertEqual(result.get("history_text"), reply_text)
        self.assertIn("<", result["reply"])
        self.assertNotEqual(result["reply"], result["history_text"])

    def test_hello_does_not_force_sql_tools(self):
        reply_text = "Hello! How can I help with your pawnshop portfolio today?"
        responses = [_make_gemini_response(text=reply_text)]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("hello")

        self.assertEqual(result.get("tools_used"), [])
        self.assertEqual(result.get("history_text"), reply_text)
        self.assertFalse(result.get("query_details", {}).get("queries"))
        self.assertIn("hello", llm_chat.SYSTEM_PROMPT.lower())

    def test_gemini_final_response_stores_plain_text_in_history_text(self):
        reply_text = "Priya Nair has one active personal loan."
        responses = [_make_gemini_response(text=reply_text)]

        with _patch_gemini_responses(responses):
            result = llm_chat.chat("Tell me about Priya Nair")

        self.assertEqual(result["history_text"], reply_text)
        self.assertEqual(result.get("format"), "html")
        self.assertIn("Priya Nair", result["reply"])
        self.assertIn("<", result["reply"])

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
                "execute_safe_sql",
                {"sql": "SELECT full_name FROM customers"},
                {
                    "success": True,
                    "rows": [{"full_name": "Asha Patel"}],
                    "row_count": 1,
                },
            )
        ]
        response = _make_gemini_response(text="")

        result = llm_chat._finalize_gemini_turn(
            response,
            classification,
            [{"tool": "execute_safe_sql", "args": {"sql": "SELECT full_name FROM customers"}}],
            executions,
        )

        self.assertIn("could not compose a final answer", result["reply"].lower())

    @patch("llm_chat._execute_classification")
    def test_empty_gemini_turn_does_not_fall_back_to_predefined_tools(
        self,
        mock_execute,
    ):
        classification = classify_intent("Show me all overdue customers.")
        self.assertTrue(llm_chat._can_execute_operationally(classification))

        with _patch_gemini_responses([_make_gemini_response(text=None)]):
            result = llm_chat.chat("Show me all overdue customers.")

        mock_execute.assert_not_called()
        self.assertIn("portfolio analytics", result["reply"].lower())

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
            "success": True,
            "rows": [
                {"full_name": "Asha Patel", "remaining_due": 850.0},
            ],
            "row_count": 1,
        }
        responses = [
            _make_gemini_response(
                function_calls=[
                    _make_function_call(
                        "execute_safe_sql",
                        {"sql": "SELECT full_name FROM customers LIMIT 10"},
                    )
                ]
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
            "rows": [{"item_type": "Jewelry"}],
            "row_count": 1,
        }

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
        self.assertEqual(
            first.get("tools_used"),
            [{"tool": "execute_safe_sql", "args": {"sql": "SELECT item_type FROM collateral_items"}}],
        )
        self.assertEqual(second.get("tools_used"), [])


if __name__ == "__main__":
    unittest.main()
