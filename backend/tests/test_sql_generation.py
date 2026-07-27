import inspect
import os
import unittest
from unittest.mock import MagicMock, patch

import sql_generation
from sql_generation import SqlGenerationError, generate_sql_with_claude


def _make_text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


class SqlGenerationTests(unittest.TestCase):
    def setUp(self):
        sql_generation._anthropic_client = None

    def tearDown(self):
        sql_generation._anthropic_client = None

    def test_returns_plain_sql_text(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response(
            "SELECT customer_id, full_name FROM customers LIMIT 10"
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            with patch(
                "sql_generation._get_anthropic_client",
                return_value=mock_client,
            ):
                sql = generate_sql_with_claude("List customers")

        self.assertEqual(
            sql,
            "SELECT customer_id, full_name FROM customers LIMIT 10",
        )

    def test_strips_sql_code_fence(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response(
            "```sql\nSELECT loan_id FROM loans LIMIT 5\n```"
        )
        with patch(
            "sql_generation._get_anthropic_client",
            return_value=mock_client,
        ):
            sql = generate_sql_with_claude("Show loans")

        self.assertEqual(sql, "SELECT loan_id FROM loans LIMIT 5")

    def test_rejects_empty_user_question(self):
        with self.assertRaises(SqlGenerationError) as ctx:
            generate_sql_with_claude("   ")
        self.assertIn("non-empty", str(ctx.exception).lower())

    def test_rejects_missing_anthropic_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with self.assertRaises(SqlGenerationError) as ctx:
                generate_sql_with_claude("How many customers?")
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_rejects_empty_claude_response(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response("  \n  ")
        with patch(
            "sql_generation._get_anthropic_client",
            return_value=mock_client,
        ):
            with self.assertRaises(SqlGenerationError) as ctx:
                generate_sql_with_claude("How many loans?")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_wraps_anthropic_api_failure(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("upstream timeout")
        with patch(
            "sql_generation._get_anthropic_client",
            return_value=mock_client,
        ):
            with self.assertRaises(SqlGenerationError) as ctx:
                generate_sql_with_claude("Show overdue loans")
        message = str(ctx.exception)
        self.assertIn("Claude SQL generation failed", message)
        self.assertNotIn("upstream timeout", message)

    def test_prompt_includes_approved_schema(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response(
            "SELECT customer_id FROM customers LIMIT 1"
        )
        with patch(
            "sql_generation._get_anthropic_client",
            return_value=mock_client,
        ):
            generate_sql_with_claude("Count customers")

        prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("customers", prompt)
        self.assertIn("customer_id", prompt)
        self.assertIn("loans", prompt)
        self.assertIn("collateral_items", prompt)
        self.assertIn("Approved read-only schema", prompt)

    def test_prompt_requires_sql_only_readonly_output(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response(
            "SELECT account_id FROM accounts LIMIT 1"
        )
        with patch(
            "sql_generation._get_anthropic_client",
            return_value=mock_client,
        ):
            generate_sql_with_claude("List accounts")

        prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Return SQL only", prompt)
        self.assertIn("SELECT", prompt)
        self.assertIn("INSERT", prompt)
        self.assertIn("UPDATE", prompt)
        self.assertIn("DELETE", prompt)
        self.assertIn("Do not invent", prompt)

    def test_module_does_not_execute_sql_or_call_mcp(self):
        source = inspect.getsource(sql_generation)
        self.assertNotIn("run_traced_query", source)
        self.assertNotIn("call_mcp_tool", source)
        self.assertNotIn("validate_readonly_sql", source)
        self.assertNotIn("execute_safe_sql", source)
        self.assertNotIn("cursor.execute", source)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response(
            "SELECT full_name FROM customers LIMIT 3"
        )
        with patch("sql_generation.get_approved_schema") as mock_schema:
            mock_schema.return_value = {
                "tables": {
                    "customers": {
                        "fields": ["customer_id", "full_name"],
                        "computed_fields": [],
                    }
                },
                "relationships": [],
                "restricted_contact_fields": [],
            }
            with patch(
                "sql_generation._get_anthropic_client",
                return_value=mock_client,
            ):
                with patch("database.run_traced_query") as mock_run:
                    with patch("pawnshop_mcp.client.call_mcp_tool") as mock_mcp:
                        sql = generate_sql_with_claude("Show names")
                        mock_run.assert_not_called()
                        mock_mcp.assert_not_called()
        self.assertEqual(sql, "SELECT full_name FROM customers LIMIT 3")


if __name__ == "__main__":
    unittest.main()
