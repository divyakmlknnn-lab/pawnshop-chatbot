import json
import logging
import os
import re

import html as html_module
from openai import OpenAI

from formatting import (
    OPERATIONAL_HANDLERS,
    OPERATIONAL_HISTORY,
    OPERATIONAL_TOOLS,
    build_collateral_at_risk_text,
    build_customer_accounts_text,
    build_customer_loans_text,
    build_customer_summary_text,
    build_due_soon_customers_text,
    build_high_risk_loans_text,
    build_missed_payments_text,
    build_overdue_customers_text,
    build_today_priorities_response,
    html_response,
)
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

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOOL_ROUNDS = 5

_openai_client = None

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


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def _tool_result_count(result) -> int:
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
        list_values = [value for value in result.values() if isinstance(value, list)]
        if list_values:
            return sum(len(value) for value in list_values)
        return 1
    return 0


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


def _message_html(text: str, history: str) -> dict:
    return html_response(
        f'<p class="empty-message">{html_module.escape(text)}</p>',
        history,
        [],
    )


def _respond_today_priorities() -> dict:
    raw = execute_tool("get_today_priorities", {})
    _log_tool_execution("get_today_priorities", {}, raw)
    return build_today_priorities_response(raw)


def _handle_customer_accounts(customer_id: int | None, customer_name: str | None) -> dict:
    cid, customer, error = _resolve_customer(customer_id, customer_name)
    if error:
        return _message_html(error, "Customer account lookup failed.")

    args = {"customer_id": cid}
    accounts = execute_tool("get_customer_accounts", args)
    _log_tool_execution("get_customer_accounts", args, accounts)
    name = _display_name(customer)
    return html_response(
        build_customer_accounts_text(customer, accounts if isinstance(accounts, list) else []),
        f"Provided account balances for {name} (ID {cid}).",
        [{"tool": "get_customer_accounts", "args": args}],
    )


def _handle_customer_loans(customer_id: int | None, customer_name: str | None) -> dict:
    cid, customer, error = _resolve_customer(customer_id, customer_name)
    if error:
        return _message_html(error, "Customer loan lookup failed.")

    args = {"customer_id": cid}
    loans = execute_tool("get_customer_loans", args)
    _log_tool_execution("get_customer_loans", args, loans)
    name = _display_name(customer)
    return html_response(
        build_customer_loans_text(customer, loans if isinstance(loans, list) else []),
        f"Provided loan details for {name} (ID {cid}).",
        [{"tool": "get_customer_loans", "args": args}],
    )


def _display_name(customer: dict) -> str:
    name = str(customer.get("full_name") or "").strip()
    if name:
        return name
    return f"Customer #{customer.get('customer_id')}"


def _handle_operational_action(
    action: str,
    customer_id: int | None = None,
    customer_name: str | None = None,
) -> dict:
    if action == "customer_summary_missing_id":
        return _message_html(
            'Please specify a customer ID or name. For example: '
            '"Summarize customer 1" or "Tell me about Asha Patel".',
            "Requested customer summary without enough detail.",
        )

    if action == "customer_accounts":
        return _handle_customer_accounts(customer_id, customer_name)

    if action == "customer_loans":
        return _handle_customer_loans(customer_id, customer_name)

    if action == "customer_summary":
        cid, customer, error = _resolve_customer(customer_id, customer_name)
        if error:
            return _message_html(error, "Customer summary lookup failed.")

        result = gather_customer_summary(cid)
        if result.get("error"):
            return _message_html(result["error"], "Customer summary failed.")

        summary = result["summary"]
        for entry in result.get("tools_used", []):
            key = entry["tool"].replace("get_customer_", "")
            _log_tool_execution(entry["tool"], entry.get("args", {}), summary.get(key))

        name = _display_name(summary.get("customer", customer))
        return html_response(
            build_customer_summary_text(summary),
            f"Provided customer summary for {name} (ID {cid}).",
            result["tools_used"],
        )

    if action not in OPERATIONAL_HANDLERS:
        return _message_html("Unable to handle that request.", "Unhandled action.")

    if action == "today_priorities":
        return _respond_today_priorities()

    tool_name = OPERATIONAL_TOOLS[action]
    raw_result = execute_tool(tool_name, {})
    _log_tool_execution(tool_name, {}, raw_result)
    reply = OPERATIONAL_HANDLERS[action]()
    return html_response(
        reply,
        OPERATIONAL_HISTORY[action],
        [{"tool": tool_name, "args": {}}],
    )


def _clarifying_response() -> dict:
    return _message_html(
        CLARIFYING_MESSAGE,
        "Asked a clarifying question because intent confidence was below threshold.",
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
    if normalized not in ALLOWED_TOOL_NAMES:
        return f"Unknown tool: {tool_name}"
    return None


def _portfolio_tool_response(tool_name: str, tool_args: dict, tool_result) -> dict | None:
    if tool_name == "get_today_priorities":
        payload = tool_result if isinstance(tool_result, dict) else {}
        return build_today_priorities_response(payload)

    list_formatters = {
        "get_overdue_customers": ("overdue_customers", build_overdue_customers_text),
        "get_due_soon_customers": ("due_soon_customers", build_due_soon_customers_text),
        "get_missed_payments": ("missed_payments", build_missed_payments_text),
        "get_high_risk_loans": ("high_risk_loans", build_high_risk_loans_text),
        "get_collateral_at_risk": ("collateral_at_risk", build_collateral_at_risk_text),
    }
    if tool_name in list_formatters:
        action, formatter = list_formatters[tool_name]
        items = tool_result if isinstance(tool_result, list) else []
        return html_response(
            formatter(items),
            OPERATIONAL_HISTORY[action],
            [{"tool": tool_name, "args": tool_args}],
        )
    return None


def _customer_tool_response(tool_name: str, tool_args: dict, tool_result) -> dict | None:
    if isinstance(tool_result, dict) and tool_result.get("error"):
        return _message_html(tool_result["error"], f"{tool_name} failed.")

    if tool_name in {"get_customer_accounts", "get_customer_loans"}:
        customer_id, customer, error = _resolve_customer(
            tool_args.get("customer_id"),
            tool_args.get("customer_name"),
        )
        if error or not customer or not customer_id:
            return None
        items = tool_result if isinstance(tool_result, list) else []
        if tool_name == "get_customer_accounts":
            return html_response(
                build_customer_accounts_text(customer, items),
                f"Provided account balances for {_display_name(customer)} (ID {customer_id}).",
                [{"tool": tool_name, "args": tool_args}],
            )
        return html_response(
            build_customer_loans_text(customer, items),
            f"Provided loan details for {_display_name(customer)} (ID {customer_id}).",
            [{"tool": tool_name, "args": tool_args}],
        )

    if tool_name in {"get_customer_payments", "get_customer_collateral"}:
        return None

    if tool_name == "search_customers" and isinstance(tool_result, dict) and "overdue" in tool_result:
        return build_today_priorities_response(tool_result)

    return None


def _format_tool_result(tool_name: str, tool_args: dict, tool_result) -> dict | None:
    portfolio = _portfolio_tool_response(tool_name, tool_args, tool_result)
    if portfolio:
        return portfolio
    return _customer_tool_response(tool_name, tool_args, tool_result)


def _text_to_html_response(text: str, history_text: str, tools_used: list) -> dict:
    paragraphs = [
        f"<p>{html_module.escape(part.strip())}</p>"
        for part in re.split(r"\n\s*\n", text.strip())
        if part.strip()
    ]
    body = "".join(paragraphs) if paragraphs else f'<p class="empty-message">{html_module.escape(text)}</p>'
    return html_response(body, history_text, tools_used)


def _chat_with_openai(message: str, history: list | None) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-10:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    tools_used = []
    client = _get_openai_client()

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )
        assistant_message = response.choices[0].message

        if not assistant_message.tool_calls:
            reply_text = (assistant_message.content or "").strip()
            if not reply_text:
                reply_text = CLARIFYING_MESSAGE
            return _text_to_html_response(
                reply_text,
                "Answered with OpenAI using conversation context.",
                tools_used,
            )

        messages.append(
            {
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in assistant_message.tool_calls
                ],
            }
        )

        for call in assistant_message.tool_calls:
            tool_name = call.function.name
            validation_error = _validate_tool_call(tool_name)
            if validation_error:
                tool_result = {"error": validation_error}
            else:
                tool_args = _parse_tool_arguments(call.function.arguments)
                tool_result = execute_tool(tool_name, tool_args)
                tools_used.append({"tool": tool_name, "args": tool_args})
                _log_tool_execution(tool_name, tool_args, tool_result)

                formatted = _format_tool_result(tool_name, tool_args, tool_result)
                if formatted is not None:
                    return formatted

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(tool_result, default=str),
                }
            )

    return _message_html(
        "I couldn't finish that request. Please try rephrasing your question.",
        "OpenAI tool loop reached its limit.",
    )


def _finalize(message: str, result: dict, classification: IntentClassification) -> dict:
    result["question"] = message.strip()
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
            return _handle_operational_action("customer_summary_missing_id")
        return _clarifying_response()

    return _handle_operational_action(
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
            )
        return _finalize(message, result, classification)

    try:
        result = _chat_with_openai(message, history)
    except ValueError as exc:
        result = _message_html(str(exc), "OpenAI configuration error.")
    except Exception as exc:
        result = _message_html(
            f"Unable to process your request: {exc}",
            "OpenAI chat request failed.",
        )

    return _finalize(message, result, classification)
