import html
import re
from datetime import date, datetime

from database import (
    get_collateral_at_risk,
    get_due_soon_customers,
    get_high_risk_loans,
    get_overdue_customers,
    get_today_priorities,
)


def format_money(amount) -> str:
    return f"${float(amount):,.2f}"


def format_ltv(value) -> str:
    return f"{float(value):.2f}%"


def format_phone_paren(phone) -> str:
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return str(phone)


def parse_date(date_value) -> date | None:
    if not date_value:
        return None
    if isinstance(date_value, date) and not isinstance(date_value, datetime):
        return date_value
    if isinstance(date_value, datetime):
        return date_value.date()
    if isinstance(date_value, str):
        try:
            return datetime.fromisoformat(date_value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def format_date_short(date_value) -> str:
    parsed = parse_date(date_value)
    if not parsed:
        return "N/A"
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def title_case_item(text: str) -> str:
    return text.title() if text else text


def html_response(reply: str, history_text: str, tools_used: list | None = None) -> dict:
    payload = {"reply": reply, "format": "html", "history_text": history_text}
    if tools_used is not None:
        payload["tools_used"] = tools_used
    return payload


def text_response(reply: str, history_text: str, tools_used: list | None = None) -> dict:
    payload = {"reply": reply, "format": "text", "history_text": history_text}
    if tools_used is not None:
        payload["tools_used"] = tools_used
    return payload


def _esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _sort_by_due_date(items: list) -> list:
    return sorted(items, key=lambda item: parse_date(item.get("due_date")) or date.max)


def _item_key(item: dict) -> tuple:
    return (item.get("customer_id"), item.get("full_name"), item.get("loan_type"))


def _display_customer_name(item: dict) -> str:
    name = str(item.get("full_name") or "").strip()
    if name and name.lower() not in {"unknown", "n/a", "none", "null"}:
        return name
    customer_id = item.get("customer_id")
    if customer_id is not None:
        return f"Customer #{customer_id}"
    return "Customer on file"


def _field(label: str, value: str) -> str:
    return (
        f'<div class="card-field">'
        f'<span class="field-label">{_esc(label)}</span>'
        f'<span class="field-value">{value}</span>'
        f"</div>"
    )


def _customer_card(
    name: str,
    loan: str,
    amount_due: str,
    due_date: str,
    recommended_action: str,
    badge: str = "",
    badge_class: str = "badge-neutral",
) -> str:
    badge_html = f'<span class="badge {badge_class}">{_esc(badge)}</span>' if badge else ""
    return (
        f'<div class="customer-card">'
        f'<div class="card-header">'
        f'<div class="customer-name">{_esc(name)}</div>'
        f"{badge_html}"
        f"</div>"
        f'{_field("Loan", _esc(loan))}'
        f'{_field("Amount Due", amount_due)}'
        f'{_field("Due Date", _esc(due_date))}'
        f'<div class="card-action">'
        f'<span class="field-label">Recommended Action</span>'
        f'<span class="action-text">{_esc(recommended_action)}</span>'
        f"</div>"
        f"</div>"
    )


def _follow_up_card(item: dict, badge: str, badge_class: str, action: str) -> str:
    remaining = item.get("remaining_due") or item.get("missed_amount")
    amount = format_money(remaining) if remaining is not None else "N/A"
    due = item.get("due_date") or item.get("next_due_date")
    return _customer_card(
        name=_display_customer_name(item),
        loan=str(item.get("loan_type") or "Loan"),
        amount_due=amount,
        due_date=format_date_short(due),
        recommended_action=action,
        badge=badge,
        badge_class=badge_class,
    )


def _high_risk_card(item: dict, action: str) -> str:
    balance = item.get("current_balance")
    amount = format_money(balance) if balance is not None else format_ltv(item.get("ltv_percent", 0))
    return _customer_card(
        name=_display_customer_name(item),
        loan=str(item.get("loan_type") or "Loan"),
        amount_due=amount,
        due_date=format_date_short(item.get("next_due_date")),
        recommended_action=action,
        badge="High LTV",
        badge_class="badge-risk",
    )


def _collateral_card(item: dict, action: str) -> str:
    collateral = title_case_item(
        str(item.get("item_description") or item.get("item_type") or "Collateral")
    )
    value = item.get("appraised_value")
    amount = format_money(value) if value is not None else "N/A"
    return _customer_card(
        name=_display_customer_name(item),
        loan=str(item.get("loan_type") or collateral),
        amount_due=amount,
        due_date=format_date_short(item.get("forfeiture_date")),
        recommended_action=action,
        badge="At Risk",
        badge_class="badge-collateral",
    )


def _section(title: str, badge_class: str, cards_html: str) -> str:
    return (
        f'<div class="response-section">'
        f'<div class="section-title"><span class="badge {badge_class}">{_esc(title)}</span></div>'
        f'<div class="card-grid">{cards_html}</div>'
        f"</div>"
    )


def _action_banner(action: str, detail: str) -> str:
    return (
        f'<div class="action-banner">'
        f'<div class="action-banner-title">Recommended Next Action</div>'
        f'<div class="action-banner-text">{_esc(action)}</div>'
        f'<div class="action-banner-detail">{_esc(detail)}</div>'
        f"</div>"
    )


def _response_page(title: str, body: str) -> str:
    return (
        f'<div class="copilot-response">'
        f'<div class="response-title">{_esc(title)}</div>'
        f"{body}"
        f"</div>"
    )


def _empty_message(text: str) -> str:
    return f'<div class="empty-message">{_esc(text)}</div>'


def _recommended_action_parts_for_today(data: dict) -> tuple[str, str]:
    overdue = _sort_by_due_date(data.get("overdue") or [])
    if overdue:
        name = _display_customer_name(overdue[0])
        return (
            f"Contact {name} first.",
            "This is the oldest overdue payment in the portfolio.",
        )

    due_soon = _sort_by_due_date(data.get("due_soon") or [])
    if due_soon:
        name = _display_customer_name(due_soon[0])
        due = format_date_short(due_soon[0].get("due_date"))
        return (
            f"Contact {name} first.",
            f"This payment is due soonest, on {due}.",
        )

    high_risk = data.get("high_risk") or []
    if high_risk:
        name = _display_customer_name(high_risk[0])
        ltv = format_ltv(high_risk[0].get("ltv_percent", 0))
        return (
            f"Review {name} first.",
            f"Highest LTV in the portfolio at {ltv}.",
        )

    return (
        "No immediate follow-up needed.",
        "All clear based on current records.",
    )


def _dedupe_priority_sections(data: dict) -> tuple[list, list, list]:
    seen = set()
    overdue = _sort_by_due_date(data.get("overdue") or [])
    for item in overdue:
        seen.add(_item_key(item))

    due_soon_filtered = []
    for item in _sort_by_due_date(data.get("due_soon") or []):
        key = _item_key(item)
        if key not in seen:
            due_soon_filtered.append(item)
            seen.add(key)

    high_risk_filtered = []
    for item in data.get("high_risk") or []:
        key = _item_key(item)
        if key not in seen:
            high_risk_filtered.append(item)
            seen.add(key)

    return overdue, due_soon_filtered, high_risk_filtered


def _overdue_action(item: dict) -> str:
    remaining = item.get("remaining_due") or item.get("missed_amount")
    due = format_date_short(item.get("due_date"))
    if remaining is not None:
        return f"Contact about {format_money(remaining)} overdue since {due}."
    return f"Contact about payment overdue since {due}."


def _due_soon_action(item: dict) -> str:
    due = format_date_short(item.get("due_date"))
    remaining = item.get("remaining_due")
    if remaining is not None:
        return f"Follow up on {format_money(remaining)} due {due}."
    return f"Follow up before {due}."


def build_today_priorities_dashboard(data: dict) -> str:
    overdue, due_soon_filtered, high_risk_filtered = _dedupe_priority_sections(data)
    parts = []

    if not overdue and not due_soon_filtered and not high_risk_filtered:
        return _response_page(
            "Today's Priorities",
            _empty_message(
                "All clear for today. No overdue accounts, due-soon payments, "
                "or high-LTV loans need follow-up."
            ),
        )

    if overdue:
        cards = "".join(
            _follow_up_card(item, "Overdue", "badge-urgent", _overdue_action(item))
            for item in overdue
        )
        parts.append(_section("Immediate Follow-Up", "badge-urgent", cards))

    if due_soon_filtered:
        cards = "".join(
            _follow_up_card(item, "Due Soon", "badge-soon", _due_soon_action(item))
            for item in due_soon_filtered
        )
        parts.append(_section("Coming Due", "badge-soon", cards))

    if high_risk_filtered:
        cards = "".join(
            _high_risk_card(
                item,
                f"Review LTV {format_ltv(item.get('ltv_percent', 0))} with customer.",
            )
            for item in high_risk_filtered
        )
        parts.append(_section("High Risk", "badge-risk", cards))

    action, detail = _recommended_action_parts_for_today(data)
    parts.append(_action_banner(action, detail))
    return _response_page("Today's Priorities", "".join(parts))


def build_today_priorities_text(data: dict) -> str:
    return build_today_priorities_dashboard(data)


def build_overdue_customers_text(items: list) -> str:
    if not items:
        return _response_page("Overdue Customers", _empty_message("No overdue customers found."))

    sorted_items = _sort_by_due_date(items)
    cards = "".join(
        _follow_up_card(item, "Overdue", "badge-urgent", _overdue_action(item))
        for item in sorted_items
    )
    oldest = sorted_items[0]
    body = (
        _section("Overdue Accounts", "badge-urgent", cards)
        + _action_banner(
            f"Contact {_display_customer_name(oldest)} first.",
            "Oldest overdue payment in the portfolio.",
        )
    )
    return _response_page("Overdue Customers", body)


def build_due_soon_customers_text(items: list) -> str:
    if not items:
        return _response_page("Due Soon", _empty_message("No customers due soon found."))

    sorted_items = _sort_by_due_date(items)
    cards = "".join(
        _follow_up_card(item, "Due Soon", "badge-soon", _due_soon_action(item))
        for item in sorted_items
    )
    first = sorted_items[0]
    body = (
        _section("Coming Due", "badge-soon", cards)
        + _action_banner(
            f"Contact {_display_customer_name(first)} first.",
            f"Payment due soonest on {format_date_short(first.get('due_date'))}.",
        )
    )
    return _response_page("Due Soon", body)


def build_high_risk_loans_text(items: list) -> str:
    if not items:
        return _response_page("High Risk Loans", _empty_message("No high-LTV loans found."))

    sorted_items = sorted(items, key=lambda x: float(x.get("ltv_percent") or 0), reverse=True)
    cards = "".join(
        _high_risk_card(
            item,
            f"Review LTV {format_ltv(item.get('ltv_percent', 0))} with customer.",
        )
        for item in sorted_items
    )
    top = sorted_items[0]
    body = (
        _section("High LTV Loans", "badge-risk", cards)
        + _action_banner(
            f"Review {_display_customer_name(top)} first.",
            f"Highest LTV at {format_ltv(top.get('ltv_percent', 0))}.",
        )
    )
    return _response_page("High Risk Loans", body)


def build_collateral_at_risk_text(items: list) -> str:
    if not items:
        return _response_page("Collateral at Risk", _empty_message("No collateral at risk found."))

    sorted_items = sorted(
        items,
        key=lambda x: parse_date(x.get("forfeiture_date")) or date.max,
    )
    cards = "".join(
        _collateral_card(
            item,
            f"Follow up before forfeiture on {format_date_short(item.get('forfeiture_date'))}.",
        )
        for item in sorted_items
    )
    first = sorted_items[0]
    body = (
        _section("Collateral at Risk", "badge-collateral", cards)
        + _action_banner(
            f"Follow up with {_display_customer_name(first)} first.",
            f"Nearest forfeiture date: {format_date_short(first.get('forfeiture_date'))}.",
        )
    )
    return _response_page("Collateral at Risk", body)


def build_missed_payments_text(items: list) -> str:
    if not items:
        return _response_page("Missed Payments", _empty_message("No missed payments found."))

    sorted_items = _sort_by_due_date(items)
    cards = "".join(
        _follow_up_card(item, "Missed", "badge-urgent", _overdue_action(item))
        for item in sorted_items
    )
    oldest = sorted_items[0]
    body = (
        _section("Missed Payments", "badge-urgent", cards)
        + _action_banner(
            f"Contact {_display_customer_name(oldest)} first.",
            "Oldest missed payment in the portfolio.",
        )
    )
    return _response_page("Missed Payments", body)


def _account_card(account: dict) -> str:
    return _customer_card(
        name=str(account.get("account_type") or "Account"),
        loan=str(account.get("status") or "Account"),
        amount_due=format_money(account.get("balance", 0)),
        due_date="N/A",
        recommended_action="Review account balance with customer.",
        badge="Account",
        badge_class="badge-neutral",
    )


def _loan_detail_card(loan: dict) -> str:
    balance = loan.get("current_balance")
    ltv = loan.get("ltv_percent")
    action = f"Review balance of {format_money(balance)}." if balance is not None else "Review loan status."
    if ltv is not None:
        action = f"Review LTV {format_ltv(ltv)} and outstanding balance."
    return _customer_card(
        name=str(loan.get("loan_type") or "Loan"),
        loan=str(loan.get("loan_type") or "Loan"),
        amount_due=format_money(balance) if balance is not None else "N/A",
        due_date=format_date_short(loan.get("next_due_date")),
        recommended_action=action,
        badge="Loan",
        badge_class="badge-neutral",
    )


def build_customer_summary_text(data: dict) -> str:
    customer = data.get("customer") or {}
    name = _display_customer_name(customer) if customer else "Customer"
    accounts = data.get("accounts") or []
    loans = data.get("loans") or []
    payments = data.get("payments") or []
    collateral = data.get("collateral") or []
    today = date.today()
    parts = []

    meta = f'<div class="summary-meta">Customer ID {_esc(customer.get("customer_id", "N/A"))}'
    if customer.get("phone"):
        meta += f" · {_esc(format_phone_paren(customer['phone']))}"
    if customer.get("email"):
        meta += f" · {_esc(customer['email'])}"
    meta += "</div>"
    parts.append(meta)

    if accounts:
        cards = "".join(_account_card(a) for a in accounts)
        parts.append(_section("Accounts", "badge-neutral", cards))

    if loans:
        cards = "".join(_loan_detail_card(loan) for loan in loans)
        parts.append(_section("Loans", "badge-neutral", cards))

    if payments:
        cards = ""
        for payment in payments:
            remaining = payment.get("remaining_due")
            cards += _customer_card(
                name=name,
                loan="Payment",
                amount_due=format_money(remaining) if remaining is not None else "N/A",
                due_date=format_date_short(payment.get("due_date")),
                recommended_action="Review payment status with customer.",
                badge="Payment",
                badge_class="badge-soon",
            )
        parts.append(_section("Payments", "badge-soon", cards))

    overdue_note = None
    for payment in payments:
        remaining = payment.get("remaining_due")
        due = parse_date(payment.get("due_date"))
        if remaining and float(remaining) > 0 and due and due < today:
            overdue_note = (
                f"Follow up on {format_money(remaining)} overdue since "
                f"{format_date_short(due)}."
            )
            break

    if overdue_note:
        parts.append(_action_banner(f"Contact {name}.", overdue_note))
    else:
        parts.append(_action_banner("No immediate follow-up required.", "Current records are up to date."))

    if collateral:
        cards = "".join(
            _collateral_card(
                item,
                f"Verify status: {item.get('item_status') or 'review'}.",
            )
            for item in collateral
        )
        parts.append(_section("Collateral", "badge-collateral", cards))

    if not accounts and not loans and not payments and not collateral:
        parts.append(_empty_message("No records on file for this customer."))

    return _response_page(f"Customer Summary: {name}", "".join(parts))


def build_customer_accounts_text(customer: dict, accounts: list) -> str:
    name = _display_customer_name(customer)
    if not accounts:
        return _response_page(
            f"Accounts: {name}",
            _empty_message("No accounts on file for this customer."),
        )

    cards = "".join(_account_card(a) for a in accounts)
    total = sum(float(a.get("balance") or 0) for a in accounts)
    body = (
        _section("Account Balances", "badge-neutral", cards)
        + _action_banner(
            f"Total balance across accounts: {format_money(total)}.",
            f"Review balances with {name}.",
        )
    )
    return _response_page(f"Accounts: {name}", body)


def build_customer_loans_text(customer: dict, loans: list) -> str:
    name = _display_customer_name(customer)
    if not loans:
        return _response_page(
            f"Loans: {name}",
            _empty_message("No loans on file for this customer."),
        )

    cards = "".join(_loan_detail_card(loan) for loan in loans)
    total = sum(float(loan.get("current_balance") or 0) for loan in loans)
    body = (
        _section("Loan Details", "badge-neutral", cards)
        + _action_banner(
            f"Total outstanding: {format_money(total)}." if total else "Review loan status.",
            f"Discuss loan details with {name}.",
        )
    )
    return _response_page(f"Loans: {name}", body)


OPERATIONAL_HANDLERS = {
    "today_priorities": lambda: build_today_priorities_dashboard(get_today_priorities()),
    "overdue_customers": lambda: build_overdue_customers_text(get_overdue_customers()),
    "due_soon_customers": lambda: build_due_soon_customers_text(get_due_soon_customers()),
    "missed_payments": lambda: build_missed_payments_text(get_overdue_customers()),
    "high_risk_loans": lambda: build_high_risk_loans_text(get_high_risk_loans()),
    "collateral_at_risk": lambda: build_collateral_at_risk_text(get_collateral_at_risk()),
}

OPERATIONAL_HISTORY = {
    "today_priorities": "Provided today's follow-up plan.",
    "overdue_customers": "Provided overdue customer list.",
    "due_soon_customers": "Provided due-soon customer list.",
    "missed_payments": "Provided missed payment list.",
    "high_risk_loans": "Provided high-LTV loan list.",
    "collateral_at_risk": "Provided collateral-at-risk list.",
}

OPERATIONAL_TOOLS = {
    "today_priorities": "get_today_priorities",
    "overdue_customers": "get_overdue_customers",
    "due_soon_customers": "get_due_soon_customers",
    "missed_payments": "get_missed_payments",
    "high_risk_loans": "get_high_risk_loans",
    "collateral_at_risk": "get_collateral_at_risk",
}


def build_today_priorities_response(data: dict | None = None) -> dict:
    payload = data if data is not None else get_today_priorities()
    return html_response(
        build_today_priorities_dashboard(payload),
        OPERATIONAL_HISTORY["today_priorities"],
        [{"tool": "get_today_priorities", "args": {}}],
    )
