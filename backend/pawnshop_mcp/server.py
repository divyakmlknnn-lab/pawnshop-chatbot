"""FastMCP server for approved schema resources and safe SQL validation."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Provenance for trusted tenant identity:
# Record whether the MCP client placed TELLERIQ_TRUSTED_STORE_ID in the
# process environment at launch, THEN load .env for DB/Gemini vars, THEN
# drop any trusted-store value that appeared only via load_dotenv().
# A .env-only value must never become trusted store identity.
_TRUSTED_STORE_ENV_KEY = "TELLERIQ_TRUSTED_STORE_ID"
_TRUSTED_STORE_PRESENT_AT_LAUNCH = _TRUSTED_STORE_ENV_KEY in os.environ
load_dotenv()

from database import run_traced_query
from query_trace import extract_rows
from schema_metadata import get_approved_schema
from sql_validation import validate_readonly_sql
from tenant_sql import (
    apply_tenant_scope,
    clear_unlaunched_trusted_store_id,
    read_trusted_store_id_from_env,
    tenancy_enforcement_enabled,
)

clear_unlaunched_trusted_store_id(
    present_at_process_launch=_TRUSTED_STORE_PRESENT_AT_LAUNCH
)

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
    """Validate and execute a single read-only SELECT statement against the approved schema.

    When TENANCY_ENFORCEMENT=1, requires TELLERIQ_TRUSTED_STORE_ID and injects
    deterministic tenant predicates before execution. Fail closed — never executes
    the original/global SQL as a fallback.
    """
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
    tenant_scope = None

    if tenancy_enforcement_enabled():
        trusted_store_id = read_trusted_store_id_from_env()
        if trusted_store_id is None:
            return {
                "success": False,
                "sql": None,
                "rows": [],
                "row_count": 0,
                "validation": validation,
                "error": (
                    "Tenant enforcement requires a valid trusted store_id "
                    "(TELLERIQ_TRUSTED_STORE_ID)."
                ),
                "tenant_scope": {
                    "applied": False,
                    "store_id": None,
                    "original_sql": sql,
                    "scoped_sql": None,
                    "reason": "Missing or invalid trusted store_id.",
                },
            }

        scope_result = apply_tenant_scope(
            normalized_sql,
            trusted_store_id,
            prevalidated=validation,
        )
        tenant_scope = scope_result.to_dict()
        if not scope_result.applied or not scope_result.sql:
            return {
                "success": False,
                "sql": None,
                "rows": [],
                "row_count": 0,
                "validation": scope_result.validation or validation,
                "error": scope_result.reason
                or "Tenant scoping failed; refusing to execute unscoped SQL.",
                "tenant_scope": tenant_scope,
            }
        normalized_sql = scope_result.sql
        validation = scope_result.validation or validation

    tables_used = {table: [] for table in validation.get("tables_used", [])}
    try:
        trace_result = run_traced_query(normalized_sql, tables_used=tables_used)
        rows = extract_rows(trace_result)
        payload = {
            "success": True,
            "sql": normalized_sql,
            "rows": rows,
            "row_count": len(rows),
            "validation": validation,
            "trace": trace_result,
        }
        if tenant_scope is not None:
            payload["tenant_scope"] = tenant_scope
        return payload
    except Exception as exc:
        payload = {
            "success": False,
            "sql": normalized_sql,
            "rows": [],
            "row_count": 0,
            "validation": validation,
            "error": str(exc),
        }
        if tenant_scope is not None:
            payload["tenant_scope"] = tenant_scope
        return payload


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
