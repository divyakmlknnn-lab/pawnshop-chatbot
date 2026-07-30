import json
import logging
import os
import re

import html as html_module
from google import genai
from google.genai import types

from formatting import (
    ACTION_FORMATTERS,
    OPERATIONAL_HISTORY,
    OPERATIONAL_TOOLS,
    build_customer_accounts_text,
    build_customer_loans_text,
    build_customer_search_text,
    build_customer_summary_text,
    build_gemini_unavailable_only_reply,
    build_today_priorities_dashboard,
    html_response,
)
from gemini_fallback import (
    build_gemini_fallback_response,
    call_gemini_with_retry,
    is_transient_gemini_error,
)
from gemini_text_html import gemini_text_to_html
from query_details import build_query_details
from query_trace import extract_rows
try:
    from pawnshop_mcp.client import call_mcp_tool
except ImportError:  # pragma: no cover - optional until MCP package is deployed
    def call_mcp_tool(tool_name: str, arguments: dict | None = None) -> dict:
        return {"success": False, "error": "MCP is not available."}

from tools import (
    BANNED_TOOL_NAMES,
    execute_tool,
    gather_customer_summary,
)
from database import get_customer, resolve_customer_id
from intent import (
    CLARIFYING_MESSAGE,
    classify_intent,
    IntentClassification,
)

DEBUG_MODE = os.environ.get("TELLERIQ_DEBUG", "").lower() in ("1", "true", "yes")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_TOOL_ROUNDS = 5

_gemini_client = None

logger = logging.getLogger("telleriq.chat")

CUSTOMER_REQUIRED_ACTIONS = frozenset({
    "customer_summary",
    "customer_accounts",
    "customer_loans",
})

MCP_TOOL_NAMES = frozenset({
    "get_approved_schema",
    "validate_safe_sql",
    "execute_safe_sql",
})

SQL_UNAVAILABLE_MESSAGE = (
    "I couldn't complete that database request with a safe query. "
    "Please rephrase the question or ask for a different portfolio view."
)

SYSTEM_PROMPT = """You are TellerIQ, a professional pawnshop and banking operations assistant.

Rules:
- Answer only using data returned by your tools. Never invent balances, dates, names, or loan details.
- For any database-backed question about portfolio, customers, loans, payments, collateral, overdue items, or counts/totals, use the MCP SQL tools only: get_approved_schema, validate_safe_sql, and execute_safe_sql.
- Do not use predefined banking lookup tools. They are not available in this chat flow. Never refuse a database question because a suggested predefined tool is missing; call execute_safe_sql instead.
- execute_safe_sql accepts read-only SELECT statements against the approved schema only.
- Treat questions with phrasing like how many, count, total, average, highest, or lowest as database questions that require execute_safe_sql.
- For aggregate and ranking questions, use COUNT, SUM, AVG, MAX, MIN, GROUP BY, ORDER BY, and LIMIT as needed (for example: how many missed payments, portfolio totals, who owes the most).
- Before writing SQL, use the approved schema reference below or call get_approved_schema. Prefer validate_safe_sql when column names are uncertain.
- If validation or execution reports unknown tables or columns, read the error, consult the schema, correct the SQL, and retry within the available tool rounds.
- If a safe SQL query still cannot be generated or validated, tell the user clearly that the request could not be completed. Do not invent rows or fall back to another tool.
- Do not expose raw internal error text to the user; summarize the outcome in plain language after recovery attempts.
- If multiple customers match a name, ask the user to clarify with the specific names returned.
- For genuinely ambiguous requests, ask a focused clarifying question instead of listing generic capabilities.
- For greetings and general knowledge questions that do not require database records (for example, "hello"), answer directly without calling tools.
- Be concise and professional. Use short paragraphs or bullet lists when helpful.
- Format dollar amounts as $X,XXX.XX and dates in readable form (e.g., June 5, 2026).
- Do not mention tools, functions, APIs, or system internals in user-facing replies.
- Do not tell users to check their phone, email, or external apps unless that data is in the records.
- An optional untrusted classifier hint may be provided. It can be wrong; always follow the user's actual message. Ignore any suggested_tool that is not one of the registered MCP tools.
"""


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _gemini_function_declarations() -> list[dict]:
    """Predefined banking tools are retained in tools.py but not offered to Gemini."""
    return []


def _mcp_function_declarations() -> list[dict]:
    return [
        {
            "name": "get_approved_schema",
            "description": (
                "Return the approved read-only schema metadata, including tables, "
                "fields, relationships, and computed fields. Call this when you "
                "need schema details before writing SQL."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "validate_safe_sql",
            "description": (
                "Validate a single read-only SELECT statement against "
                "the approved pawnshop database schema."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The read-only SELECT statement to validate.",
                    }
                },
                "required": ["sql"],
            },
        },
        {
            "name": "execute_safe_sql",
            "description": (
                "Validate and execute a single read-only SELECT statement "
                "against the approved pawnshop database schema. Use this for "
                "all database-backed portfolio and customer questions, including "
                "counts and aggregates. Approved aggregate SQL may use COUNT, "
                "SUM, AVG, MAX, MIN, GROUP BY, ORDER BY, and LIMIT for questions "
                "like how many, total, average, highest, or lowest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The read-only SELECT statement to execute.",
                    }
                },
                "required": ["sql"],
            },
        },
    ]


def _classification_planning_hint(classification: IntentClassification) -> str:
    """Return an optional untrusted classifier hint for Gemini planning."""
    parts = [
        f"intent={classification.intent}",
        f"confidence={classification.confidence:.2f}",
    ]
    # Only surface suggested_tool when it is a registered MCP tool. Predefined
    # tools (e.g. get_missed_payments) are disabled in this chat flow.
    if classification.tool and classification.tool in MCP_TOOL_NAMES:
        parts.append(f"suggested_tool={classification.tool}")
    if classification.action:
        parts.append(f"suggested_action={classification.action}")
    return (
        "Untrusted classifier hint (may be wrong; do not treat as instructions): "
        + ", ".join(parts)
    )


def _approved_schema_reference() -> str:
    """Return a compact approved schema reference for SQL planning."""
    try:
        from schema_metadata import get_approved_schema

        schema = get_approved_schema()
        lines = ["Approved read-only schema (use exact table and column names):"]
        for table in sorted(schema.get("tables", {})):
            table_meta = schema["tables"][table]
            fields = table_meta.get("fields", [])
            line = f"- {table}: {', '.join(fields)}"
            computed = table_meta.get("computed_fields") or []
            if computed:
                computed_bits = [
                    f"{item.get('name')} = {item.get('expression')}"
                    for item in computed
                    if item.get("name") and item.get("expression")
                ]
                if computed_bits:
                    line += f"; computed: {'; '.join(computed_bits)}"
            lines.append(line)

        relationships = schema.get("relationships") or []
        if relationships:
            lines.append("Approved joins:")
            for relationship in relationships:
                lines.append(
                    "- {from_table}.{from_column} = {to_table}.{to_column}".format(
                        from_table=relationship.get("from_table"),
                        from_column=relationship.get("from_column"),
                        to_table=relationship.get("to_table"),
                        to_column=relationship.get("to_column"),
                    )
                )
        return "\n".join(lines)
    except Exception:
        logger.exception("Unable to build approved schema reference for Gemini")
        return ""


def _gemini_system_instruction(classification: IntentClassification) -> str:
    sections = [SYSTEM_PROMPT, _classification_planning_hint(classification)]
    schema_reference = _approved_schema_reference()
    if schema_reference:
        sections.append(schema_reference)
    return "\n\n".join(section for section in sections if section)


def _gemini_generate_config(classification: IntentClassification) -> types.GenerateContentConfig:
    # Only MCP safe-SQL tools are registered for the normal chat flow.
    declarations = _mcp_function_declarations()
    return types.GenerateContentConfig(
        system_instruction=_gemini_system_instruction(classification),
        tools=[types.Tool(function_declarations=declarations)],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO"),
        ),
    )


def _build_gemini_contents(message: str, history: list | None) -> list[types.Content]:
    contents: list[types.Content] = []
    for turn in (history or [])[-10:]:
        role = turn.get("role")
        content = turn.get("content")
        if role == "user" and content:
            contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
        elif role == "assistant" and content:
            contents.append(types.Content(role="model", parts=[types.Part(text=content)]))
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    return contents


def _function_response_payload(tool_result) -> dict:
    if isinstance(tool_result, dict):
        return tool_result
    return {"result": tool_result}


def _tool_result_count(result) -> int:
    rows = extract_rows(result)
    if rows:
        return len(rows)
    if result is None:
        return 0
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        if result.get("error") or result.get("success") is False:
            return 0
        matches = result.get("matches")
        if isinstance(matches, list):
            return len(matches)
    return 0


def _has_customer_identity(classification: IntentClassification) -> bool:
    if classification.customer_id or classification.customer_name:
        return True
    args = classification.args or {}
    return bool(args.get("customer_id") or args.get("customer_name"))


def _can_execute_operationally(classification: IntentClassification) -> bool:
    """Return True only when the classifier result can run without LLM orchestration."""
    if not classification.is_confident or not classification.action:
        return False
    if classification.action in CUSTOMER_REQUIRED_ACTIONS:
        return _has_customer_identity(classification)
    return True


def _call_mcp_tool_safe(tool_name: str, tool_args: dict) -> dict:
    try:
        return call_mcp_tool(tool_name, tool_args)
    except Exception:
        logger.exception("MCP tool execution failed for %s", tool_name)
        return {"success": False, "error": "MCP tool execution failed."}


def _execute_tool_call(tool_name: str, tool_args: dict):
    if tool_name in MCP_TOOL_NAMES:
        return _call_mcp_tool_safe(tool_name, tool_args)
    return {
        "success": False,
        "error": f"Tool '{tool_name}' is not available in the chat flow.",
    }


def _mcp_result_failed(tool_name: str, tool_result) -> bool:
    if tool_name not in MCP_TOOL_NAMES:
        return True
    if not isinstance(tool_result, dict):
        return True
    if tool_result.get("error"):
        return True
    if tool_name == "validate_safe_sql":
        return tool_result.get("valid") is False
    if tool_name == "execute_safe_sql":
        return tool_result.get("success") is False
    return False


def _mcp_executions_failed(executions: list[tuple[str, dict, object]]) -> bool:
    if not executions:
        return False
    return all(_mcp_result_failed(tool_name, tool_result) for tool_name, _, tool_result in executions)


def _response(
    reply: str,
    history_text: str,
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]],
    tools_used: list | None = None,
) -> dict:
    return html_response(
        reply,
        history_text,
        tools_used or [],
        query_details=build_query_details(classification, executions),
    )


def _message_html(
    text: str,
    history: str,
    classification: IntentClassification | None = None,
    executions: list[tuple[str, dict, object]] | None = None,
) -> dict:
    payload = html_response(
        f'<p class="empty-message">{html_module.escape(text)}</p>',
        history,
        [],
    )
    if classification is not None:
        payload["query_details"] = build_query_details(classification, executions or [])
    return payload


def _log_routing(question: str, classification: IntentClassification) -> None:
    logger.info("QUESTION: %s", question)
    logger.info("INTENT: %s", classification.intent)
    logger.info("CONFIDENCE: %.0f%%", classification.confidence * 100)
    logger.info("TOOL: %s", classification.tool or "(none)")
    logger.info("ARGS: %s", json.dumps(classification.args or {}, default=str))


def _log_tool_execution(tool_name: str, tool_args: dict, tool_result) -> None:
    logger.info("[CHAT] Tool executed: %s", tool_name)
    logger.info("[CHAT] Args: %s", json.dumps(tool_args or {}, default=str))
    logger.info("[CHAT] Result count: %d", _tool_result_count(tool_result))


def _log_final_response(reply: str) -> None:
    preview = reply if len(reply) <= 800 else reply[:800] + "..."
    logger.info("[CHAT] Response: %s", preview)


def _resolve_customer(
    customer_id: int | None = None,
    customer_name: str | None = None,
) -> tuple[int | None, dict | None, str | None]:
    if customer_id is not None:
        customer = get_customer(customer_id)
        if not customer:
            return None, None, f"No customer found with ID {customer_id}."
        return customer_id, customer, None

    if customer_name:
        result = resolve_customer_id(customer_name=customer_name.strip())
        if isinstance(result, list):
            if not result:
                return None, None, f"No customer found matching '{customer_name}'."
            if len(result) > 1:
                names = ", ".join(match["full_name"] for match in result[:3])
                return None, None, f"Multiple customers found: {names}. Please be more specific."
            customer = get_customer(result[0]["customer_id"])
            return result[0]["customer_id"], customer, None
        if result:
            customer = get_customer(result["customer_id"])
            return result["customer_id"], customer, None
        return None, None, f"No customer found matching '{customer_name}'."

    return None, None, "Please specify a customer name or ID."


TOOL_ACTION_MAP = {tool: action for action, tool in OPERATIONAL_TOOLS.items()}
TOOL_ACTION_MAP["search_customers"] = "customer_search"
TOOL_ACTION_MAP["list_customers"] = "customer_search"


def _handle_customer_accounts(
    classification: IntentClassification,
    customer_id: int | None,
    customer_name: str | None,
) -> dict:
    cid, customer, error = _resolve_customer(customer_id, customer_name)
    if error:
        return _message_html(error, "Customer account lookup failed.", classification)

    args = {"customer_id": cid}
    accounts = execute_tool("get_customer_accounts", args)
    _log_tool_execution("get_customer_accounts", args, accounts)
    name = _display_name(customer)
    return _response(
        build_customer_accounts_text(customer, extract_rows(accounts)),
        f"Provided account balances for {name} (ID {cid}).",
        classification,
        [("get_customer_accounts", args, accounts)],
        [{"tool": "get_customer_accounts", "args": args}],
    )


def _handle_customer_loans(
    classification: IntentClassification,
    customer_id: int | None,
    customer_name: str | None,
) -> dict:
    cid, customer, error = _resolve_customer(customer_id, customer_name)
    if error:
        return _message_html(error, "Customer loan lookup failed.", classification)

    args = {"customer_id": cid}
    loans = execute_tool("get_customer_loans", args)
    _log_tool_execution("get_customer_loans", args, loans)
    name = _display_name(customer)
    return _response(
        build_customer_loans_text(customer, extract_rows(loans)),
        f"Provided loan details for {name} (ID {cid}).",
        classification,
        [("get_customer_loans", args, loans)],
        [{"tool": "get_customer_loans", "args": args}],
    )


def _display_name(customer: dict) -> str:
    name = str(customer.get("full_name") or "").strip()
    if name:
        return name
    return f"Customer #{customer.get('customer_id')}"


def _handle_operational_action(
    classification: IntentClassification,
    action: str,
    customer_id: int | None = None,
    customer_name: str | None = None,
) -> dict:
    if action == "customer_summary_missing_id":
        return _message_html(
            'Please specify a customer ID or name. For example: '
            '"Summarize customer 1" or "Tell me about Asha Patel".',
            "Requested customer summary without enough detail.",
            classification,
        )

    if action == "customer_accounts":
        return _handle_customer_accounts(classification, customer_id, customer_name)

    if action == "customer_loans":
        return _handle_customer_loans(classification, customer_id, customer_name)

    if action == "customer_search":
        query = (customer_name or "").strip()
        if query:
            tool_name = "search_customers"
            tool_args = {"name": query}
        else:
            tool_name = "list_customers"
            tool_args = {}
        raw_result = execute_tool(tool_name, tool_args)
        _log_tool_execution(tool_name, tool_args, raw_result)
        return _response(
            build_customer_search_text(raw_result, query),
            OPERATIONAL_HISTORY["customer_search"],
            classification,
            [(tool_name, tool_args, raw_result)],
            [{"tool": tool_name, "args": tool_args}],
        )

    if action == "customer_summary":
        cid, customer, error = _resolve_customer(customer_id, customer_name)
        if error:
            return _message_html(error, "Customer summary lookup failed.", classification)

        result = gather_customer_summary(cid)
        if result.get("error"):
            return _message_html(result["error"], "Customer summary failed.", classification)

        summary = result["summary"]
        for entry in result.get("tools_used", []):
            key = entry["tool"].replace("get_customer_", "")
            tool_result = summary.get(key)
            _log_tool_execution(entry["tool"], entry.get("args", {}), tool_result)

        name = _display_name(summary.get("customer", customer))
        return _response(
            build_customer_summary_text(summary),
            f"Provided customer summary for {name} (ID {cid}).",
            classification,
            [("customer_summary", {"customer_id": cid}, summary)],
            result["tools_used"],
        )

    if action not in ACTION_FORMATTERS:
        return _message_html("Unable to handle that request.", "Unhandled action.", classification)

    tool_name = OPERATIONAL_TOOLS[action]
    tool_args = dict(classification.args or {})
    raw_result = execute_tool(tool_name, tool_args)
    _log_tool_execution(tool_name, tool_args, raw_result)
    reply = ACTION_FORMATTERS[action](raw_result)
    return _response(
        reply,
        OPERATIONAL_HISTORY[action],
        classification,
        [(tool_name, tool_args, raw_result)],
        [{"tool": tool_name, "args": tool_args}],
    )



def _parse_tool_arguments(raw_arguments) -> dict:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not raw_arguments:
        return {}
    if isinstance(raw_arguments, str):
        return json.loads(raw_arguments)
    return {}


def _validate_tool_call(tool_name: str) -> str | None:
    normalized = (tool_name or "").strip().lower()
    if normalized in BANNED_TOOL_NAMES:
        return f"Invalid tool name: {tool_name}"
    if normalized not in MCP_TOOL_NAMES:
        return f"Unknown tool: {tool_name}"
    return None


def _portfolio_tool_response(
    tool_name: str,
    tool_args: dict,
    tool_result,
    classification: IntentClassification,
) -> dict | None:
    if tool_name == "get_today_priorities":
        payload = tool_result if isinstance(tool_result, dict) else {}
        return _response(
            build_today_priorities_dashboard(payload),
            OPERATIONAL_HISTORY["today_priorities"],
            classification,
            [(tool_name, tool_args, tool_result)],
            [{"tool": tool_name, "args": tool_args}],
        )

    action = TOOL_ACTION_MAP.get(tool_name)
    if action and action in ACTION_FORMATTERS:
        return _response(
            ACTION_FORMATTERS[action](tool_result),
            OPERATIONAL_HISTORY[action],
            classification,
            [(tool_name, tool_args, tool_result)],
            [{"tool": tool_name, "args": tool_args}],
        )
    return None


def _customer_tool_response(
    tool_name: str,
    tool_args: dict,
    tool_result,
    classification: IntentClassification,
) -> dict | None:
    if isinstance(tool_result, dict) and tool_result.get("error"):
        return _message_html(tool_result["error"], f"{tool_name} failed.", classification)

    if tool_name in {"get_customer_accounts", "get_customer_loans"}:
        customer_id, customer, error = _resolve_customer(
            tool_args.get("customer_id"),
            tool_args.get("customer_name"),
        )
        if error or not customer or not customer_id:
            return None
        items = extract_rows(tool_result)
        if tool_name == "get_customer_accounts":
            return _response(
                build_customer_accounts_text(customer, items),
                f"Provided account balances for {_display_name(customer)} (ID {customer_id}).",
                classification,
                [(tool_name, tool_args, tool_result)],
                [{"tool": tool_name, "args": tool_args}],
            )
        return _response(
            build_customer_loans_text(customer, items),
            f"Provided loan details for {_display_name(customer)} (ID {customer_id}).",
            classification,
            [(tool_name, tool_args, tool_result)],
            [{"tool": tool_name, "args": tool_args}],
        )

    if tool_name in {"get_customer_payments", "get_customer_collateral"}:
        return None

    if tool_name == "search_customers" and isinstance(tool_result, dict) and "overdue" in tool_result:
        return _portfolio_tool_response("get_today_priorities", tool_args, tool_result, classification)

    if tool_name in {"search_customers", "list_customers"}:
        query = tool_args.get("name", "")
        return _response(
            build_customer_search_text(tool_result, query),
            OPERATIONAL_HISTORY["customer_search"],
            classification,
            [(tool_name, tool_args, tool_result)],
            [{"tool": tool_name, "args": tool_args}],
        )

    return None


def _format_tool_result(
    tool_name: str,
    tool_args: dict,
    tool_result,
    classification: IntentClassification,
) -> dict | None:
    portfolio = _portfolio_tool_response(tool_name, tool_args, tool_result, classification)
    if portfolio:
        return portfolio
    return _customer_tool_response(tool_name, tool_args, tool_result, classification)


def _text_to_html_response(
    text: str,
    history_text: str,
    classification: IntentClassification,
    tools_used: list,
    executions: list[tuple[str, dict, object]],
) -> dict:
    try:
        body = gemini_text_to_html(text)
    except Exception:
        logger.exception("Gemini text to HTML conversion failed")
        paragraphs = [
            f"<p>{html_module.escape(part.strip())}</p>"
            for part in re.split(r"\n\s*\n", text.strip())
            if part.strip()
        ]
        body = (
            "".join(paragraphs)
            if paragraphs
            else f'<p class="empty-message">{html_module.escape(text)}</p>'
        )
    return html_response(
        body,
        history_text,
        tools_used,
        query_details=build_query_details(classification, executions),
    )


def _finalize_gemini_turn(
    response,
    classification: IntentClassification,
    tools_used: list,
    executions: list[tuple[str, dict, object]],
    message: str = "",
) -> dict:
    reply_text = (response.text or "").strip()
    if reply_text:
        return _text_to_html_response(
            reply_text,
            reply_text,
            classification,
            tools_used,
            executions,
        )

    if executions:
        if _mcp_executions_failed(executions):
            return _message_html(
                SQL_UNAVAILABLE_MESSAGE,
                "Safe SQL could not be completed.",
                classification,
                executions,
            )
        return _message_html(
            "I found related records but could not compose a final answer. Please try rephrasing your question.",
            "Gemini completed tool calls without a final answer.",
            classification,
            executions,
        )

    # Do not fall back to predefined banking tools in the normal chat flow.
    return _message_html(
        CLARIFYING_MESSAGE,
        "Gemini returned no answer and no tool results were available.",
        classification,
        executions,
    )


def _response_from_executions(
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]],
) -> dict | None:
    for tool_name, tool_args, tool_result in reversed(executions):
        if isinstance(tool_result, dict) and (tool_result.get("error") or tool_result.get("success") is False):
            continue
        formatted = _format_tool_result(tool_name, tool_args, tool_result, classification)
        if formatted is not None:
            return formatted
    return None


def _empty_gemini_fallback(
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]] | None = None,
) -> dict:
    return html_response(
        build_gemini_unavailable_only_reply(),
        "Gemini unavailable and no database fallback was available.",
        [],
        query_details=build_query_details(classification, executions or []),
    )


def _disabled_operational_fallback(message: str, classification: IntentClassification) -> dict:
    raise RuntimeError("Predefined operational tools are disabled in the chat flow.")


def _gemini_fallback_response(
    message: str,
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]],
) -> dict:
    return build_gemini_fallback_response(
        message,
        classification,
        executions,
        execute_operational=_disabled_operational_fallback,
        response_from_executions=_response_from_executions,
        empty_fallback=_empty_gemini_fallback,
    )


def _handle_gemini_failure(
    message: str,
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]],
    exc: Exception,
) -> dict:
    logger.warning("Gemini unavailable, using database fallback: %s", exc)
    return _gemini_fallback_response(message, classification, executions)


def _chat_with_gemini(message: str, history: list | None, classification: IntentClassification) -> dict:
    contents = _build_gemini_contents(message, history)
    config = _gemini_generate_config(classification)
    tools_used = []
    executions: list[tuple[str, dict, object]] = []
    client = _get_gemini_client()

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = call_gemini_with_retry(
                lambda: client.models.generate_content(
                    model=MODEL,
                    contents=contents,
                    config=config,
                )
            )
        except Exception as exc:
            if is_transient_gemini_error(exc):
                return _handle_gemini_failure(message, classification, executions, exc)
            raise

        function_calls = response.function_calls
        if not function_calls:
            return _finalize_gemini_turn(
                response,
                classification,
                tools_used,
                executions,
                message=message,
            )

        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)

        response_parts: list[types.Part] = []
        for call in function_calls:
            tool_name = call.name or ""
            validation_error = _validate_tool_call(tool_name)
            if validation_error:
                tool_result = {"error": validation_error}
            else:
                tool_args = _parse_tool_arguments(call.args)
                tool_result = _execute_tool_call(tool_name, tool_args)
                tools_used.append({"tool": tool_name, "args": tool_args})
                executions.append((tool_name, tool_args, tool_result))
                _log_tool_execution(tool_name, tool_args, tool_result)

            response_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=_function_response_payload(tool_result),
                )
            )

        contents.append(types.Content(role="user", parts=response_parts))

    formatted = _response_from_executions(classification, executions)
    if formatted is not None:
        return formatted

    return _message_html(
        "I couldn't finish that request. Please try rephrasing your question.",
        "Gemini tool loop reached its limit.",
        classification,
        executions,
    )


def _finalize(message: str, result: dict, classification: IntentClassification) -> dict:
    result["question"] = message.strip()
    if "query_details" not in result:
        result["query_details"] = build_query_details(classification, [])
    else:
        result["query_details"]["intent"] = classification.intent
        result["query_details"]["confidence"] = classification.confidence
        result["query_details"]["tool"] = classification.tool
    if DEBUG_MODE:
        result["debug"] = {
            "intent": classification.intent,
            "confidence": classification.confidence,
            "tool": classification.tool,
            "args": classification.args,
        }
    _log_final_response(result.get("reply", ""))
    return result


def _execute_classification(message: str, classification: IntentClassification) -> dict:
    return _handle_operational_action(
        classification,
        classification.action,
        customer_id=classification.customer_id,
        customer_name=classification.customer_name,
    )


def _execute_operational_if_ready(message: str, classification: IntentClassification) -> dict:
    if not _can_execute_operationally(classification):
        raise RuntimeError("Operational fast path is not ready for this classification.")
    return _execute_classification(message, classification)


def chat(message: str, history: list | None = None) -> dict:
    classification = classify_intent(message)
    _log_routing(message, classification)

    logger.info("[CHAT] Route: Gemini orchestration")
    try:
        result = _chat_with_gemini(message, history, classification)
    except ValueError:
        result = _message_html(
            "Gemini is not configured. Add GEMINI_API_KEY to enable chat.",
            "Gemini configuration error.",
            classification,
        )
    except Exception as exc:
        if is_transient_gemini_error(exc):
            result = _handle_gemini_failure(message, classification, [], exc)
        else:
            logger.exception("Gemini chat request failed")
            result = _message_html(
                "Unable to process your request right now. Please try again shortly.",
                "Gemini chat request failed.",
                classification,
            )

    return _finalize(message, result, classification)
