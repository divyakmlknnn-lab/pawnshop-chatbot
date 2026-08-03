"""Deterministic SELECT projection enrichment for MCP-only TellerIQ SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from intent import (
    COLLATERAL_RISK,
    CUSTOMER_LOANS,
    CUSTOMER_SUMMARY,
    DUE_SOON,
    DUE_THIS_WEEK,
    DUE_TODAY,
    DUE_TOMORROW,
    HIGH_RISK_LOANS,
    MISSED_PAYMENTS,
    OVERDUE_CUSTOMERS,
)
from schema_metadata import get_approved_schema, list_projection_profiles
from sql_validation import validate_readonly_sql

# Deterministic profiles only (Phase B). Advisory-only profiles are ignored.
DETERMINISTIC_PROFILES: frozenset[str] = frozenset(
    {
        "customer_detail",
        "overdue_payments",
        "due_soon",
        "high_risk_loans",
        "collateral_detail",
    }
)

INTENT_TO_PROFILE: dict[str, str] = {
    CUSTOMER_SUMMARY: "customer_detail",
    CUSTOMER_LOANS: "customer_detail",
    OVERDUE_CUSTOMERS: "overdue_payments",
    MISSED_PAYMENTS: "overdue_payments",
    DUE_SOON: "due_soon",
    DUE_TODAY: "due_soon",
    DUE_TOMORROW: "due_soon",
    DUE_THIS_WEEK: "due_soon",
    HIGH_RISK_LOANS: "high_risk_loans",
    COLLATERAL_RISK: "collateral_detail",
}

_PREFERRED_ALIASES: dict[str, str] = {
    "customers": "c",
    "loans": "l",
    "payments": "p",
    "collateral_items": "ci",
    "accounts": "a",
}

_RESTRICTED_CONTACT_FIELDS: frozenset[str] = frozenset({"phone", "email"})

_IDENTIFIER = r"`?([a-zA-Z_][a-zA-Z0-9_]*)`?"
_SELECT_FROM = re.compile(
    r"^\s*SELECT\b(?P<select>.+?)\bFROM\b(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_SELECT_MODIFIERS = re.compile(r"^\s*(?P<mod>(?:DISTINCT|ALL)\s+)", re.IGNORECASE)
_FROM_CLAUSE = re.compile(
    rf"\bFROM\s+(?:(?P<schema>{_IDENTIFIER})\.)?(?P<table>{_IDENTIFIER})"
    rf"(?:\s+(?:AS\s+)?(?P<alias>{_IDENTIFIER}))?",
    re.IGNORECASE,
)
_JOIN_CLAUSE = re.compile(
    rf"\b(?:INNER|LEFT|RIGHT|CROSS)?\s*JOIN\s+(?:(?P<schema>{_IDENTIFIER})\.)?(?P<table>{_IDENTIFIER})"
    rf"(?:\s+(?:AS\s+)?(?P<alias>{_IDENTIFIER}))?"
    rf"\s+ON\s+(?P<on>.+?)(?=\s+(?:INNER|LEFT|RIGHT|CROSS|JOIN|WHERE|GROUP|ORDER|HAVING|LIMIT)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_TAIL_CLAUSE = re.compile(
    r"(?P<head>.*?)(?P<tail>\b(?:WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b.*)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_AGGREGATE_FN = re.compile(r"\b(?:COUNT|SUM|AVG|MIN|MAX)\s*\(", re.IGNORECASE)
_QUALIFIED_COLUMN = re.compile(
    rf"(?<![a-zA-Z0-9_`]){_IDENTIFIER}\.{_IDENTIFIER}(?![a-zA-Z0-9_`])"
)
_BARE_IDENTIFIER = re.compile(rf"^{_IDENTIFIER}$", re.IGNORECASE)
_AS_ALIAS = re.compile(rf"\bAS\s+{_IDENTIFIER}\s*$", re.IGNORECASE)
_CONTACT_REQUEST = re.compile(
    r"\b(?:phone|email|e-mail|contact(?:\s+details?)?)\b",
    re.IGNORECASE,
)
_SQL_KEYWORDS = frozenset(
    {
        "select",
        "from",
        "where",
        "join",
        "inner",
        "left",
        "right",
        "on",
        "and",
        "or",
        "as",
        "group",
        "order",
        "by",
        "having",
        "limit",
        "asc",
        "desc",
        "distinct",
        "all",
        "null",
        "nullif",
        "case",
        "when",
        "then",
        "else",
        "end",
        "not",
        "in",
        "is",
        "like",
        "between",
        "exists",
        "true",
        "false",
        "curdate",
        "current_date",
        "date_add",
        "interval",
        "day",
        "round",
        "count",
        "sum",
        "avg",
        "min",
        "max",
    }
)


@dataclass
class EnrichmentResult:
    """Outcome of deterministic SELECT projection enrichment."""

    sql: str
    original_sql: str
    applied: bool = False
    skipped: bool = False
    reason: str = ""
    profile: str | None = None
    added_fields: list[str] = field(default_factory=list)
    added_joins: list[str] = field(default_factory=list)
    attempted_sql: str | None = None
    validation_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "applied": self.applied,
            "skipped": self.skipped,
            "reason": self.reason,
            "original_sql": self.original_sql,
            "enriched_sql": self.sql if self.applied else None,
            "attempted_sql": self.attempted_sql,
            "added_fields": list(self.added_fields),
            "added_joins": list(self.added_joins),
            "validation_error": self.validation_error,
        }


def profile_for_intent(intent: str | None) -> str | None:
    """Return deterministic projection profile name for a classified intent."""
    if not intent:
        return None
    profile = INTENT_TO_PROFILE.get(str(intent).strip().upper())
    if profile in DETERMINISTIC_PROFILES:
        return profile
    return None


def get_profile_definition(profile_name: str) -> dict[str, Any] | None:
    for profile in list_projection_profiles():
        if profile.get("name") == profile_name:
            return profile
    return None


def user_requested_contact_fields(user_message: str | None) -> bool:
    return bool(user_message and _CONTACT_REQUEST.search(user_message))


def _normalize_expression(expression: str) -> str:
    return re.sub(r"\s+", "", expression or "").lower()


def _strip_qualifiers(expression: str) -> str:
    return _QUALIFIED_COLUMN.sub(lambda match: match.group(2), expression or "")


def _split_select_list(select_clause: str) -> list[str]:
    items: list[str] = []
    depth = 0
    current: list[str] = []
    for char in select_clause:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            continue
        current.append(char)
    trailing = "".join(current).strip()
    if trailing:
        items.append(trailing)
    return items


def _extract_alias(select_item: str) -> tuple[str, str | None]:
    match = _AS_ALIAS.search(select_item)
    if match:
        return select_item[: match.start()].strip(), match.group(1).lower()
    parts = select_item.rsplit(None, 1)
    if len(parts) == 2 and _BARE_IDENTIFIER.fullmatch(parts[1]):
        maybe_alias = parts[1].lower().strip("`")
        if maybe_alias not in _SQL_KEYWORDS and "." not in parts[0]:
            # Bare trailing alias only when left side is an expression, not table.col
            left = parts[0].strip()
            if not _BARE_IDENTIFIER.fullmatch(left) and not _QUALIFIED_COLUMN.fullmatch(left):
                return left, maybe_alias
    return select_item.strip(), None


def _parse_sql_parts(sql: str) -> dict[str, Any] | None:
    match = _SELECT_FROM.match(sql.strip())
    if not match:
        return None
    select_raw = match.group("select")
    rest = match.group("rest").strip()
    modifier_match = _SELECT_MODIFIERS.match(select_raw)
    modifier = ""
    select_body = select_raw
    if modifier_match:
        modifier = modifier_match.group("mod")
        select_body = select_raw[modifier_match.end() :]
    tail_match = _TAIL_CLAUSE.match(rest)
    if tail_match:
        from_joins = tail_match.group("head").strip()
        preserved_tail = tail_match.group("tail").strip()
    else:
        from_joins = rest
        preserved_tail = ""
    # Re-attach leading FROM for table parsing.
    from_sql = f"FROM {from_joins}"
    return {
        "modifier": modifier,
        "select_items": _split_select_list(select_body),
        "from_joins": from_joins,
        "from_sql": from_sql,
        "preserved_tail": preserved_tail,
        "where_clause": _extract_where_clause(preserved_tail),
    }


def _extract_where_clause(preserved_tail: str) -> str | None:
    if not preserved_tail:
        return None
    match = re.search(
        r"\bWHERE\b(?P<where>.+?)(?=\b(?:GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b|$)",
        preserved_tail,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return match.group("where").strip()


def _parse_tables(from_sql: str) -> tuple[set[str], dict[str, str], dict[str, str]]:
    """Return table_names, alias_to_table, table_to_alias."""
    table_names: set[str] = set()
    alias_to_table: dict[str, str] = {}
    table_to_alias: dict[str, str] = {}

    from_match = _FROM_CLAUSE.search(from_sql)
    if not from_match:
        return table_names, alias_to_table, table_to_alias

    table = from_match.group("table").lower().strip("`")
    alias = (from_match.group("alias") or table).lower().strip("`")
    table_names.add(table)
    alias_to_table[alias] = table
    table_to_alias[table] = alias

    for join_match in _JOIN_CLAUSE.finditer(from_sql):
        join_table = join_match.group("table").lower().strip("`")
        join_alias = (join_match.group("alias") or join_table).lower().strip("`")
        table_names.add(join_table)
        alias_to_table[join_alias] = join_table
        table_to_alias.setdefault(join_table, join_alias)

    return table_names, alias_to_table, table_to_alias


def _is_aggregate_select(select_items: list[str], preserved_tail: str) -> bool:
    if re.search(r"\bGROUP\s+BY\b", preserved_tail, re.IGNORECASE):
        return True
    for item in select_items:
        expression, _alias = _extract_alias(item)
        if _AGGREGATE_FN.search(expression):
            return True
    return False


def _build_field_catalog(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map field/alias name -> {kind, table, expression?}."""
    catalog: dict[str, dict[str, Any]] = {}
    for table_name, table_meta in (schema.get("tables") or {}).items():
        for column in table_meta.get("fields") or []:
            # Prefer first owner; customers before loans for shared keys when both listed.
            if column not in catalog:
                catalog[column] = {"kind": "column", "table": table_name}
            elif table_name == "customers" and column in {"customer_id"}:
                catalog[column] = {"kind": "column", "table": table_name}
        for computed in table_meta.get("computed_fields") or []:
            name = computed["name"]
            catalog[name] = {
                "kind": "computed",
                "table": table_name,
                "expression": computed["expression"],
            }
    return catalog


def _selected_field_names(
    select_items: list[str],
    catalog: dict[str, dict[str, Any]],
) -> set[str]:
    present: set[str] = set()
    for item in select_items:
        expression, alias = _extract_alias(item)
        if alias:
            present.add(alias.lower())
        normalized = _normalize_expression(expression)
        stripped = _normalize_expression(_strip_qualifiers(expression))
        for name, meta in catalog.items():
            if meta["kind"] == "computed":
                approved = _normalize_expression(meta["expression"])
                if normalized == approved or stripped == approved:
                    present.add(name)
                    break
        if _BARE_IDENTIFIER.fullmatch(expression.strip()):
            present.add(expression.strip().lower().strip("`"))
            continue
        qualified = _QUALIFIED_COLUMN.fullmatch(expression.strip())
        if qualified:
            present.add(qualified.group(2).lower())
    return present


def _qualify_expression(expression: str, table: str, table_to_alias: dict[str, str]) -> str:
    alias = table_to_alias.get(table, table)
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[^A-Za-z_]+", expression)
    rebuilt: list[str] = []
    for token in tokens:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            lowered = token.lower()
            if lowered in _SQL_KEYWORDS or lowered.isdigit():
                rebuilt.append(token)
            else:
                rebuilt.append(f"{alias}.{token}")
        else:
            rebuilt.append(token)
    return "".join(rebuilt)


def _ensure_table_aliases(
    from_joins: str,
    table_names: set[str],
    table_to_alias: dict[str, str],
    alias_to_table: dict[str, str],
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Ensure FROM tables that will be joined have stable aliases."""
    from_match = _FROM_CLAUSE.search(f"FROM {from_joins}")
    if not from_match:
        return from_joins, table_to_alias, alias_to_table

    table = from_match.group("table").lower().strip("`")
    existing_alias = from_match.group("alias")
    if existing_alias:
        return from_joins, table_to_alias, alias_to_table

    preferred = _PREFERRED_ALIASES.get(table, table[0] if table else table)
    # Avoid alias collision with existing join aliases.
    used = set(alias_to_table)
    alias = preferred
    if alias in used and alias_to_table.get(alias) != table:
        suffix = 2
        while f"{preferred}{suffix}" in used:
            suffix += 1
        alias = f"{preferred}{suffix}"

    # from_joins does not include the FROM keyword; alias the leading table.
    updated = re.sub(
        rf"^{re.escape(table)}\b",
        f"{table} {alias}",
        from_joins,
        count=1,
        flags=re.IGNORECASE,
    )

    table_to_alias = dict(table_to_alias)
    alias_to_table = dict(alias_to_table)
    if table in alias_to_table and alias_to_table[table] == table:
        del alias_to_table[table]
    alias_to_table[alias] = table
    table_to_alias[table] = alias
    return updated, table_to_alias, alias_to_table


def _relationship_edges(
    relationships: list[dict[str, str]],
) -> list[tuple[str, str, str, str]]:
    edges: list[tuple[str, str, str, str]] = []
    for rel in relationships:
        edges.append(
            (
                rel["from_table"],
                rel["from_column"],
                rel["to_table"],
                rel["to_column"],
            )
        )
        edges.append(
            (
                rel["to_table"],
                rel["to_column"],
                rel["from_table"],
                rel["from_column"],
            )
        )
    return edges


def _plan_join_path(
    present: set[str],
    needed: set[str],
    relationships: list[dict[str, str]],
    table_to_alias: dict[str, str],
) -> tuple[list[str], dict[str, str], list[str]] | None:
    """Plan approved JOINs to reach needed tables. Returns (join_sqls, updated aliases, joined tables)."""
    missing = set(needed) - present
    if not missing:
        return [], dict(table_to_alias), []

    edges = _relationship_edges(relationships)
    reachable = set(present)
    join_sqls: list[str] = []
    joined_tables: list[str] = []
    aliases = dict(table_to_alias)
    used_aliases = set(aliases.values())

    def allocate_alias(table: str) -> str:
        preferred = _PREFERRED_ALIASES.get(table, table[0])
        alias = preferred
        if alias in used_aliases:
            suffix = 2
            while f"{preferred}{suffix}" in used_aliases:
                suffix += 1
            alias = f"{preferred}{suffix}"
        used_aliases.add(alias)
        aliases[table] = alias
        return alias

    # Iteratively attach any missing table adjacent to the reachable set.
    progress = True
    while missing and progress:
        progress = False
        for left_table, left_col, right_table, right_col in edges:
            if left_table not in reachable or right_table in reachable:
                continue
            if right_table not in missing and right_table not in needed:
                continue
            if right_table not in needed:
                continue
            left_alias = aliases.get(left_table) or allocate_alias(left_table)
            right_alias = allocate_alias(right_table)
            join_sql = (
                f"JOIN {right_table} {right_alias} "
                f"ON {right_alias}.{right_col} = {left_alias}.{left_col}"
            )
            join_sqls.append(join_sql)
            joined_tables.append(right_table)
            reachable.add(right_table)
            missing.discard(right_table)
            progress = True
            break

    if missing:
        return None
    return join_sqls, aliases, joined_tables


def _render_select_expression(
    field_name: str,
    catalog: dict[str, dict[str, Any]],
    table_to_alias: dict[str, str],
) -> str | None:
    meta = catalog.get(field_name)
    if not meta:
        return None
    table = meta["table"]
    alias = table_to_alias.get(table, table)
    if meta["kind"] == "computed":
        qualified = _qualify_expression(meta["expression"], table, table_to_alias)
        return f"{qualified} AS {field_name}"
    return f"{alias}.{field_name}"


def _column_owners(
    column: str,
    table_names: set[str],
    schema: dict[str, Any],
) -> list[str]:
    owners: list[str] = []
    for table in table_names:
        fields = (schema.get("tables") or {}).get(table, {}).get("fields") or []
        if column in fields:
            owners.append(table)
    return owners


def _bare_identifiers_in_sql_fragment(fragment: str | None) -> set[str]:
    if not fragment:
        return set()
    # Ignore string literals for contact/name filters.
    scrubbed = re.sub(r"'([^']|'')*'", "''", fragment)
    scrubbed = re.sub(r'"([^"]|"")*"', '""', scrubbed)
    found: set[str] = set()
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", scrubbed):
        token = match.group(1).lower()
        if token in _SQL_KEYWORDS:
            continue
        # Skip qualified left-hand sides by checking preceding char in original span.
        start = match.start()
        if start > 0 and scrubbed[start - 1] == ".":
            continue
        # Skip table.column right side already handled; also skip function names followed by (
        end = match.end()
        if end < len(scrubbed) and scrubbed[end:].lstrip().startswith("("):
            continue
        found.add(token)
    return found


def _where_would_be_ambiguous(
    where_clause: str | None,
    table_names: set[str],
    schema: dict[str, Any],
) -> bool:
    for column in _bare_identifiers_in_sql_fragment(where_clause):
        owners = _column_owners(column, table_names, schema)
        if len(owners) > 1:
            return True
    return False


def _qualify_original_select_items(
    select_items: list[str],
    table_names: set[str],
    table_to_alias: dict[str, str],
    schema: dict[str, Any],
) -> list[str]:
    """Qualify bare SELECT columns so added joins do not create ambiguity."""
    if len(table_names) <= 1:
        return list(select_items)

    qualified_items: list[str] = []
    for item in select_items:
        expression, alias = _extract_alias(item)
        expr = expression.strip()
        if _BARE_IDENTIFIER.fullmatch(expr):
            column = expr.lower().strip("`")
            owners = _column_owners(column, table_names, schema)
            if len(owners) == 1:
                table_alias = table_to_alias.get(owners[0], owners[0])
                rewritten = f"{table_alias}.{column}"
                if alias:
                    rewritten = f"{rewritten} AS {alias}"
                qualified_items.append(rewritten)
                continue
            if len(owners) > 1:
                # Prefer customers for shared identity keys when present.
                preferred = "customers" if "customers" in owners else owners[0]
                table_alias = table_to_alias.get(preferred, preferred)
                rewritten = f"{table_alias}.{column}"
                if alias:
                    rewritten = f"{rewritten} AS {alias}"
                qualified_items.append(rewritten)
                continue
        if alias:
            qualified_items.append(f"{expression} AS {alias}")
        else:
            qualified_items.append(item)
    return qualified_items


def enrich_select_projection(
    sql: str,
    *,
    intent: str | None,
    user_message: str | None = None,
) -> EnrichmentResult:
    """Enrich a thin SELECT projection using the deterministic profile for intent.

    Preserves FROM/JOIN/WHERE/GROUP BY/ORDER BY/LIMIT unless approved joins must
    be appended to reach profile tables. Never invents non-schema joins. Never
    adds phone/email unless the user explicitly requested contact details.
    Aggregate/count queries are left unchanged.
    """
    original_sql = (sql or "").strip()
    result = EnrichmentResult(sql=original_sql, original_sql=original_sql)

    if not original_sql:
        result.skipped = True
        result.reason = "empty_sql"
        return result

    profile_name = profile_for_intent(intent)
    result.profile = profile_name
    if not profile_name:
        result.skipped = True
        result.reason = "no_deterministic_profile"
        return result

    profile = get_profile_definition(profile_name)
    if not profile:
        result.skipped = True
        result.reason = "profile_definition_missing"
        return result

    parts = _parse_sql_parts(original_sql)
    if not parts:
        result.skipped = True
        result.reason = "unparseable_sql"
        return result

    if _is_aggregate_select(parts["select_items"], parts["preserved_tail"]):
        result.skipped = True
        result.reason = "aggregate_query"
        return result

    schema = get_approved_schema()
    catalog = _build_field_catalog(schema)
    present_fields = _selected_field_names(parts["select_items"], catalog)

    allow_contact = user_requested_contact_fields(user_message)
    recommended = [
        field_name
        for field_name in profile.get("recommended_fields") or []
        if field_name not in _RESTRICTED_CONTACT_FIELDS or allow_contact
    ]
    missing = [name for name in recommended if name not in present_fields]
    if not missing:
        result.skipped = True
        result.reason = "projection_already_complete"
        return result

    table_names, alias_to_table, table_to_alias = _parse_tables(parts["from_sql"])
    if not table_names:
        result.skipped = True
        result.reason = "no_tables"
        return result

    # Tables required by missing fields only.
    needed_tables: set[str] = set()
    actionable_missing: list[str] = []
    for field_name in missing:
        meta = catalog.get(field_name)
        if not meta:
            continue
        needed_tables.add(meta["table"])
        actionable_missing.append(field_name)

    if not actionable_missing:
        result.skipped = True
        result.reason = "no_actionable_fields"
        return result

    from_joins = parts["from_joins"]
    # Alias the primary FROM table before appending joins when needed.
    if needed_tables - table_names:
        from_joins, table_to_alias, alias_to_table = _ensure_table_aliases(
            from_joins,
            table_names,
            table_to_alias,
            alias_to_table,
        )

    join_plan = _plan_join_path(
        present=set(table_names),
        needed=set(table_names) | needed_tables,
        relationships=list(schema.get("relationships") or []),
        table_to_alias=table_to_alias,
    )
    if join_plan is None:
        # Fall back: enrich only fields whose tables are already present.
        actionable_missing = [
            name
            for name in actionable_missing
            if catalog[name]["table"] in table_names
        ]
        added_join_sqls: list[str] = []
        if not actionable_missing:
            result.skipped = True
            result.reason = "required_joins_unavailable"
            return result
        final_tables = set(table_names)
    else:
        added_join_sqls, table_to_alias, joined_tables = join_plan
        final_tables = set(table_names) | set(joined_tables)
        # Never rewrite WHERE; skip join expansion if bare WHERE columns
        # would become ambiguous across the expanded table set.
        if added_join_sqls and _where_would_be_ambiguous(
            parts["where_clause"],
            final_tables,
            schema,
        ):
            actionable_missing = [
                name
                for name in actionable_missing
                if catalog[name]["table"] in table_names
            ]
            added_join_sqls = []
            final_tables = set(table_names)
            if not actionable_missing:
                result.skipped = True
                result.reason = "join_enrichment_would_ambiguate_where"
                return result

    added_expressions: list[str] = []
    added_fields: list[str] = []
    for field_name in actionable_missing:
        if catalog[field_name]["table"] not in final_tables:
            continue
        expression = _render_select_expression(field_name, catalog, table_to_alias)
        if not expression:
            continue
        added_expressions.append(expression)
        added_fields.append(field_name)

    if not added_expressions:
        result.skipped = True
        result.reason = "nothing_to_add"
        return result

    new_from = from_joins.rstrip()
    for join_sql in added_join_sqls:
        new_from = f"{new_from} {join_sql}"

    base_select_items = _qualify_original_select_items(
        parts["select_items"],
        final_tables,
        table_to_alias,
        schema,
    )
    select_list = ", ".join(base_select_items + added_expressions)
    modifier = parts["modifier"] or ""
    enriched = f"SELECT {modifier}{select_list} FROM {new_from}"
    if parts["preserved_tail"]:
        enriched = f"{enriched} {parts['preserved_tail']}"
    enriched = re.sub(r"\s+", " ", enriched).strip()

    result.attempted_sql = enriched
    result.added_fields = added_fields
    result.added_joins = list(added_join_sqls)

    # WHERE must be preserved exactly when present.
    original_where = parts["where_clause"]
    enriched_parts = _parse_sql_parts(enriched)
    if original_where is not None and enriched_parts:
        if enriched_parts["where_clause"] != original_where:
            result.skipped = True
            result.reason = "where_clause_mutated"
            return result

    validation = validate_readonly_sql(
        enriched,
        allow_contact_fields=allow_contact,
    )
    if not validation.get("valid"):
        result.skipped = True
        result.reason = "validation_failed"
        result.validation_error = validation.get("reason") or "validation failed"
        return result

    result.sql = enriched
    result.applied = True
    result.reason = "enriched"
    return result
