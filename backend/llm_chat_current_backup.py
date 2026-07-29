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
from query_details import build_query_details
from query_trace import extract_rows
from pawnshop_mcp.client import call_mcp_tool
from tools import (
    ALLOWED_TOOL_NAMES,
    BANNED_TOOL_NAMES,
    TOOL_DEFINITIONS,
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

SYSTEM_PROMPT = """You are TellerIQ, a professional pawnshop and banking operations assistant.

Rules:
- Answer only using data returned by your tools. Never invent balances, dates, names, or loan details.
- For customer-specific questions, call the appropriate lookup tool before answering.
- If multiple customers match a name, ask the user to clarify.
- Be concise and professional. Use short paragraphs or bullet lists when helpful.
- Format dollar amounts as $X,XXX.XX and dates in readable form (e.g., June 5, 2026).
- Do not mention tools, functions, APIs, or system internals in user-facing replies.
- Do not tell users to check their phone, email, or external apps unless that data is in the records.
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


MCP_TOOL_NAMES = {
    "validate_safe_sql",
    "execute_safe_sql",
}


def _gemini_function_declarations() -> list[dict]:
    declarations = []
    for tool in TOOL_DEFINITIONS:
        function = tool["function"]
        declarations.append(
            {
                "name": function["name"],
                "description": function["description"],
                "parameters": function["parameters"],
            }
        )
    return declarations


def _mcp_function_declarations() -> list[dict]:
    return [
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
                "against the approved pawnshop database schema. Use this only "
                "when no existing predefined tool directly answers the question."
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


def _gemini_generate_config() -> types.GenerateContentConfig:
    declarations = (
        _gemini_function_declarations()
        + _mcp_function_declarations()
    )

    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[
            types.Tool(
                function_declarations=declarations,
            )
        ],
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
        if result.get("error"):
            return 0
        matches = result.get("matches")
        if isinstance(matches, list):
            return len(matches)
    return 0


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


def _clarifying_response(classification: IntentClassification) -> dict:
    return _message_html(
        CLARIFYING_MESSAGE,
        "Asked a clarifying question because intent confidence was below threshold.",
        classification,
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

    allowed_names = set(ALLOWED_TOOL_NAMES) | MCP_TOOL_NAMES
    if normalized not in allowed_names:
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
    paragraphs = [
        f"<p>{html_module.escape(part.strip())}</p>"
        for part in re.split(r"\n\s*\n", text.strip())
        if part.strip()
    ]
    body = "".join(paragraphs) if paragraphs else f'<p class="empty-message">{html_module.escape(text)}</p>'
    return html_response(
        body,
        history_text,
        tools_used,
        query_details=build_query_details(classification, executions),
    )


def _response_from_executions(
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]],
) -> dict | None:
    for tool_name, tool_args, tool_result in reversed(executions):
        if isinstance(tool_result, dict) and tool_result.get("error"):
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


def _gemini_fallback_response(
    message: str,
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]],
) -> dict:
    return build_gemini_fallback_response(
        message,
        classification,
        executions,
        execute_operational=_execute_classification,
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
    config = _gemini_generate_config()
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
            reply_text = (response.text or "").strip()
            if not reply_text:
                reply_text = CLARIFYING_MESSAGE
            return _text_to_html_response(
                reply_text,
                "Answered with Gemini using conversation context.",
                classification,
                tools_used,
                executions,
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

                if tool_name in MCP_TOOL_NAMES:
                    tool_result = call_mcp_tool(tool_name, tool_args)
                else:
                    tool_result = execute_tool(tool_name, tool_args)

                tools_used.append({"tool": tool_name, "args": tool_args})
                executions.append((tool_name, tool_args, tool_result))
                _log_tool_execution(tool_name, tool_args, tool_result)

                formatted = _format_tool_result(tool_name, tool_args, tool_result, classification)
                if formatted is not None:
                    return formatted

            response_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=_function_response_payload(tool_result),
                )
            )

        contents.append(types.Content(role="user", parts=response_parts))

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
    needs_customer = classification.action in {
        "customer_summary",
        "customer_accounts",
        "customer_loans",
    }
    has_customer = bool(classification.customer_id or classification.customer_name)

    if needs_customer and not has_customer:
        if classification.action == "customer_summary":
            return _handle_operational_action(classification, "customer_summary_missing_id")
        return _clarifying_response(classification)

    return _handle_operational_action(
        classification,
        classification.action,
        customer_id=classification.customer_id,
        customer_name=classification.customer_name,
    )


def chat(message: str, history: list | None = None) -> dict:
    classification = classify_intent(message)
    _log_routing(message, classification)

    if classification.is_confident and classification.action:
        try:
            result = _execute_classification(message, classification)
        except Exception as exc:
            result = _message_html(
                f"Unable to retrieve records: {exc}",
                "Operational query failed.",
                classification,
            )
        return _finalize(message, result, classification)

    try:
        result = _chat_with_gemini(message, history, classification)
    except ValueError:
        result = _message_html(
            "Gemini is not configured. Operational database queries still work.",
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