from database import (
    search_customers,
    list_customers,
    get_accounts,
    get_loans,
    get_payments,
    get_collateral,
    get_overdue_customers,
    get_due_soon_customers,
    get_due_today_customers,
    get_due_tomorrow_customers,
    get_due_this_week_customers,
    get_missed_payments,
    get_high_risk_loans,
    get_collateral_at_risk,
    get_today_priorities,
    get_customer_count,
    get_loan_count,
    get_account_count,
    get_total_overdue_amount,
    get_total_portfolio_balance,
    get_portfolio_summary,
    resolve_customer_id,
    get_customer,
)
from intent import (
    is_reserved_customer_name,
    is_customer_summary_intent,
    extract_customer_id,
    payment_due_tool_for_phrase,
)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_customers",
            "description": (
                "Find customers by partial or full name. Do NOT use for payment due queries "
                "(due today, due tomorrow, due this week, due soon) or daily priorities — "
                "use the matching get_due_* or get_today_priorities tools instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_accounts",
            "description": (
                "Get checking/savings account balances for a customer. "
                "Use customer_id when provided — do not search by name if customer_id is known."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "customer_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_loans",
            "description": "Get loan balances, collateral values, and LTV for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "customer_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_payments",
            "description": "Get payment due amounts, paid amounts, and remaining balances.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "customer_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_collateral",
            "description": "Get collateral items (jewelry, vehicles, electronics) for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "customer_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overdue_customers",
            "description": (
                "Return a row-level list of overdue unpaid payments/customers, "
                "ordered by due date. Use for ordinary overdue list requests "
                "(for example, 'show overdue customers' or 'who is overdue'). "
                "Do NOT use for highest overdue amount, who owes the most, "
                "per-customer totals, or ranked overdue balances—use "
                "execute_safe_sql with aggregate SQL instead."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_due_soon_customers",
            "description": "List customers with payments due in the next 30 days.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_due_today_customers",
            "description": "List customers with unpaid payments due today (CURDATE()).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_due_tomorrow_customers",
            "description": "List customers with unpaid payments due tomorrow.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_due_this_week_customers",
            "description": "List customers with unpaid payments due through the end of this week.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_missed_payments",
            "description": "List customers who missed monthly payments.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_high_risk_loans",
            "description": (
                "List loans with high loan-to-value ratio (default >= 75%) across all customers. "
                "Do NOT use for single-customer summaries — use get_customer_loans instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ltv_threshold": {"type": "number", "description": "LTV % threshold, default 75"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_collateral_at_risk",
            "description": "List collateral items nearing forfeiture or tied to high-LTV loans.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_priorities",
            "description": (
                "Get today's combined priority dashboard: overdue, due-soon, and high-LTV follow-ups. "
                "Use ONLY for explicit daily planning questions such as who to call today, "
                "what to do today, morning follow-up lists, today's workload, or what to focus on today. "
                "Do NOT use for overdue-only, high-risk-only, collateral, or single-customer questions."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_customers",
            "description": "List customers on file when no specific search name is provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum customers to return, default 50"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_count",
            "description": "Return the total number of customers in the portfolio.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_loan_count",
            "description": "Return the total number of active loans in the portfolio.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_count",
            "description": "Return the total number of customer accounts on file.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_total_overdue_amount",
            "description": (
                "Return the portfolio-wide total overdue payment amount and "
                "count of overdue customers. Does not rank customers or return "
                "per-customer totals."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_total_portfolio_balance",
            "description": "Return total loan balances, account balances, and combined portfolio balance.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_summary",
            "description": (
                "Return a portfolio-wide business snapshot: customer, loan, and account counts, "
                "total balances, overdue exposure, due-soon count, and high-risk loan count."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

ALLOWED_TOOL_NAMES = frozenset(
    tool["function"]["name"] for tool in TOOL_DEFINITIONS
)

BANNED_TOOL_NAMES = frozenset({"the system", "system", "the_system"})


def _resolve_id(args):
    cid = args.get("customer_id")
    name = args.get("customer_name")
    if cid:
        return cid, None
    if name:
        if is_reserved_customer_name(name):
            return None, {
                "error": f"'{name}' is not a customer name.",
                "hint": "Use the daily priorities lookup for follow-up questions.",
            }
        result = resolve_customer_id(customer_name=name)
        if isinstance(result, list):
            if len(result) == 0:
                return None, {"error": f"No customer found matching '{name}'."}
            if len(result) > 1:
                return None, {"matches": result, "message": "Multiple customers found. Ask user to clarify."}
            return result[0]["customer_id"], None
        if result:
            return result["customer_id"], None
        return None, {"error": f"No customer found matching '{name}'."}
    return None, {"error": "Provide customer_id or customer_name."}


CUSTOMER_SUMMARY_TOOLS = (
    "get_customer_accounts",
    "get_customer_loans",
    "get_customer_payments",
    "get_customer_collateral",
)


def gather_customer_summary(customer_id: int) -> dict:
    customer = get_customer(customer_id)
    if not customer:
        return {"error": f"No customer found with ID {customer_id}."}

    args = {"customer_id": customer_id}
    tools_used = []

    summary = {"customer": customer}
    for tool_name in CUSTOMER_SUMMARY_TOOLS:
        result = execute_tool(tool_name, args)
        key = tool_name.replace("get_customer_", "")
        summary[key] = result
        tools_used.append({"tool": tool_name, "args": args})

    return {"summary": summary, "tools_used": tools_used}


def execute_tool(name: str, arguments: dict, *, allow_high_risk: bool = True):
    if name not in ALLOWED_TOOL_NAMES:
        return {"error": f"Unknown tool: {name}"}

    args = arguments or {}

    if name == "get_high_risk_loans" and not allow_high_risk:
        return {"error": "High-risk loan list is not used for single-customer summaries."}

    if name == "search_customers" and args.get("customer_id"):
        return {"error": "Do not search by name when customer_id is provided."}

    if name == "search_customers":
        query_name = str(args.get("name") or "").strip()
        if not query_name:
            return list_customers(int(args.get("limit", 50)))
        payment_tool = payment_due_tool_for_phrase(query_name)
        if payment_tool:
            return execute_tool(payment_tool, {})
        if is_reserved_customer_name(query_name):
            return get_today_priorities()
        return search_customers(query_name)

    if name == "list_customers":
        return list_customers(int(args.get("limit", 50)))

    if name in ("get_customer_accounts", "get_customer_loans", "get_customer_payments", "get_customer_collateral"):
        customer_id, err = _resolve_id(args)
        if err:
            return err
        fn_map = {
            "get_customer_accounts": get_accounts,
            "get_customer_loans": get_loans,
            "get_customer_payments": get_payments,
            "get_customer_collateral": get_collateral,
        }
        return fn_map[name](customer_id)

    dispatch = {
        "get_overdue_customers": get_overdue_customers,
        "get_due_soon_customers": get_due_soon_customers,
        "get_due_today_customers": get_due_today_customers,
        "get_due_tomorrow_customers": get_due_tomorrow_customers,
        "get_due_this_week_customers": get_due_this_week_customers,
        "get_missed_payments": get_missed_payments,
        "get_high_risk_loans": lambda: get_high_risk_loans(args.get("ltv_threshold", 75.0)),
        "get_collateral_at_risk": get_collateral_at_risk,
        "get_today_priorities": get_today_priorities,
        "get_customer_count": get_customer_count,
        "get_loan_count": get_loan_count,
        "get_account_count": get_account_count,
        "get_total_overdue_amount": get_total_overdue_amount,
        "get_total_portfolio_balance": get_total_portfolio_balance,
        "get_portfolio_summary": get_portfolio_summary,
    }

    if name in dispatch:
        return dispatch[name]()

    return {"error": f"Unknown tool: {name}"}
