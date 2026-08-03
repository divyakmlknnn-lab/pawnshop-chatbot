"""Client helpers for calling the local Pawnshop MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tenant_sql import TRUSTED_STORE_ENV, parse_trusted_store_id


def _server_parameters(
    *,
    trusted_store_id: int | str | None = None,
) -> StdioServerParameters:
    """Return the command used to launch the local MCP server.

    Pass the parent process environment explicitly. The MCP stdio client
    sanitizes the subprocess env when ``env`` is omitted, which drops
    database credentials that Render injects as process environment
    variables (and that are not available via a deployed ``.env`` file).

    Trusted store identity is passed only via per-spawn
    ``TELLERIQ_TRUSTED_STORE_ID``. Ambient parent values are cleared unless
    this call explicitly provides a trusted store id. Gemini tool arguments
    never carry store identity.
    """
    env = os.environ.copy()
    # Never inherit an ambient trusted store id from the parent process.
    env.pop(TRUSTED_STORE_ENV, None)

    parsed = parse_trusted_store_id(trusted_store_id)
    if parsed is not None:
        env[TRUSTED_STORE_ENV] = str(parsed)

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "pawnshop_mcp.server"],
        env=env,
    )


async def _call_mcp_tool_async(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    trusted_store_id: int | str | None = None,
) -> dict[str, Any]:
    """Connect to the MCP server and call one tool."""
    server = _server_parameters(trusted_store_id=trusted_store_id)

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                tool_name,
                arguments=arguments or {},
            )

            if result.isError:
                return {
                    "success": False,
                    "error": "The MCP tool returned an error.",
                }

            structured = getattr(result, "structuredContent", None)
            if isinstance(structured, dict):
                return structured

            for item in result.content:
                text = getattr(item, "text", None)
                if not text:
                    continue

                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return {
                        "success": True,
                        "result": text,
                    }

                if isinstance(parsed, dict):
                    return parsed

                return {
                    "success": True,
                    "result": parsed,
                }

            return {
                "success": True,
                "result": None,
            }


def call_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    trusted_store_id: int | str | None = None,
) -> dict[str, Any]:
    """Synchronously call a tool exposed by the local MCP server."""
    return asyncio.run(
        _call_mcp_tool_async(
            tool_name=tool_name,
            arguments=arguments,
            trusted_store_id=trusted_store_id,
        )
    )
