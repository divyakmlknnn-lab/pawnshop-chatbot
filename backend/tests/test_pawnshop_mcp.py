import json
import unittest
from unittest.mock import patch

from pawnshop_mcp.constants import SCHEMA_RESOURCE_URI, SERVER_NAME
from pawnshop_mcp.server import mcp


class PawnshopMcpServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_name(self):
        self.assertEqual(mcp.name, SERVER_NAME)

    async def test_list_resources_includes_approved_schema(self):
        resources = await mcp.list_resources()

        self.assertEqual(len(resources), 1)
        self.assertEqual(str(resources[0].uri), SCHEMA_RESOURCE_URI)
        self.assertEqual(resources[0].mimeType, "application/json")

    async def test_approved_schema_resource_returns_expected_shape(self):
        contents = await mcp.read_resource(SCHEMA_RESOURCE_URI)

        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].mime_type, "application/json")

        schema = json.loads(contents[0].content)

        self.assertIn("tables", schema)
        self.assertIn("relationships", schema)
        self.assertIn("computed_fields", schema)
        self.assertIn("restricted_contact_fields", schema)

        self.assertEqual(
            sorted(schema["tables"].keys()),
            [
                "accounts",
                "collateral_items",
                "customers",
                "loans",
                "payments",
            ],
        )

    async def test_list_tools_exposes_validation_and_execution_tools(self):
        tools = await mcp.list_tools()
        tool_names = [tool.name for tool in tools]

        self.assertEqual(
            tool_names,
            ["validate_safe_sql", "execute_safe_sql"],
        )

        validate_tool = next(
            tool for tool in tools if tool.name == "validate_safe_sql"
        )

        self.assertNotIn(
            "allow_contact_fields",
            validate_tool.inputSchema.get("properties", {}),
        )

    async def test_validate_safe_sql_accepts_valid_select(self):
        result = await mcp.call_tool(
            "validate_safe_sql",
            {"sql": "SELECT customer_id FROM customers"},
        )

        payload = json.loads(result[0].text)

        self.assertTrue(payload["valid"])
        self.assertEqual(
            payload["normalized_sql"],
            "SELECT customer_id FROM customers LIMIT 100",
        )
        self.assertEqual(payload["tables_used"], ["customers"])
        self.assertEqual(payload["columns_used"], ["customer_id"])

    async def test_validate_safe_sql_rejects_delete(self):
        result = await mcp.call_tool(
            "validate_safe_sql",
            {"sql": "DELETE FROM customers"},
        )

        payload = json.loads(result[0].text)

        self.assertFalse(payload["valid"])
        self.assertIn("DELETE", payload["reason"])

    async def test_validate_safe_sql_rejects_contact_fields_by_default(self):
        result = await mcp.call_tool(
            "validate_safe_sql",
            {"sql": "SELECT phone, email FROM customers LIMIT 10"},
        )

        payload = json.loads(result[0].text)

        self.assertFalse(payload["valid"])
        self.assertIn("Restricted contact fields", payload["reason"])

    async def test_execute_safe_sql_rejects_invalid_query_without_execution(self):
        with patch("pawnshop_mcp.server.run_traced_query") as mock_run_query:
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "DELETE FROM customers"},
            )

        payload = json.loads(result[0].text)

        self.assertFalse(payload["success"])
        self.assertFalse(payload["validation"]["valid"])
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["row_count"], 0)

        mock_run_query.assert_not_called()

    async def test_execute_safe_sql_returns_rows_for_valid_query(self):
        trace_result = {
            "sql": "SELECT customer_id FROM customers LIMIT 100",
            "results": [{"customer_id": 1}, {"customer_id": 2}],
        }

        expected_rows = [
            {"customer_id": 1},
            {"customer_id": 2},
        ]

        with (
            patch(
                "pawnshop_mcp.server.run_traced_query",
                return_value=trace_result,
            ) as mock_run_query,
            patch(
                "pawnshop_mcp.server.extract_rows",
                return_value=expected_rows,
            ) as mock_extract_rows,
        ):
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )

        payload = json.loads(result[0].text)

        self.assertTrue(payload["success"])
        self.assertEqual(
            payload["sql"],
            "SELECT customer_id FROM customers LIMIT 100",
        )
        self.assertEqual(payload["rows"], expected_rows)
        self.assertEqual(payload["row_count"], 2)
        self.assertTrue(payload["validation"]["valid"])

        mock_run_query.assert_called_once_with(
            "SELECT customer_id FROM customers LIMIT 100",
            tables_used={"customers": []},
        )
        mock_extract_rows.assert_called_once_with(trace_result)

    async def test_execute_safe_sql_handles_database_error(self):
        with patch(
            "pawnshop_mcp.server.run_traced_query",
            side_effect=Exception("Database connection failed"),
        ):
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )

        payload = json.loads(result[0].text)

        self.assertFalse(payload["success"])
        self.assertEqual(
            payload["sql"],
            "SELECT customer_id FROM customers LIMIT 100",
        )
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["row_count"], 0)
        self.assertEqual(payload["error"], "Database connection failed")
        self.assertTrue(payload["validation"]["valid"])


if __name__ == "__main__":
    unittest.main()