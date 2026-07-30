"""FastMCP server for approved schema resources and safe SQL validation."""

from __future__ import annotations

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

from database import run_traced_query
from query_trace import extract_rows
from schema_metadata import get_approved_schema
from sql_validation import validate_readonly_sql

from pawnshop_mcp.constants import SCHEMA_RESOURCE_URI, SERVER_NAME

mcp = FastMCP(SERVER_NAME)


@mcp.resource(SCHEMA_RESOURCE_URI, mime_type="application/json")
def approved_schema_resource() -> dict:
    """Return the approved read-only schema metadata for safe SQL generation."""
    return get_approved_schema()


@mcp.tool(name="get_approved_schema")
def get_approved_schema_tool() -> dict:
    """Return the approved read-only schema metadata for safe SQL generation."""
    return get_approved_schema()


@mcp.tool(name="validate_safe_sql")
def validate_safe_sql(sql: str) -> dict:
    """Validate a single read-only SELECT statement against the approved schema."""
    return validate_readonly_sql(sql)


@mcp.tool(name="execute_safe_sql")
def execute_safe_sql(sql: str) -> dict:
    """Validate and execute a single read-only SELECT statement against the approved schema."""
    validation = validate_readonly_sql(sql)
    if not validation["valid"]:
        return {
            "success": False,
            "sql": None,
            "rows": [],
            "row_count": 0,
            "validation": validation,
        }

    normalized_sql = validation["normalized_sql"]
    tables_used = {table: [] for table in validation.get("tables_used", [])}
    try:
        trace_result = run_traced_query(normalized_sql, tables_used=tables_used)
        rows = extract_rows(trace_result)
        return {
            "success": True,
            "sql": normalized_sql,
            "rows": rows,
            "row_count": len(rows),
            "validation": validation,
            "trace": trace_result,
        }
    except Exception as exc:
        return {
            "success": False,
            "sql": normalized_sql,
            "rows": [],
            "row_count": 0,
            "validation": validation,
            "error": str(exc),
        }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
