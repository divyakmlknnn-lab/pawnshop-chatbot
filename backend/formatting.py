import html
import re
from datetime import date, datetime

from query_trace import extract_rows
from database import (
    get_collateral_at_risk,
    get_due_soon_customers,
    get_due_today_customers,
    get_due_tomorrow_customers,
    get_due_this_week_customers,
    get_high_risk_loans,
    get_overdue_customers,
    get_today_priorities,
    get_customer_count,
    get_loan_count,
    get_account_count,
    get_total_overdue_amount,
    get_total_portfolio_balance,
    get_portfolio_summary,
    list_customers,
    search_customers,
    get_overdue_account_count,
    get_next_scheduled_payment,
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


def html_response(reply: str, history_text: str, tools_used: list | None = None, query_details: dict | None = None) -> dict:
    payload = {"reply": reply, "format": "html", "history_text": history_text}
    if tools_used is not None:
        payload["tools_used"] = tools_used
    if query_details is not None:
        payload["query_details"] = query_details
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


def _response_page(title: str, body: str) -> str:
    return (
        f'<div class="copilot-response">'
        f'<div class="response-title">{_esc(title)}</div>'
        f"{body}"
        f"</div>"
    )


def _assistant_response(body: str) -> str:
    return f'<div class="copilot-response">{body}</div>'


def wrap_gemini_fallback_reply(reply_html: str) -> str:
    inner = (reply_html or "").strip()
    wrapper_open = '<div class="copilot-response">'
    if inner.startswith(wrapper_open) and inner.endswith("</div>"):
        inner = inner[len(wrapper_open): inner.rfind("</div>")].strip()
    return (
        f'{wrapper_open}'
        f'<p class="business-summary gemini-unavailable-intro">Gemini is temporarily unavailable.</p>'
        f'<p class="business-summary">Based on current portfolio data:</p>'
        f"{inner}"
        f'<p class="business-summary fallback-footnote">Showing database results below.</p>'
        f"</div>"
    )


def build_gemini_unavailable_only_reply() -> str:
    return _assistant_response(
        '<p class="business-summary gemini-unavailable-intro">Gemini is temporarily unavailable.</p>'
        "<p class=\"business-summary\">Based on current portfolio data, no matching database query "
        "could be run for this question.</p>"
        "<p class=\"business-summary fallback-footnote\">Try an operational question such as "
        "&quot;Who is overdue?&quot; or &quot;Show today&apos;s priorities.&quot;</p>"
    )


def _business_summary(text: str) -> str:
    return f'<p class="business-summary">{_esc(text)}</p>'


def _payment_amount(item: dict):
    return item.get("remaining_due") if item.get("remaining_due") is not None else item.get("missed_amount")


def _payment_due_date(item: dict):
    return item.get("due_date") or item.get("next_due_date")


def _action_banner(
    action: str,
    reason: str,
    *,
    remaining_due=None,
    due_date=None,
    ltv_percent=None,
    forfeiture_date=None,
) -> str:
    metric_fields = []
    if remaining_due is not None:
        metric_fields.append(_field("Remaining Due", format_money(remaining_due)))
    if due_date is not None:
        metric_fields.append(_field("Due Date", _esc(format_date_short(due_date))))
    if ltv_percent is not None:
        metric_fields.append(_field("LTV", _esc(format_ltv(ltv_percent))))
    if forfeiture_date is not None:
        metric_fields.append(_field("Forfeiture Date", _esc(format_date_short(forfeiture_date))))

    metrics_html = ""
    if metric_fields:
        metrics_html = f'<div class="action-banner-metrics">{"".join(metric_fields)}</div>'

    return (
        f'<div class="action-banner">'
        f'<div class="action-banner-text">{_esc(action)}</div>'
        f'<div class="action-banner-detail">'
        f'<span class="action-reason-label">Reason</span> {_esc(reason)}'
        f"</div>"
        f"{metrics_html}"
        f"</div>"
    )


def _empty_message(text: str) -> str:
    return f'<div class="empty-message">{_esc(text)}</div>'


def _stat_card(label: str, value: str, detail: str = "") -> str:
    detail_html = (
        f'<div class="card-action"><span class="action-text">{_esc(detail)}</span></div>'
        if detail
        else ""
    )
    return (
        f'<div class="customer-card">'
        f'<div class="card-header"><div class="customer-name">{_esc(label)}</div></div>'
        f'{_field("Value", f"<strong>{value}</strong>")}'
        f"{detail_html}"
        f"</div>"
    )


def _customer_directory_card(customer: dict) -> str:
    phone = format_phone_paren(customer.get("phone"))
    email = str(customer.get("email") or "N/A")
    return (
        f'<div class="customer-card">'
        f'<div class="card-header">'
        f'<div class="customer-name">{_esc(_display_customer_name(customer))}</div>'
        f'<span class="badge badge-neutral">ID {_esc(customer.get("customer_id"))}</span>'
        f"</div>"
        f'{_field("Phone", _esc(phone))}'
        f'{_field("Email", _esc(email))}'
        f"</div>"
    )


def _metric_count(data, key: str = "count") -> int:
    if data is None:
        return 0
    rows = extract_rows(data)
    if rows:
        return int(rows[0].get(key) or 0)
    if isinstance(data, dict):
        return int(data.get(key) or 0)
    return 0


def _normalize_priority_data(data: dict) -> dict:
    return {
        "overdue": extract_rows(data.get("overdue")),
        "due_soon": extract_rows(data.get("due_soon")),
        "high_risk": extract_rows(data.get("high_risk"))[:5],
    }


def build_customer_count_text(data: dict | None = None) -> str:
    payload = data if data is not None else get_customer_count()
    count = _metric_count(payload)
    body = (
        _business_summary(f"There are {count} customers on file.")
        + _action_banner(
            "Use portfolio summary for a full snapshot.",
            "Customer count reflects active customer records.",
        )
    )
    return _assistant_response(body)


def build_loan_count_text(data: dict | None = None) -> str:
    payload = data if data is not None else get_loan_count()
    count = _metric_count(payload)
    body = (
        _business_summary(f"There are {count} active loans in the portfolio.")
        + _action_banner(
            "Review high-risk loans if LTV exposure is a concern.",
            "Loan count reflects all loan records on file.",
        )
    )
    return _assistant_response(body)


def build_account_count_text(data: dict | None = None) -> str:
    payload = data if data is not None else get_account_count()
    count = _metric_count(payload)
    body = (
        _business_summary(f"There are {count} customer accounts on file.")
        + _action_banner(
            "Review account balances for liquidity planning.",
            "Includes checking and savings accounts.",
        )
    )
    return _assistant_response(body)


def build_total_overdue_text(data: dict | None = None) -> str:
    payload = data if data is not None else get_total_overdue_amount()
    total = format_money(payload.get("total_overdue") or 0)
    overdue_customers = int(payload.get("overdue_customer_count") or 0)
    label = "customer" if overdue_customers == 1 else "customers"
    body = (
        _business_summary(
            f"{total} is overdue across {overdue_customers} {label}."
        )
        + _action_banner(
            "Review overdue accounts first.",
            f"{total} is outstanding across overdue payments.",
        )
    )
    return _assistant_response(body)


def build_portfolio_balance_text(data: dict | None = None) -> str:
    payload = data if data is not None else get_total_portfolio_balance()
    loan_balance = format_money(payload.get("loan_balance") or 0)
    account_balance = format_money(payload.get("account_balance") or 0)
    total_balance = format_money(payload.get("total_balance") or 0)
    body = (
        _business_summary(
            f"Combined portfolio balance is {total_balance} "
            f"({loan_balance} in loans and {account_balance} in accounts)."
        )
        + _action_banner(
            "Use portfolio summary for operational counts.",
            "Balances reflect live loan and account records.",
        )
    )
    return _assistant_response(body)


def build_portfolio_summary_text(data: dict | None = None) -> str:
    payload = data if data is not None else get_portfolio_summary()
    body = (
        _business_summary(
            "The portfolio includes "
            f"{payload.get('customer_count') or 0} customers, "
            f"{payload.get('loan_count') or 0} loans, and "
            f"{payload.get('account_count') or 0} accounts with "
            f"{format_money(payload.get('total_balance') or 0)} in combined balances."
        )
        + _action_banner(
            "Use today's priorities for follow-up sequencing.",
            f"{format_money(payload.get('total_overdue') or 0)} is overdue across "
            f"{payload.get('overdue_customer_count') or 0} customers.",
        )
    )
    return _assistant_response(body)


def build_customer_search_text(customers, query: str = "") -> str:
    rows = extract_rows(customers)
    if not rows:
        message = "No matching customers found."
        if query:
            message = f"No customers found matching '{query}'."
        return _assistant_response(
            _business_summary(message)
            + _action_banner(
                "Refine the customer name or account number and try again.",
                "No customer records matched the query.",
            )
        )

    detail = f"Showing {len(rows)} match(es)."
    if query:
        detail = f"Showing {len(rows)} match(es) for '{query}'."
    body = (
        _business_summary(f"Found {len(rows)} matching customer record(s).")
        + _action_banner("Select a customer for details.", detail)
    )
    return _assistant_response(body)


def _recommended_action_parts_for_today(data: dict) -> tuple[str, str]:
    normalized = _normalize_priority_data(data)
    overdue = _sort_by_due_date(normalized.get("overdue") or [])
    if overdue:
        name = _display_customer_name(overdue[0])
        return (
            f"Call {name} first.",
            "Oldest overdue payment in today's queue.",
        )

    due_soon = _sort_by_due_date(normalized.get("due_soon") or [])
    if due_soon:
        name = _display_customer_name(due_soon[0])
        due = format_date_short(due_soon[0].get("due_date"))
        return (
            f"Call {name} first.",
            f"This payment is due soonest, on {due}.",
        )

    high_risk = normalized.get("high_risk") or []
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


def _today_priorities_summary(overdue: list, due_soon: list, high_risk: list) -> str:
    messages = []
    if overdue:
        count = len(overdue)
        label = "overdue account" if count == 1 else "overdue accounts"
        messages.append(f"{count} {label} requiring follow-up today")
    if due_soon:
        count = len(due_soon)
        label = "payment due soon" if count == 1 else "payments due soon"
        messages.append(f"{count} {label}")
    if high_risk:
        count = len(high_risk)
        label = "high-risk loan" if count == 1 else "high-risk loans"
        messages.append(f"{count} {label} to review")
    if not messages:
        return "All clear for today based on current records."
    return "There are " + ", ".join(messages) + "."


def _first_priority_item(overdue: list, due_soon: list, high_risk: list) -> dict | None:
    if overdue:
        return _sort_by_due_date(overdue)[0]
    if due_soon:
        return _sort_by_due_date(due_soon)[0]
    if high_risk:
        return high_risk[0]
    return None


def _dedupe_priority_sections(data: dict) -> tuple[list, list, list]:
    normalized = _normalize_priority_data(data)
    seen = set()
    overdue = _sort_by_due_date(normalized.get("overdue") or [])
    for item in overdue:
        seen.add(_item_key(item))

    due_soon_filtered = []
    for item in _sort_by_due_date(normalized.get("due_soon") or []):
        key = _item_key(item)
        if key not in seen:
            due_soon_filtered.append(item)
            seen.add(key)

    high_risk_filtered = []
    for item in normalized.get("high_risk") or []:
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
    normalized = _normalize_priority_data(data)
    overdue, due_soon_filtered, high_risk_filtered = _dedupe_priority_sections(normalized)

    if not overdue and not due_soon_filtered and not high_risk_filtered:
        return _assistant_response(
            _business_summary(
                "All clear for today. No overdue accounts, due-soon payments, "
                "or high-LTV loans need follow-up."
            )
            + _action_banner(
                "No immediate follow-up needed.",
                "All clear based on current records.",
            )
        )

    action, reason = _recommended_action_parts_for_today(normalized)
    first_item = _first_priority_item(overdue, due_soon_filtered, high_risk_filtered)
    banner_kwargs = {}
    if first_item:
        if overdue or due_soon_filtered:
            banner_kwargs["remaining_due"] = _payment_amount(first_item)
            banner_kwargs["due_date"] = _payment_due_date(first_item)
        else:
            banner_kwargs["ltv_percent"] = first_item.get("ltv_percent")
            banner_kwargs["due_date"] = _payment_due_date(first_item)

    body = (
        _business_summary(_today_priorities_summary(overdue, due_soon_filtered, high_risk_filtered))
        + _action_banner(action, reason, **banner_kwargs)
    )
    return _assistant_response(body)


def build_today_priorities_text(data: dict) -> str:
    return build_today_priorities_dashboard(data)


def build_overdue_customers_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _assistant_response(
            _business_summary("No overdue customers found.")
            + _action_banner(
                "No overdue follow-up needed.",
                "All customer payments are current.",
            )
        )

    sorted_items = _sort_by_due_date(rows)
    oldest = sorted_items[0]
    count = len(sorted_items)
    label = "account" if count == 1 else "accounts"
    body = (
        _business_summary(f"There are {count} overdue {label} requiring follow-up.")
        + _action_banner(
            f"Call {_display_customer_name(oldest)} first.",
            "Oldest overdue payment in the portfolio.",
            remaining_due=_payment_amount(oldest),
            due_date=oldest.get("due_date"),
        )
    )
    return _assistant_response(body)


def _overdue_priority_summary() -> str:
    overdue_count = get_overdue_account_count()
    if overdue_count == 1:
        return "Current priority: 1 overdue account requires follow-up."
    return f"Current priority: {overdue_count} overdue accounts require follow-up."


def _payment_due_empty_response(empty_message: str, empty_reason: str) -> str:
    priority_line = _overdue_priority_summary()
    return _assistant_response(
        _business_summary(empty_message)
        + _business_summary(priority_line)
        + _action_banner(
            "Review overdue accounts first.",
            empty_reason,
        )
    )


def _payment_due_success_response(rows: list, window_label: str) -> str:
    sorted_items = _sort_by_due_date(rows)
    first = sorted_items[0]
    count = len(sorted_items)
    label = "customer payment" if count == 1 else "customer payments"
    return _assistant_response(
        _business_summary(f"There are {count} {label} {window_label}.")
        + _action_banner(
            f"Call {_display_customer_name(first)} first.",
            f"Payment due on {format_date_short(first.get('due_date'))}.",
            remaining_due=_payment_amount(first),
            due_date=first.get("due_date"),
        )
    )


def build_due_today_customers_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _payment_due_empty_response(
            "No unpaid customer payments are due today.",
            "No payments are scheduled for today.",
        )
    return _payment_due_success_response(rows, "due today")


def build_due_tomorrow_customers_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _payment_due_empty_response(
            "No unpaid customer payments are due tomorrow.",
            "No payments are scheduled for tomorrow.",
        )
    return _payment_due_success_response(rows, "due tomorrow")


def build_due_this_week_customers_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _payment_due_empty_response(
            "No unpaid customer payments are due this week.",
            "No payments are scheduled for the remainder of this week.",
        )
    return _payment_due_success_response(rows, "due this week")


def _due_soon_empty_status() -> str:
    overdue_count = get_overdue_account_count()
    next_payment = get_next_scheduled_payment()

    if overdue_count == 1:
        overdue_line = "1 overdue account requires attention."
    else:
        overdue_line = f"{overdue_count} overdue accounts require attention."

    status_items = [overdue_line]
    if next_payment:
        name = _display_customer_name(next_payment)
        due = format_date_short(next_payment.get("due_date"))
        remaining = float(next_payment.get("remaining_due") or 0)
        payment_status = "already paid" if remaining <= 0 else "payment pending"
        status_items.append(
            f"Next upcoming scheduled payment: {name} on {due} ({payment_status})."
        )
    else:
        status_items.append("No upcoming scheduled payments on file.")

    bullets = "".join(f"<li>{_esc(item)}</li>" for item in status_items)
    return (
        _business_summary("No unpaid customer payments are due within the next 30 days.")
        + f'<p class="portfolio-status-intro"><strong>{_esc("Current portfolio status:")}</strong></p>'
        f'<ul class="portfolio-status-list">{bullets}</ul>'
    )


def build_due_soon_customers_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _assistant_response(
            _due_soon_empty_status()
            + _action_banner(
                "Review overdue accounts first.",
                "No due-soon payments are scheduled in the next 30 days.",
            )
        )

    sorted_items = _sort_by_due_date(rows)
    first = sorted_items[0]
    count = len(sorted_items)
    label = "customer payment" if count == 1 else "customer payments"
    body = (
        _business_summary(f"There are {count} {label} due within the next 30 days.")
        + _action_banner(
            f"Call {_display_customer_name(first)} first.",
            f"Payment due soonest on {format_date_short(first.get('due_date'))}.",
            remaining_due=_payment_amount(first),
            due_date=first.get("due_date"),
        )
    )
    return _assistant_response(body)


def build_high_risk_loans_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _assistant_response(
            _business_summary("No high-risk loans currently require review.")
            + _action_banner(
                "Portfolio LTV levels are within normal review thresholds.",
                "All loans are below the high-LTV threshold.",
            )
        )

    sorted_items = sorted(rows, key=lambda x: float(x.get("ltv_percent") or 0), reverse=True)
    top = sorted_items[0]
    count = len(sorted_items)
    label = "high-risk loan" if count == 1 else "high-risk loans"
    body = (
        _business_summary(f"There are {count} {label} above the LTV threshold.")
        + _action_banner(
            f"Review {_display_customer_name(top)} first.",
            f"Highest LTV at {format_ltv(top.get('ltv_percent', 0))}.",
            ltv_percent=top.get("ltv_percent"),
            due_date=_payment_due_date(top),
        )
    )
    return _assistant_response(body)


def build_collateral_at_risk_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _assistant_response(
            _business_summary("No collateral at risk found.")
            + _action_banner(
                "No collateral follow-up needed.",
                "No items are approaching forfeiture.",
            )
        )

    sorted_items = sorted(
        rows,
        key=lambda x: parse_date(x.get("forfeiture_date")) or date.max,
    )
    first = sorted_items[0]
    count = len(sorted_items)
    label = "collateral item" if count == 1 else "collateral items"
    body = (
        _business_summary(f"There are {count} {label} at risk of forfeiture.")
        + _action_banner(
            f"Follow up with {_display_customer_name(first)} first.",
            f"Nearest forfeiture date: {format_date_short(first.get('forfeiture_date'))}.",
            forfeiture_date=first.get("forfeiture_date"),
        )
    )
    return _assistant_response(body)


def build_missed_payments_text(items) -> str:
    rows = extract_rows(items)
    if not rows:
        return _assistant_response(
            _business_summary("No missed payments found.")
            + _action_banner(
                "No missed payment follow-up needed.",
                "All scheduled payments have been received.",
            )
        )

    sorted_items = _sort_by_due_date(rows)
    oldest = sorted_items[0]
    count = len(sorted_items)
    label = "missed payment" if count == 1 else "missed payments"
    body = (
        _business_summary(f"There are {count} {label} requiring follow-up.")
        + _action_banner(
            f"Call {_display_customer_name(oldest)} first.",
            "Oldest missed payment in the portfolio.",
            remaining_due=_payment_amount(oldest),
            due_date=oldest.get("due_date"),
        )
    )
    return _assistant_response(body)


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
    accounts = extract_rows(data.get("accounts"))
    loans = extract_rows(data.get("loans"))
    payments = extract_rows(data.get("payments"))
    collateral = extract_rows(data.get("collateral"))
    today = date.today()

    summary_parts = []
    if accounts:
        summary_parts.append(f"{len(accounts)} account{'s' if len(accounts) != 1 else ''}")
    if loans:
        summary_parts.append(f"{len(loans)} loan{'s' if len(loans) != 1 else ''}")
    if payments:
        summary_parts.append(f"{len(payments)} payment record{'s' if len(payments) != 1 else ''}")
    if collateral:
        summary_parts.append(f"{len(collateral)} collateral item{'s' if len(collateral) != 1 else ''}")

    if summary_parts:
        business_text = f"{name} has {', '.join(summary_parts)} on file."
    else:
        business_text = f"No records on file for {name}."

    contact_bits = []
    if customer.get("phone"):
        contact_bits.append(format_phone_paren(customer["phone"]))
    if customer.get("email"):
        contact_bits.append(str(customer["email"]))
    if contact_bits:
        business_text += f" Contact: {', '.join(contact_bits)}."

    overdue_payment = None
    for payment in payments:
        remaining = payment.get("remaining_due")
        due = parse_date(payment.get("due_date"))
        if remaining and float(remaining) > 0 and due and due < today:
            overdue_payment = payment
            break

    if overdue_payment:
        remaining = overdue_payment.get("remaining_due")
        due = overdue_payment.get("due_date")
        action = f"Call {name}."
        reason = (
            f"Follow up on {format_money(remaining)} overdue since "
            f"{format_date_short(due)}."
        )
        banner = _action_banner(
            action,
            reason,
            remaining_due=remaining,
            due_date=due,
        )
    else:
        banner = _action_banner(
            "No immediate follow-up required.",
            "Current records are up to date.",
        )

    return _assistant_response(_business_summary(business_text) + banner)


def build_customer_accounts_text(customer: dict, accounts: list) -> str:
    name = _display_customer_name(customer)
    if not accounts:
        return _assistant_response(
            _business_summary(f"No accounts on file for {name}.")
            + _action_banner(
                "Confirm account setup with the customer.",
                "No checking or savings accounts were found.",
            )
        )

    total = sum(float(a.get("balance") or 0) for a in accounts)
    body = (
        _business_summary(
            f"{name} has {len(accounts)} account{'s' if len(accounts) != 1 else ''} "
            f"with a combined balance of {format_money(total)}."
        )
        + _action_banner(
            f"Review balances with {name}.",
            f"Total balance across accounts: {format_money(total)}.",
        )
    )
    return _assistant_response(body)


def build_customer_loans_text(customer: dict, loans: list) -> str:
    name = _display_customer_name(customer)
    if not loans:
        return _assistant_response(
            _business_summary(f"No loans on file for {name}.")
            + _action_banner(
                "Discuss lending options if needed.",
                "No active loan records were found.",
            )
        )

    total = sum(float(loan.get("current_balance") or 0) for loan in loans)
    body = (
        _business_summary(
            f"{name} has {len(loans)} loan{'s' if len(loans) != 1 else ''} "
            f"with {format_money(total)} outstanding."
        )
        + _action_banner(
            f"Discuss loan details with {name}.",
            f"Total outstanding: {format_money(total)}." if total else "Review loan status.",
        )
    )
    return _assistant_response(body)


ACTION_FORMATTERS = {
    "today_priorities": lambda data: build_today_priorities_dashboard(data if isinstance(data, dict) else {}),
    "overdue_customers": build_overdue_customers_text,
    "due_today_customers": build_due_today_customers_text,
    "due_tomorrow_customers": build_due_tomorrow_customers_text,
    "due_this_week_customers": build_due_this_week_customers_text,
    "due_soon_customers": build_due_soon_customers_text,
    "missed_payments": build_missed_payments_text,
    "high_risk_loans": build_high_risk_loans_text,
    "collateral_at_risk": build_collateral_at_risk_text,
    "customer_count": build_customer_count_text,
    "loan_count": build_loan_count_text,
    "account_count": build_account_count_text,
    "total_overdue": build_total_overdue_text,
    "portfolio_balance": build_portfolio_balance_text,
    "portfolio_summary": build_portfolio_summary_text,
}

# Backward-compatible alias used by llm_chat operational routing.
OPERATIONAL_HANDLERS = ACTION_FORMATTERS

OPERATIONAL_HISTORY = {
    "today_priorities": "Provided today's follow-up plan.",
    "overdue_customers": "Provided overdue customer list.",
    "due_today_customers": "Provided due-today customer list.",
    "due_tomorrow_customers": "Provided due-tomorrow customer list.",
    "due_this_week_customers": "Provided due-this-week customer list.",
    "due_soon_customers": "Provided due-soon customer list.",
    "missed_payments": "Provided missed payment list.",
    "high_risk_loans": "Provided high-LTV loan list.",
    "collateral_at_risk": "Provided collateral-at-risk list.",
    "customer_count": "Provided customer count.",
    "loan_count": "Provided loan count.",
    "account_count": "Provided account count.",
    "total_overdue": "Provided total overdue amount.",
    "portfolio_balance": "Provided portfolio balance totals.",
    "portfolio_summary": "Provided portfolio summary.",
    "customer_search": "Provided customer search results.",
}

OPERATIONAL_TOOLS = {
    "today_priorities": "get_today_priorities",
    "overdue_customers": "get_overdue_customers",
    "due_today_customers": "get_due_today_customers",
    "due_tomorrow_customers": "get_due_tomorrow_customers",
    "due_this_week_customers": "get_due_this_week_customers",
    "due_soon_customers": "get_due_soon_customers",
    "missed_payments": "get_missed_payments",
    "high_risk_loans": "get_high_risk_loans",
    "collateral_at_risk": "get_collateral_at_risk",
    "customer_count": "get_customer_count",
    "loan_count": "get_loan_count",
    "account_count": "get_account_count",
    "total_overdue": "get_total_overdue_amount",
    "portfolio_balance": "get_total_portfolio_balance",
    "portfolio_summary": "get_portfolio_summary",
    "customer_search": "search_customers",
}


def build_today_priorities_response(
    data: dict | None = None,
    query_details: dict | None = None,
) -> dict:
    payload = data if data is not None else get_today_priorities()
    return html_response(
        build_today_priorities_dashboard(payload),
        OPERATIONAL_HISTORY["today_priorities"],
        [{"tool": "get_today_priorities", "args": {}}],
        query_details=query_details,
    )
