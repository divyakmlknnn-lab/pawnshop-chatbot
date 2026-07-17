"""FastMCP server for approved schema resources and safe SQL validation."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from schema_metadata import get_approved_schema
from sql_validation import validate_readonly_sql

from pawnshop_mcp.constants import SCHEMA_RESOURCE_URI, SERVER_NAME

mcp = FastMCP(SERVER_NAME)


@mcp.resource(SCHEMA_RESOURCE_URI, mime_type="application/json")
def approved_schema_resource() -> dict:
    """Return the approved read-only schema metadata for safe SQL generation."""
    return get_approved_schema()


@mcp.tool(name="validate_safe_sql")
def validate_safe_sql(sql: str) -> dict:
    """Validate a single read-only SELECT statement against the approved schema."""
    return validate_readonly_sql(sql)


def main() -> None:
    mcp.run()
