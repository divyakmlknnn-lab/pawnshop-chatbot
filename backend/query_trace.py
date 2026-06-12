import re
from copy import deepcopy


def format_sql_for_display(sql: str, params=None) -> str:
    cleaned = re.sub(r"\s+", " ", (sql or "").strip())
    if not params:
        return cleaned
    display = cleaned
    for param in params:
        if isinstance(param, str):
            replacement = f"'{param}'"
        else:
            replacement = str(param)
        display = display.replace("%s", replacement, 1)
    return display


def make_trace(sql: str, tables_used: dict[str, list[str]], rows, params=None) -> dict:
    return {
        "tables_used": tables_used,
        "sql": format_sql_for_display(sql, params),
        "rows": deepcopy(rows) if rows is not None else [],
    }


def is_traced(obj) -> bool:
    return (
        isinstance(obj, dict)
        and "sql" in obj
        and "rows" in obj
        and "tables_used" in obj
    )


def extract_rows(obj):
    if obj is None:
        return []
    if is_traced(obj):
        return obj.get("rows") or []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if obj.get("error"):
            return []
        if "matches" in obj and isinstance(obj["matches"], list):
            return obj["matches"]
        if not is_traced(obj) and not obj.get("_traces"):
            keys = [key for key in obj if not key.startswith("_")]
            if keys and all(not isinstance(obj[key], (dict, list)) for key in keys):
                return [obj]
    return []


def merge_tables_used(*table_dicts: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for tables in table_dicts:
        if not isinstance(tables, dict):
            continue
        for table, columns in tables.items():
            existing = merged.setdefault(table, [])
            for column in columns or []:
                if column not in existing:
                    existing.append(column)
    return merged


def is_today_priorities_result(obj) -> bool:
    return (
        isinstance(obj, dict)
        and {"overdue", "due_soon", "high_risk"}.issubset(obj.keys())
    )


def is_customer_summary_result(obj) -> bool:
    return (
        isinstance(obj, dict)
        and "customer" in obj
        and any(key in obj for key in ("accounts", "loans", "payments", "collateral"))
    )


def _item_key(item: dict) -> tuple:
    return (item.get("customer_id"), item.get("full_name"), item.get("loan_type"))


def _flatten_today_priorities(result: dict) -> list[dict]:
    overdue = extract_rows(result.get("overdue"))
    due_soon = extract_rows(result.get("due_soon"))
    high_risk = extract_rows(result.get("high_risk"))[:5]

    seen = set()
    rows: list[dict] = []

    for item in sorted(
        overdue,
        key=lambda row: row.get("due_date") or "",
    ):
        seen.add(_item_key(item))
        row = dict(item)
        row["priority_status"] = "Overdue"
        rows.append(row)

    for item in sorted(
        due_soon,
        key=lambda row: row.get("due_date") or "",
    ):
        key = _item_key(item)
        if key in seen:
            continue
        seen.add(key)
        row = dict(item)
        row["priority_status"] = "Due Soon"
        rows.append(row)

    for item in high_risk:
        key = _item_key(item)
        if key in seen:
            continue
        seen.add(key)
        row = dict(item)
        row["priority_status"] = "High Risk"
        rows.append(row)

    return rows


def _flatten_customer_summary(summary: dict) -> list[dict]:
    rows: list[dict] = []
    customer = summary.get("customer")
    if isinstance(customer, dict) and customer:
        row = dict(customer)
        row["record_type"] = "Customer"
        rows.append(row)

    for key, label in (
        ("accounts", "Account"),
        ("loans", "Loan"),
        ("payments", "Payment"),
        ("collateral", "Collateral"),
    ):
        for item in extract_rows(summary.get(key)):
            row = dict(item)
            row["record_type"] = label
            rows.append(row)
    return rows


def _scalar_result_rows(result: dict) -> list[dict]:
    clean = {
        key: value
        for key, value in result.items()
        if not key.startswith("_")
        and not isinstance(value, (dict, list))
    }
    return [clean] if clean else []


def _collect_sql_and_tables(obj, label: str = "") -> tuple[list[str], dict[str, list[str]]]:
    sql_parts: list[str] = []
    tables: dict[str, list[str]] = {}

    if obj is None:
        return sql_parts, tables

    if is_traced(obj):
        sql = (obj.get("sql") or "").strip()
        if sql:
            prefix = f"-- {label}\n" if label else ""
            sql_parts.append(f"{prefix}{sql}")
        tables = merge_tables_used(tables, obj.get("tables_used") or {})
        return sql_parts, tables

    if isinstance(obj, dict):
        if obj.get("error"):
            return sql_parts, tables

        nested_traces = obj.get("_traces")
        if isinstance(nested_traces, list):
            for index, nested in enumerate(nested_traces, start=1):
                nested_sql, nested_tables = _collect_sql_and_tables(
                    nested,
                    label or f"Query {index}",
                )
                sql_parts.extend(nested_sql)
                tables = merge_tables_used(tables, nested_tables)
            return sql_parts, tables

        if is_today_priorities_result(obj):
            for key, section_label in (
                ("overdue", "Overdue"),
                ("due_soon", "Due Soon"),
                ("high_risk", "High Risk"),
            ):
                nested_sql, nested_tables = _collect_sql_and_tables(
                    obj.get(key),
                    section_label,
                )
                sql_parts.extend(nested_sql)
                tables = merge_tables_used(tables, nested_tables)
            return sql_parts, tables

        if is_customer_summary_result(obj):
            for key, section_label in (
                ("accounts", "Accounts"),
                ("loans", "Loans"),
                ("payments", "Payments"),
                ("collateral", "Collateral"),
            ):
                nested_sql, nested_tables = _collect_sql_and_tables(
                    obj.get(key),
                    section_label,
                )
                sql_parts.extend(nested_sql)
                tables = merge_tables_used(tables, nested_tables)
            return sql_parts, tables

    return sql_parts, tables


def extract_final_rows(tool_name: str, result) -> list[dict]:
    if result is None:
        return []
    if isinstance(result, dict) and result.get("error"):
        return []

    if tool_name == "customer_summary" or is_customer_summary_result(result):
        return _flatten_customer_summary(result)

    if tool_name == "get_today_priorities" or is_today_priorities_result(result):
        return _flatten_today_priorities(result)

    if isinstance(result, dict) and "_traces" in result:
        return _scalar_result_rows(result)

    if is_traced(result):
        return extract_rows(result)

    rows = extract_rows(result)
    return rows if rows else []


def extract_final_sql_and_tables(tool_name: str, result) -> tuple[str, dict[str, list[str]]]:
    if result is None or (isinstance(result, dict) and result.get("error")):
        return "", {}

    sql_parts, tables = _collect_sql_and_tables(result)
    if not sql_parts and is_traced(result):
        sql_parts = [(result.get("sql") or "").strip()]
        tables = merge_tables_used(tables, result.get("tables_used") or {})

    return "\n\n".join(part for part in sql_parts if part), tables


def build_final_query_entry(
    tool_name: str,
    tool_args: dict | None,
    result,
) -> dict | None:
    if isinstance(result, dict) and result.get("error"):
        return None

    rows = extract_final_rows(tool_name, result)
    if not rows:
        return None

    sql, tables_used = extract_final_sql_and_tables(tool_name, result)
    return {
        "tool": tool_name,
        "args": tool_args or {},
        "tables_used": tables_used,
        "sql": sql,
        "rows": rows,
    }


def collect_traces(obj, tool_name: str | None = None) -> list[dict]:
    traces: list[dict] = []
    if obj is None:
        return traces

    if is_traced(obj):
        trace = {
            "tool": tool_name or "query",
            "tables_used": obj.get("tables_used") or {},
            "sql": obj.get("sql") or "",
            "rows": obj.get("rows") or [],
        }
        traces.append(trace)
        return traces

    if isinstance(obj, dict):
        if obj.get("error"):
            return traces
        nested_traces = obj.get("_traces")
        if isinstance(nested_traces, list):
            for index, nested in enumerate(nested_traces):
                traces.extend(collect_traces(nested, tool_name=tool_name or f"query_{index + 1}"))
            return traces
        for key, value in obj.items():
            if key.startswith("_"):
                continue
            traces.extend(collect_traces(value, tool_name=tool_name or key))
        return traces

    if isinstance(obj, list):
        for item in obj:
            traces.extend(collect_traces(item, tool_name=tool_name))
    return traces
