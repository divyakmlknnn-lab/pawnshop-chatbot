"""Claude-based text-to-SQL generation for approved TellerIQ schema.

This module converts a natural-language database question into one read-only
MySQL SELECT string. It does not validate, execute, or route SQL through MCP.
"""

from __future__ import annotations

import logging
import os
import re

from anthropic import Anthropic

from schema_metadata import get_approved_schema

logger = logging.getLogger("telleriq.sql_generation")

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
MAX_OUTPUT_TOKENS = 1024

_SQL_FENCE_RE = re.compile(
    r"^```(?:sql)?\s*\n?(?P<body>.*?)\n?```\s*$",
    re.IGNORECASE | re.DOTALL,
)

_anthropic_client: Anthropic | None = None


class SqlGenerationError(RuntimeError):
    """Raised when Claude text-to-SQL generation fails."""


def _get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise SqlGenerationError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _anthropic_client = Anthropic(api_key=api_key)
    return _anthropic_client


def _format_approved_schema() -> str:
    """Return a compact approved-schema description for the text-to-SQL prompt."""
    schema = get_approved_schema()
    lines = ["Approved read-only schema (use exact table and column names):"]
    for table in sorted(schema.get("tables", {})):
        table_meta = schema["tables"][table]
        fields = table_meta.get("fields", [])
        lines.append(f"- {table}: {', '.join(fields)}")
        computed = table_meta.get("computed_fields") or []
        for field in computed:
            name = field.get("name")
            expression = field.get("expression")
            if name and expression:
                lines.append(f"  computed {name}: {expression}")
    relationships = schema.get("relationships") or []
    if relationships:
        lines.append("Approved relationships:")
        for rel in relationships:
            lines.append(
                f"- {rel.get('from_table')}.{rel.get('from_column')} -> "
                f"{rel.get('to_table')}.{rel.get('to_column')}"
            )
    restricted = schema.get("restricted_contact_fields") or []
    if restricted:
        lines.append(
            "Restricted contact fields (avoid unless explicitly required): "
            + ", ".join(restricted)
        )
    return "\n".join(lines)


def _build_text_to_sql_prompt(user_question: str, schema_text: str) -> str:
    return (
        "You convert natural-language questions into exactly one MySQL SELECT "
        "query for the TellerIQ pawnshop database.\n\n"
        "Rules:\n"
        "- Return SQL only. No explanation, no markdown, no comments outside SQL.\n"
        "- Generate exactly one read-only SELECT statement.\n"
        "- Read-only CTEs (WITH ... SELECT) are not supported by the downstream "
        "validator; start with SELECT.\n"
        "- Use only approved tables and columns from the schema below.\n"
        "- Do not invent tables, columns, or relationships.\n"
        "- Do not generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, "
        "or any other write or DDL operation.\n"
        "- Prefer explicit column lists; avoid SELECT *.\n"
        "- Use approved JOIN relationships when joining tables.\n\n"
        f"{schema_text}\n\n"
        f"Question:\n{user_question.strip()}\n"
    )


def _extract_message_text(response) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
    return "".join(parts)


def _strip_optional_sql_fence(text: str) -> str:
    stripped = text.strip()
    match = _SQL_FENCE_RE.match(stripped)
    if match:
        return match.group("body").strip()
    return stripped


def generate_sql_with_claude(user_question: str) -> str:
    """Generate one read-only MySQL SELECT for ``user_question`` via Claude.

    Returns the SQL string only. Does not validate or execute the query.
    """
    if not isinstance(user_question, str) or not user_question.strip():
        raise SqlGenerationError("user_question must be a non-empty string.")

    schema_text = _format_approved_schema()
    prompt = _build_text_to_sql_prompt(user_question, schema_text)
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)

    try:
        client = _get_anthropic_client()
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )
    except SqlGenerationError:
        raise
    except Exception as exc:
        logger.exception("Anthropic SQL generation failed")
        raise SqlGenerationError(
            "Claude SQL generation failed. Check ANTHROPIC_API_KEY and try again."
        ) from exc

    raw_text = _extract_message_text(response)
    sql = _strip_optional_sql_fence(raw_text)
    if not sql:
        raise SqlGenerationError("Claude returned an empty SQL response.")
    return sql
