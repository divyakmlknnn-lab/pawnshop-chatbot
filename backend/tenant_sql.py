"""Deterministic fail-closed tenant SQL scoping for MCP execute_safe_sql."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from sql_validation import (
    _FROM_CLAUSE,
    _JOIN_CLAUSE,
    _parse_table_reference,
    validate_readonly_sql,
)

TRUSTED_STORE_ENV = "TELLERIQ_TRUSTED_STORE_ID"

TENANT_BUSINESS_TABLES: frozenset[str] = frozenset(
    {
        "customers",
        "accounts",
        "loans",
        "payments",
        "collateral_items",
    }
)

# FROM/JOIN alias capture can greedily consume the next SQL keyword when no
# explicit alias is present (e.g. FROM customers WHERE ...).
_SQL_CLAUSE_KEYWORDS: frozenset[str] = frozenset(
    {
        "where",
        "group",
        "order",
        "having",
        "limit",
        "join",
        "inner",
        "left",
        "right",
        "cross",
        "on",
        "as",
        "union",
        "intersect",
        "except",
    }
)


def _effective_alias(table_name: str, alias_name: str) -> str:
    if alias_name.lower() in _SQL_CLAUSE_KEYWORDS:
        return table_name
    return alias_name

_JOIN_TYPE_PREFIX = re.compile(
    r"^\s*(?P<kind>INNER|LEFT|RIGHT|CROSS)?\s*JOIN\b",
    re.IGNORECASE,
)
_WHERE_CLAUSE = re.compile(
    r"\bWHERE\b(?P<where>.+?)(?=\b(?:GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_BEFORE_TAIL = re.compile(
    r"\b(?:GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b",
    re.IGNORECASE,
)


def tenancy_enforcement_enabled() -> bool:
    return os.environ.get("TENANCY_ENFORCEMENT", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def parse_trusted_store_id(raw: Any) -> int | None:
    """Return a positive int store id, or None if missing/invalid."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    text = str(raw).strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def read_trusted_store_id_from_env(
    env: dict[str, str] | None = None,
) -> int | None:
    source = os.environ if env is None else env
    return parse_trusted_store_id(source.get(TRUSTED_STORE_ENV))


def clear_unlaunched_trusted_store_id(*, present_at_process_launch: bool) -> None:
    """Drop TELLERIQ_TRUSTED_STORE_ID unless it was in the process launch env.

    Used after load_dotenv() so a value present only in a .env file cannot
    become trusted tenant identity. Explicit MCP client launch env is kept.
    """
    if not present_at_process_launch:
        os.environ.pop(TRUSTED_STORE_ENV, None)


@dataclass
class TenantScopeResult:
    applied: bool
    sql: str | None
    original_sql: str
    store_id: int | None = None
    reason: str | None = None
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "store_id": self.store_id,
            "original_sql": self.original_sql,
            "scoped_sql": self.sql if self.applied else None,
            "reason": self.reason,
            "validation": self.validation,
        }


def _join_kind(join_match: re.Match[str]) -> str:
    prefix = _JOIN_TYPE_PREFIX.match(join_match.group(0))
    if prefix is None:
        return "inner"
    kind = (prefix.group("kind") or "INNER").lower()
    if kind == "left":
        return "left"
    if kind == "right":
        return "right"
    if kind == "cross":
        return "cross"
    return "inner"


def _predicate(alias: str, store_id: int) -> str:
    return f"{alias}.store_id = {store_id:d}"


def _splice_before_remainder(prefix: str, remainder: str) -> str:
    """Join rewritten SQL to the unconsumed tail with exactly one boundary space.

    Clause regex matches often absorb trailing whitespace into the replaced
    span while leaving the next keyword (ORDER BY / LIMIT / …) at remainder[0].
    Stripping the replacement body without restoring that boundary produces
    tokens like ``1ORDER`` or ``1LIMIT``.
    """
    if not remainder:
        return prefix
    if prefix and remainder[0].isspace():
        return prefix + remainder
    if not prefix:
        return remainder
    return prefix + " " + remainder


def inject_tenant_predicates(sql: str, store_id: int) -> str:
    """Return SQL with deterministic store predicates for all tenant aliases."""
    if parse_trusted_store_id(store_id) is None:
        raise ValueError("trusted store_id must be a positive integer.")

    working = sql.strip().rstrip(";").strip()
    from_match = _FROM_CLAUSE.search(working)
    if from_match is None:
        raise ValueError("SELECT must include a FROM clause.")

    _, base_table, parsed_base_alias = _parse_table_reference(
        from_match.group("schema"),
        from_match.group("table"),
        from_match.group("alias"),
    )
    base_alias = _effective_alias(base_table, parsed_base_alias)

    where_aliases: list[str] = []
    if base_table in TENANT_BUSINESS_TABLES:
        where_aliases.append(base_alias)

    # 1) OUTER JOIN tenant aliases → ON clause (edit spans from end to start).
    # RIGHT JOIN is fail-closed: Safe SQL may accept it, but rewrite would
    # incorrectly push the preserved-side predicate into WHERE.
    on_replacements: list[tuple[int, int, str]] = []
    for join_match in _JOIN_CLAUSE.finditer(working):
        kind = _join_kind(join_match)
        if kind == "right":
            raise ValueError(
                "RIGHT JOIN is not supported under tenant enforcement."
            )
        _, join_table, parsed_join_alias = _parse_table_reference(
            join_match.group("schema"),
            join_match.group("table"),
            join_match.group("alias"),
        )
        join_alias = _effective_alias(join_table, parsed_join_alias)
        if join_table not in TENANT_BUSINESS_TABLES:
            continue
        on_sql = join_match.group("on").strip()
        if kind == "inner":
            where_aliases.append(join_alias)
            continue
        if kind != "left":
            raise ValueError(f"Unsupported JOIN kind for tenant scoping: {kind}")
        predicate = _predicate(join_alias, store_id)
        if re.search(
            rf"(?i)\b{re.escape(join_alias)}\.store_id\s*=\s*{store_id:d}\b",
            on_sql,
        ):
            continue
        on_replacements.append(
            (join_match.start("on"), join_match.end("on"), f"{on_sql} AND {predicate}")
        )

    for start, end, new_on in reversed(on_replacements):
        working = _splice_before_remainder(working[:start] + new_on, working[end:])

    # 2) FROM + INNER JOIN tenant aliases → WHERE
    seen: set[str] = set()
    ordered_where_aliases: list[str] = []
    for alias in where_aliases:
        if alias not in seen:
            seen.add(alias)
            ordered_where_aliases.append(alias)

    if not ordered_where_aliases:
        return working

    tenant_where = " AND ".join(
        _predicate(alias, store_id) for alias in ordered_where_aliases
    )

    where_match = _WHERE_CLAUSE.search(working)
    if where_match:
        original_where = where_match.group("where").strip()
        if all(
            re.search(
                rf"(?i)\b{re.escape(alias)}\.store_id\s*=\s*{store_id:d}\b",
                original_where,
            )
            for alias in ordered_where_aliases
        ):
            return working
        scoped_where = f"({original_where}) AND {tenant_where}"
        prefix = working[: where_match.start()] + f"WHERE {scoped_where}"
        return _splice_before_remainder(prefix, working[where_match.end() :])

    tail = _BEFORE_TAIL.search(working)
    if tail:
        prefix = working[: tail.start()].rstrip() + f" WHERE {tenant_where}"
        return _splice_before_remainder(prefix, working[tail.start() :])
    return working.rstrip() + f" WHERE {tenant_where}"


def apply_tenant_scope(
    sql: str,
    store_id: int,
    *,
    prevalidated: dict[str, Any] | None = None,
) -> TenantScopeResult:
    """Validate → inject → revalidate. Fail closed on any error."""
    original = (sql or "").strip()
    trusted = parse_trusted_store_id(store_id)
    if trusted is None:
        return TenantScopeResult(
            applied=False,
            sql=None,
            original_sql=original,
            store_id=None,
            reason="Trusted store_id must be a positive integer.",
        )

    first = prevalidated or validate_readonly_sql(original)
    if not first.get("valid"):
        return TenantScopeResult(
            applied=False,
            sql=None,
            original_sql=original,
            store_id=trusted,
            reason=first.get("reason") or "SQL failed validation before tenant scoping.",
            validation=first,
        )

    base_sql = first.get("normalized_sql") or original
    try:
        scoped = inject_tenant_predicates(base_sql, trusted)
    except ValueError as exc:
        return TenantScopeResult(
            applied=False,
            sql=None,
            original_sql=original,
            store_id=trusted,
            reason=str(exc),
            validation=first,
        )

    second = validate_readonly_sql(scoped, allow_tenant_predicates=True)
    if not second.get("valid"):
        return TenantScopeResult(
            applied=False,
            sql=None,
            original_sql=original,
            store_id=trusted,
            reason=second.get("reason") or "Scoped SQL failed revalidation.",
            validation=second,
        )

    return TenantScopeResult(
        applied=True,
        sql=second.get("normalized_sql") or scoped,
        original_sql=original,
        store_id=trusted,
        reason=None,
        validation=second,
    )
