import unittest
from unittest.mock import patch

from intent import classify_intent
from query_details import build_query_details
from query_trace import (
    build_final_query_entry,
    extract_rows,
    is_traced,
    make_trace,
)

import llm_chat


MCP_RESULT = {
    "success": True,
    "sql": "SELECT customer_id, full_name FROM customers LIMIT 5",
    "rows": [
        {"customer_id": 1, "full_name": "Asha Patel"},
        {"customer_id": 2, "full_name": "Rohan Mehta"},
    ],
    "row_count": 2,
    "validation": {
        "valid": True,
        "normalized_sql": "SELECT customer_id, full_name FROM customers LIMIT 5",
        "reason": None,
        "tables_used": ["customers"],
        "columns_used": ["customer_id", "full_name"],
    },
    "trace": {
        "tables_used": {"customers": []},
        "sql": "SELECT customer_id, full_name FROM customers LIMIT 5",
        "rows": [
            {"customer_id": 1, "full_name": "Asha Patel"},
            {"customer_id": 2, "full_name": "Rohan Mehta"},
        ],
    },
}


class McpTraceIntegrationTests(unittest.TestCase):
    def test_extract_rows_returns_mcp_rows(self):
        rows = extract_rows(MCP_RESULT)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["full_name"], "Asha Patel")

    def test_extract_rows_returns_empty_for_failed_mcp_result(self):
        failed = {
            "success": False,
            "sql": None,
            "rows": [],
            "row_count": 0,
            "validation": {"valid": False, "reason": "Forbidden SQL keyword: DELETE."},
        }
        self.assertEqual(extract_rows(failed), [])

    def test_build_final_query_entry_includes_mcp_sql_tables_rows_and_count(self):
        entry = build_final_query_entry(
            "execute_safe_sql",
            {"sql": MCP_RESULT["sql"]},
            MCP_RESULT,
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["tool"], "execute_safe_sql")
        self.assertEqual(
            entry["sql"],
            "SELECT customer_id, full_name FROM customers LIMIT 5",
        )
        self.assertEqual(entry["tables_used"], {"customers": ["Used"]})
        self.assertEqual(len(entry["rows"]), 2)
        self.assertEqual(entry["row_count"], 2)

    def test_join_query_tables_used_includes_customers_loans_payments(self):
        join_sql = (
            "SELECT c.full_name, l.loan_id, p.amount_due "
            "FROM customers c "
            "JOIN loans l ON l.customer_id = c.customer_id "
            "JOIN payments p ON p.loan_id = l.loan_id "
            "LIMIT 10"
        )
        result = {
            "success": True,
            "sql": join_sql,
            "rows": [{"full_name": "Asha Patel", "loan_id": 1, "amount_due": 100.0}],
            "row_count": 1,
            "validation": {
                "valid": True,
                "normalized_sql": join_sql,
                "reason": None,
                "tables_used": ["customers", "loans", "payments"],
                "columns_used": ["full_name", "loan_id", "amount_due"],
            },
            "trace": {
                "tables_used": {"customers": [], "loans": [], "payments": []},
                "sql": join_sql,
                "rows": [{"full_name": "Asha Patel", "loan_id": 1, "amount_due": 100.0}],
            },
        }

        entry = build_final_query_entry(
            "execute_safe_sql",
            {"sql": join_sql},
            result,
        )

        self.assertIsNotNone(entry)
        self.assertEqual(
            set(entry["tables_used"].keys()),
            {"customers", "loans", "payments"},
        )
        self.assertEqual(
            entry["tables_used"],
            {
                "customers": ["Used"],
                "loans": ["Used"],
                "payments": ["Used"],
            },
        )

    def test_build_query_details_includes_mcp_execution(self):
        classification = classify_intent("Show customers with the highest balances")
        executions = [("execute_safe_sql", {"sql": MCP_RESULT["sql"]}, MCP_RESULT)]

        details = build_query_details(classification, executions)

        self.assertEqual(len(details["queries"]), 1)
        query = details["queries"][0]
        self.assertEqual(query["tool"], "execute_safe_sql")
        self.assertEqual(query["row_count"], 2)
        self.assertIn("SELECT customer_id, full_name FROM customers", query["sql"])

    def test_predefined_traced_result_behavior_unchanged(self):
        traced = make_trace(
            "SELECT customer_id FROM customers LIMIT 100",
            {"customers": ["customer_id"]},
            [{"customer_id": 1}],
        )

        self.assertTrue(is_traced(traced))
        self.assertEqual(extract_rows(traced), [{"customer_id": 1}])

        entry = build_final_query_entry(
            "get_customer_count",
            {},
            traced,
        )
        self.assertEqual(entry["row_count"], 1)
        self.assertEqual(entry["sql"], "SELECT customer_id FROM customers LIMIT 100")


class McpChatIntegrationTests(unittest.TestCase):
    def test_tool_result_count_for_successful_mcp_result(self):
        self.assertEqual(llm_chat._tool_result_count(MCP_RESULT), 2)

    def test_tool_result_count_for_failed_mcp_result(self):
        self.assertEqual(
            llm_chat._tool_result_count(
                {"success": False, "rows": [{"customer_id": 1}]}
            ),
            0,
        )

    @patch("llm_chat.call_mcp_tool", side_effect=RuntimeError("stdio disconnected"))
    def test_call_mcp_tool_safe_returns_error_result(self, _mock_call):
        result = llm_chat._call_mcp_tool_safe(
            "execute_safe_sql",
            {"sql": "SELECT customer_id FROM customers"},
        )

        self.assertEqual(
            result,
            {
                "success": False,
                "error": "MCP tool execution failed.",
            },
        )

    @patch("llm_chat.call_mcp_tool", side_effect=RuntimeError("stdio disconnected"))
    def test_call_mcp_tool_safe_can_be_returned_to_gemini(self, _mock_call):
        result = llm_chat._call_mcp_tool_safe(
            "execute_safe_sql",
            {"sql": "SELECT customer_id FROM customers"},
        )
        payload = llm_chat._function_response_payload(result)

        self.assertEqual(payload["success"], False)
        self.assertEqual(payload["error"], "MCP tool execution failed.")


if __name__ == "__main__":
    unittest.main()
