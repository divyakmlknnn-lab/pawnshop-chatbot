"""Validate AI-generated read-only SQL against approved schema metadata."""

from __future__ import annotations

import re
from typing import Any

from schema_metadata import get_approved_schema

MAX_ROW_LIMIT = 100

ALLOWED_AGGREGATES: frozenset[str] = frozenset(
    {
        "sum",
        "count",
        "avg",
        "min",
        "max",
    }
)

FORBIDDEN_KEYWORDS: frozenset[str] = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "GRANT",
        "REVOKE",
        "CALL",
        "EXECUTE",
        "MERGE",
        "REPLACE",
    }
)

BLOCKED_SCHEMAS: frozenset[str] = frozenset(
    {
        "information_schema",
        "mysql",
        "performance_schema",
        "sys",
    }
)


def _normalize_expression(expression: str) -> str:
    return re.sub(r"\s+", " ", expression.strip().lower())


_SCHEMA = get_approved_schema()
_APPROVED_TABLES: frozenset[str] = frozenset(_SCHEMA["tables"].keys())
_TABLE_FIELDS: dict[str, frozenset[str]] = {
    table: frozenset(meta["fields"]) for table, meta in _SCHEMA["tables"].items()
}
_RESTRICTED_CONTACT_FIELDS: frozenset[str] = frozenset(_SCHEMA["restricted_contact_fields"])
_COMPUTED_FIELDS_BY_TABLE: dict[str, dict[str, str]] = {}
_COMPUTED_EXPRESSIONS: dict[str, str] = {}
for _field in _SCHEMA["computed_fields"]:
    _table = _field["table"]
    _name = _field["name"]
    _COMPUTED_FIELDS_BY_TABLE.setdefault(_table, {})[_name] = _field["expression"]
    _COMPUTED_EXPRESSIONS[_name] = _normalize_expression(_field["expression"])

_APPROVED_RELATIONSHIPS: tuple[tuple[str, str, str, str], ...] = tuple(
    (
        relationship["from_table"],
        relationship["from_column"],
        relationship["to_table"],
        relationship["to_column"],
    )
    for relationship in _SCHEMA["relationships"]
)

_IDENTIFIER = r"`?([a-zA-Z_][a-zA-Z0-9_]*)`?"
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
_ON_CONDITION = re.compile(
    rf"^{_IDENTIFIER}\.{_IDENTIFIER}\s*=\s*{_IDENTIFIER}\.{_IDENTIFIER}$",
    re.IGNORECASE,
)
_LIMIT_TRAILING = re.compile(
    r"\s+LIMIT\s+(?P<limit>\S+)(?:\s+OFFSET\s+(?P<offset>\S+))?\s*(?:;)?\s*$",
    re.IGNORECASE,
)
_SELECT_STAR = re.compile(r"\bSELECT\b(?P<select>.+?)\bFROM\b", re.IGNORECASE | re.DOTALL)
_SELECT_MODIFIERS = re.compile(r"^\s*(?:DISTINCT|ALL)\s+", re.IGNORECASE)
# Avoid \\b so backtick-quoted identifiers like `c`.`full_name` still match.
_QUALIFIED_COLUMN = re.compile(
    rf"(?<![a-zA-Z0-9_`]){_IDENTIFIER}\.{_IDENTIFIER}(?![a-zA-Z0-9_`])"
)
_QUALIFIED_COLUMN_EXACT = re.compile(rf"^{_IDENTIFIER}\.{_IDENTIFIER}$", re.IGNORECASE)
_BARE_IDENTIFIER = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")


def _validation_result(
    *,
    valid: bool,
    normalized_sql: str | None = None,
    reason: str | None = None,
    tables_used: list[str] | None = None,
    columns_used: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "valid": valid,
        "normalized_sql": normalized_sql,
        "reason": reason,
        "tables_used": sorted(set(tables_used or [])),
        "columns_used": sorted(set(columns_used or [])),
    }


def _strip_string_literals(sql: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char not in ("'", '"'):
            chars.append(char)
            index += 1
            continue

        quote = char
        chars.append(" ")
        index += 1
        while index < len(sql):
            if sql[index] == "\\" and index + 1 < len(sql):
                index += 2
                continue
            if sql[index] == quote:
                index += 1
                break
            index += 1
    return "".join(chars)


def _contains_comments(sql: str) -> bool:
    if re.search(r"--", sql):
        return True
    if re.search(r"#", sql):
        return True
    if re.search(r"/\*", sql):
        return True
    return False


def _has_multiple_statements(sql: str) -> bool:
    trimmed = sql.strip().rstrip(";").strip()
    return ";" in _strip_string_literals(trimmed)


def _contains_forbidden_keywords(sql: str) -> str | None:
    upper_sql = sql.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper_sql):
            return keyword
    if re.search(r"\bLOAD\s+DATA\b", upper_sql):
        return "LOAD DATA"
    return None


def _normalize_whitespace(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip())


def _has_comma_separated_from(sanitized: str) -> bool:
    from_match = re.search(r"\bFROM\b", sanitized, re.IGNORECASE)
    if from_match is None:
        return False
    tail = sanitized[from_match.end() :]
    stop_match = re.search(
        r"\b(WHERE|GROUP|ORDER|HAVING|LIMIT|JOIN)\b",
        tail,
        re.IGNORECASE,
    )
    from_segment = tail[: stop_match.start()] if stop_match else tail
    return "," in from_segment


def _reject_unsupported_structure(sanitized: str) -> str | None:
    if re.search(r"\bUNION\b", sanitized, re.IGNORECASE):
        return "UNION queries are not allowed."
    if re.search(r"\(\s*SELECT\b", sanitized, re.IGNORECASE):
        return "Subqueries and nested SELECT statements are not allowed."
    if len(re.findall(r"\bSELECT\b", sanitized, re.IGNORECASE)) > 1:
        return "Subqueries and nested SELECT statements are not allowed."
    if re.search(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", sanitized, re.IGNORECASE):
        return "INTO OUTFILE and INTO DUMPFILE are not allowed."
    if re.search(r"\bLIMIT\s+\d+\s*,\s*\d+\b", sanitized, re.IGNORECASE):
        return "LIMIT offset,count syntax is not allowed."
    if re.search(r"\bCROSS\s+JOIN\b", sanitized, re.IGNORECASE):
        return "CROSS JOIN is not allowed."
    if _has_comma_separated_from(sanitized):
        return "Comma-separated FROM tables are not allowed."
    for limit_match in re.finditer(r"\bLIMIT\s+(\S+)", sanitized, re.IGNORECASE):
        limit_token = limit_match.group(1).rstrip(";")
        if limit_token.isdigit():
            continue
        return "LIMIT must use a decimal integer."
    return None


def _contains_restricted_contact_references(sanitized: str) -> bool:
    for field in _RESTRICTED_CONTACT_FIELDS:
        if re.search(rf"(?<![a-zA-Z0-9_]){field}(?![a-zA-Z0-9_])", sanitized, re.IGNORECASE):
            return True
    return False


def _parse_table_reference(
    schema: str | None,
    table: str,
    alias: str | None,
) -> tuple[str | None, str, str]:
    # Named regex groups may include optional surrounding backticks from _IDENTIFIER.
    schema_name = schema.lower().strip("`") if schema else None
    table_name = table.lower().strip("`")
    alias_name = (alias or table).lower().strip("`")
    return schema_name, table_name, alias_name


def _is_blocked_schema_reference(schema_name: str | None, table_name: str) -> bool:
    if schema_name:
        return True
    return table_name in BLOCKED_SCHEMAS

def _resolve_table_name(
    reference: str,
    alias_map: dict[str, str],
    table_names: set[str],
) -> str | None:
    lowered = reference.lower()
    if lowered in alias_map:
        return alias_map[lowered]
    if lowered in table_names:
        return lowered
    return None


def _relationship_is_approved(
    left_table: str,
    left_column: str,
    right_table: str,
    right_column: str,
) -> bool:
    pair = (left_table, left_column, right_table, right_column)
    reverse_pair = (right_table, right_column, left_table, left_column)
    return pair in _APPROVED_RELATIONSHIPS or reverse_pair in _APPROVED_RELATIONSHIPS


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
    match = re.search(rf"\bAS\s+{_IDENTIFIER}", select_item, re.IGNORECASE)
    if match:
        return select_item[: match.start()].strip(), match.group(1).lower()
    parts = select_item.rsplit(None, 1)
    if len(parts) == 2 and re.fullmatch(_IDENTIFIER, parts[1], re.IGNORECASE):
        return parts[0].strip(), parts[1].lower()
    return select_item.strip(), None


def _strip_column_qualifiers(expression: str) -> str:
    """Remove optional table/alias prefixes from column references."""
    return re.sub(rf"{_IDENTIFIER}\.{_IDENTIFIER}", r"\2", expression)


def _match_aggregate(expression: str) -> tuple[str, str] | None:
    """Return (function_name, inner_expression) for a single top-level aggregate call."""
    match = re.match(
        r"^(sum|count|avg|min|max)\s*\(",
        expression.strip(),
        re.IGNORECASE,
    )
    if match is None:
        return None

    start = match.end()
    depth = 1
    index = start
    while index < len(expression):
        char = expression[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                inner = expression[start:index].strip()
                if expression[index + 1 :].strip():
                    return None
                if not inner:
                    return None
                return match.group(1).lower(), inner
        index += 1
    return None


def _allowed_columns_for_table(table_name: str) -> frozenset[str]:
    allowed = set(_TABLE_FIELDS[table_name])
    allowed.update(_COMPUTED_FIELDS_BY_TABLE.get(table_name, {}))
    return frozenset(allowed)


def _column_owner_tables(column_name: str, table_names: set[str]) -> set[str]:
    owners = {
        table_name
        for table_name in table_names
        if column_name in _allowed_columns_for_table(table_name)
    }
    return owners


def _matching_computed_field(expression: str) -> str | None:
    normalized_expression = _normalize_expression(expression)
    stripped_expression = _normalize_expression(_strip_column_qualifiers(expression))
    for computed_name, approved_expression in _COMPUTED_EXPRESSIONS.items():
        if (
            normalized_expression == approved_expression
            or stripped_expression == approved_expression
        ):
            return computed_name
    return None


def _validate_qualified_column_refs(
    expression: str,
    table_names: set[str],
    alias_map: dict[str, str],
    columns_used: set[str],
) -> str | None:
    for match in _QUALIFIED_COLUMN.finditer(expression):
        table_ref = match.group(1).lower()
        column_name = match.group(2).lower()
        resolved_table = _resolve_table_name(table_ref, alias_map, table_names)
        if resolved_table is None:
            return f"Unknown table reference: {table_ref}"
        if column_name not in _TABLE_FIELDS[resolved_table]:
            return f"Unknown column: {resolved_table}.{column_name}"
        columns_used.add(column_name)
    return None


def _validate_base_select_expression(
    expression: str,
    table_names: set[str],
    alias_map: dict[str, str],
    columns_used: set[str],
) -> str | None:
    computed_name = _matching_computed_field(expression)
    if computed_name is not None:
        qualified_error = _validate_qualified_column_refs(
            expression,
            table_names,
            alias_map,
            columns_used,
        )
        if qualified_error:
            return qualified_error
        columns_used.add(computed_name)
        _collect_physical_columns_from_expression(
            expression,
            table_names,
            alias_map,
            columns_used,
        )
        return None

    if re.fullmatch(_IDENTIFIER, expression, re.IGNORECASE):
        column_name = expression.lower()
        if column_name in _COMPUTED_EXPRESSIONS:
            if len(table_names) != 1:
                return f"Computed field '{column_name}' requires an unambiguous table context."
            only_table = next(iter(table_names))
            if column_name not in _COMPUTED_FIELDS_BY_TABLE.get(only_table, {}):
                return f"Computed field '{column_name}' is not allowed for table '{only_table}'."
            columns_used.add(column_name)
            return None

        owners = _column_owner_tables(column_name, table_names)
        if not owners:
            return f"Unknown column: {column_name}"
        if len(owners) > 1:
            return f"Ambiguous column reference: {column_name}"
        columns_used.add(column_name)
        return None

    qualified_match = _QUALIFIED_COLUMN_EXACT.fullmatch(expression)
    if qualified_match:
        table_ref = qualified_match.group(1).lower()
        column_name = qualified_match.group(2).lower()
        resolved_table = _resolve_table_name(table_ref, alias_map, table_names)
        if resolved_table is None:
            return f"Unknown table reference: {table_ref}"
        if column_name in _COMPUTED_FIELDS_BY_TABLE.get(resolved_table, {}):
            columns_used.add(column_name)
            return None
        if column_name not in _TABLE_FIELDS[resolved_table]:
            return f"Unknown column: {resolved_table}.{column_name}"
        columns_used.add(column_name)
        return None

    return "Only explicit approved columns or computed fields are allowed in SELECT."


def _validate_select_expression(
    expression: str,
    table_names: set[str],
    alias_map: dict[str, str],
    columns_used: set[str],
) -> str | None:
    aggregate = _match_aggregate(expression)
    if aggregate is not None:
        function_name, inner_expression = aggregate
        if function_name not in ALLOWED_AGGREGATES:
            return "Only explicit approved columns or computed fields are allowed in SELECT."
        return _validate_base_select_expression(
            inner_expression,
            table_names,
            alias_map,
            columns_used,
        )

    return _validate_base_select_expression(
        expression,
        table_names,
        alias_map,
        columns_used,
    )


def _validate_select_item(
    select_item: str,
    table_names: set[str],
    alias_map: dict[str, str],
    columns_used: set[str],
    select_aliases: set[str],
) -> str | None:
    expression, alias = _extract_alias(select_item)
    error = _validate_select_expression(
        expression,
        table_names,
        alias_map,
        columns_used,
    )
    if error:
        return error
    if alias:
        columns_used.add(alias)
        select_aliases.add(alias)
    return None


def _collect_physical_columns_from_expression(
    expression: str,
    table_names: set[str],
    alias_map: dict[str, str],
    columns_used: set[str],
) -> None:
    for match in _QUALIFIED_COLUMN.finditer(expression):
        table_ref = match.group(1).lower()
        column_name = match.group(2).lower()
        resolved_table = _resolve_table_name(table_ref, alias_map, table_names)
        if resolved_table and column_name in _TABLE_FIELDS[resolved_table]:
            columns_used.add(column_name)
        continue

    sql_keywords = {
        "select",
        "from",
        "where",
        "join",
        "on",
        "and",
        "or",
        "as",
        "nullif",
        "limit",
        "offset",
        "inner",
        "left",
        "right",
        "cross",
        "group",
        "by",
        "order",
        "having",
        "distinct",
    }
    if len(table_names) == 1:
        only_table = next(iter(table_names))
        for match in _BARE_IDENTIFIER.finditer(expression):
            token = match.group(1).lower()
            if token in sql_keywords or token in _COMPUTED_EXPRESSIONS:
                continue
            if token in _TABLE_FIELDS[only_table]:
                columns_used.add(token)


def _validate_clause_columns(
    clause: str,
    table_names: set[str],
    alias_map: dict[str, str],
    columns_used: set[str],
    select_aliases: set[str] | None = None,
) -> str | None:
    select_aliases = select_aliases or set()
    for match in _QUALIFIED_COLUMN.finditer(clause):
        table_ref = match.group(1).lower()
        column_name = match.group(2).lower()
        resolved_table = _resolve_table_name(table_ref, alias_map, table_names)
        if resolved_table is None:
            return f"Unknown table reference: {table_ref}"
        if column_name not in _TABLE_FIELDS[resolved_table]:
            return f"Unknown column: {resolved_table}.{column_name}"
        columns_used.add(column_name)

    if len(table_names) == 1:
        only_table = next(iter(table_names))
        for match in _BARE_IDENTIFIER.finditer(clause):
            token = match.group(1).lower()
            if token in select_aliases:
                continue
            if token in _TABLE_FIELDS[only_table]:
                columns_used.add(token)
            elif token in _COMPUTED_EXPRESSIONS:
                return f"Computed field '{token}' must use an approved expression."
            elif token not in {
                "select",
                "from",
                "where",
                "join",
                "on",
                "and",
                "or",
                "as",
                "nullif",
                "limit",
                "offset",
                "inner",
                "left",
                "right",
                "cross",
                "group",
                "by",
                "order",
                "having",
                "distinct",
                "not",
                "is",
                "null",
                "true",
                "false",
                "like",
                "between",
                "in",
                "exists",
                "case",
                "when",
                "then",
                "else",
                "end",
                "asc",
                "desc",
            } and token not in table_names and token not in alias_map:
                if token not in _allowed_columns_for_table(only_table):
                    return f"Unknown column: {token}"
                columns_used.add(token)
    return None


def _contains_restricted_contact_fields(columns_used: set[str]) -> bool:
    return bool(columns_used.intersection(_RESTRICTED_CONTACT_FIELDS))


def _apply_limit(normalized_sql: str) -> tuple[str | None, str | None]:
    base_sql = normalized_sql.rstrip(";").strip()
    limit_match = _LIMIT_TRAILING.search(base_sql)
    limit_value = MAX_ROW_LIMIT

    if limit_match is not None:
        limit_token = limit_match.group("limit")
        if not limit_token.isdigit():
            return None, "LIMIT must use a decimal integer."

        limit_value = int(limit_token)
        if limit_value > MAX_ROW_LIMIT:
            return None, f"LIMIT must be {MAX_ROW_LIMIT} or less."

        offset_token = limit_match.group("offset")
        if offset_token is not None and not offset_token.isdigit():
            return None, "LIMIT OFFSET must use a decimal integer."

        base_sql = base_sql[: limit_match.start()].rstrip()

    return f"{base_sql} LIMIT {limit_value}", None


def validate_readonly_sql(sql: str, *, allow_contact_fields: bool = False) -> dict[str, Any]:
    """Validate a single read-only SELECT statement against approved schema metadata."""
    if sql is None or not str(sql).strip():
        return _validation_result(valid=False, reason="SQL must not be blank.")

    raw_sql = str(sql).strip()
    if _contains_comments(raw_sql):
        return _validation_result(valid=False, reason="SQL comments are not allowed.")

    if _has_multiple_statements(raw_sql):
        return _validation_result(valid=False, reason="Only one SQL statement is allowed.")

    sanitized = _normalize_whitespace(_strip_string_literals(raw_sql))
    forbidden = _contains_forbidden_keywords(sanitized)
    if forbidden:
        return _validation_result(
            valid=False,
            reason=f"Forbidden SQL keyword: {forbidden}.",
        )

    if not re.match(r"^SELECT\b", sanitized, re.IGNORECASE):
        return _validation_result(valid=False, reason="Only SELECT statements are allowed.")

    structure_error = _reject_unsupported_structure(sanitized)
    if structure_error:
        return _validation_result(valid=False, reason=structure_error)

    if not allow_contact_fields and _contains_restricted_contact_references(sanitized):
        return _validation_result(
            valid=False,
            reason="Restricted contact fields require explicit approval.",
        )

    select_match = _SELECT_STAR.search(sanitized)
    if select_match is None:
        return _validation_result(valid=False, reason="Malformed SELECT statement.")

    # DISTINCT/ALL are SELECT modifiers, not part of the first projected expression.
    select_clause = _SELECT_MODIFIERS.sub("", select_match.group("select"), count=1)
    for select_item in _split_select_list(select_clause):
        stripped_item = select_item.strip()
        if stripped_item == "*":
            return _validation_result(valid=False, reason="SELECT * is not allowed.")
        if re.fullmatch(rf"{_IDENTIFIER}\.\*", stripped_item, re.IGNORECASE):
            return _validation_result(valid=False, reason="SELECT * is not allowed.")

    from_match = _FROM_CLAUSE.search(sanitized)
    if from_match is None:
        return _validation_result(valid=False, reason="SELECT must include a FROM clause.")

    tables_used: set[str] = set()
    alias_map: dict[str, str] = {}
    columns_used: set[str] = set()
    select_aliases: set[str] = set()

    base_schema, base_table, base_alias = _parse_table_reference(
        from_match.group("schema"),
        from_match.group("table"),
        from_match.group("alias"),
    )
    if _is_blocked_schema_reference(base_schema, base_table):
        reason = (
            "Schema-qualified table names are not allowed."
            if base_schema
            else "System schema access is not allowed."
        )
        return _validation_result(valid=False, reason=reason)
    if base_table not in _APPROVED_TABLES:
        return _validation_result(valid=False, reason=f"Unknown table: {base_table}")
    tables_used.add(base_table)
    alias_map[base_alias] = base_table

    for join_match in _JOIN_CLAUSE.finditer(sanitized):
        join_schema, join_table, join_alias = _parse_table_reference(
            join_match.group("schema"),
            join_match.group("table"),
            join_match.group("alias"),
        )
        if _is_blocked_schema_reference(join_schema, join_table):
            reason = (
                "Schema-qualified table names are not allowed."
                if join_schema
                else "System schema access is not allowed."
            )
            return _validation_result(
                valid=False,
                reason=reason,
                tables_used=sorted(tables_used),
            )
        if join_table not in _APPROVED_TABLES:
            return _validation_result(
                valid=False,
                reason=f"Unknown table: {join_table}",
                tables_used=sorted(tables_used),
            )
        tables_used.add(join_table)
        alias_map[join_alias] = join_table

        on_clause = _normalize_whitespace(join_match.group("on"))
        on_match = _ON_CONDITION.match(on_clause)
        if on_match is None:
            return _validation_result(
                valid=False,
                reason="JOIN conditions must use a single approved equality predicate.",
                tables_used=sorted(tables_used),
            )

        left_table = _resolve_table_name(on_match.group(1), alias_map, tables_used)
        left_column = on_match.group(2).lower()
        right_table = _resolve_table_name(on_match.group(3), alias_map, tables_used)
        right_column = on_match.group(4).lower()

        if left_table is None or right_table is None:
            return _validation_result(
                valid=False,
                reason="JOIN references an unknown table alias.",
                tables_used=sorted(tables_used),
            )
        if left_column not in _TABLE_FIELDS[left_table]:
            return _validation_result(
                valid=False,
                reason=f"Unknown column: {left_table}.{left_column}",
                tables_used=sorted(tables_used),
            )
        if right_column not in _TABLE_FIELDS[right_table]:
            return _validation_result(
                valid=False,
                reason=f"Unknown column: {right_table}.{right_column}",
                tables_used=sorted(tables_used),
            )
        if not _relationship_is_approved(left_table, left_column, right_table, right_column):
            return _validation_result(
                valid=False,
                reason="JOIN is not an approved relationship.",
                tables_used=sorted(tables_used),
            )
        columns_used.update({left_column, right_column})

    for select_item in _split_select_list(select_clause):
        error = _validate_select_item(
            select_item,
            tables_used,
            alias_map,
            columns_used,
            select_aliases,
        )
        if error:
            return _validation_result(
                valid=False,
                reason=error,
                tables_used=sorted(tables_used),
                columns_used=sorted(columns_used),
            )

    tail_match = re.search(r"\bFROM\b", sanitized, re.IGNORECASE)
    if tail_match:
        trailing_sql = sanitized[tail_match.start() :]
        for clause_name in ("WHERE", "GROUP BY", "HAVING", "ORDER BY"):
            clause_match = re.search(
                rf"\b{clause_name.replace(' ', r'\s+')}\b(.+?)(?=\b(?:WHERE|GROUP|ORDER|HAVING|LIMIT)\b|$)",
                trailing_sql,
                re.IGNORECASE | re.DOTALL,
            )
            if clause_match:
                error = _validate_clause_columns(
                    clause_match.group(1),
                    tables_used,
                    alias_map,
                    columns_used,
                    select_aliases,
                )
                if error:
                    return _validation_result(
                        valid=False,
                        reason=error,
                        tables_used=sorted(tables_used),
                        columns_used=sorted(columns_used),
                    )

    if _contains_restricted_contact_fields(columns_used) and not allow_contact_fields:
        return _validation_result(
            valid=False,
            reason="Restricted contact fields require explicit approval.",
            tables_used=sorted(tables_used),
            columns_used=sorted(columns_used),
        )

    normalized_sql = _normalize_whitespace(raw_sql)
    normalized_sql, limit_error = _apply_limit(normalized_sql)
    if limit_error:
        return _validation_result(
            valid=False,
            reason=limit_error,
            tables_used=sorted(tables_used),
            columns_used=sorted(columns_used),
        )

    return _validation_result(
        valid=True,
        normalized_sql=normalized_sql,
        reason=None,
        tables_used=sorted(tables_used),
        columns_used=sorted(columns_used),
    )
