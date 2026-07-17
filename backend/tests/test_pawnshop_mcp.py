import asyncio
import json
import unittest

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

    async def test_list_tools_exposes_validate_safe_sql_only(self):
        tools = await mcp.list_tools()
        self.assertEqual([tool.name for tool in tools], ["validate_safe_sql"])
        self.assertNotIn("allow_contact_fields", tools[0].inputSchema.get("properties", {}))

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


if __name__ == "__main__":
    unittest.main()
