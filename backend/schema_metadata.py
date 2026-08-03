"""Read-only approved schema metadata for TellerIQ MCP / safe SQL layers."""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any

from database import REQUIRED_SCHEMA, TABLES


class UnknownTableError(KeyError):
    """Raised when a table name is not in the approved schema."""


def _freeze_record(record: dict[str, str]) -> MappingProxyType[str, str]:
    return MappingProxyType(dict(record))


def _freeze_records(
    records: tuple[dict[str, str], ...],
) -> tuple[MappingProxyType[str, str], ...]:
    return tuple(_freeze_record(record) for record in records)

_APPROVED_TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "accounts": (
        "account_id",
        "customer_id",
        "account_type",
        "balance",
        "status",
    ),
    "collateral_items": (
        "item_id",
        "loan_id",
        "item_type",
        "item_description",
        "appraised_value",
        "serial_number",
        "item_status",
        "forfeiture_date",
    ),
    "customers": (
        "customer_id",
        "full_name",
        "phone",
        "email",
    ),
    "loans": (
        "loan_id",
        "customer_id",
        "loan_type",
        "current_balance",
        "collateral_value",
        "next_due_date",
    ),
    "payments": (
        "payment_id",
        "loan_id",
        "amount_due",
        "amount_paid",
        "due_date",
    ),
}

_APPROVED_RELATIONSHIPS: tuple[MappingProxyType[str, str], ...] = _freeze_records(
    (
        {
            "from_table": "accounts",
            "from_column": "customer_id",
            "to_table": "customers",
            "to_column": "customer_id",
        },
        {
            "from_table": "loans",
            "from_column": "customer_id",
            "to_table": "customers",
            "to_column": "customer_id",
        },
        {
            "from_table": "payments",
            "from_column": "loan_id",
            "to_table": "loans",
            "to_column": "loan_id",
        },
        {
            "from_table": "collateral_items",
            "from_column": "loan_id",
            "to_table": "loans",
            "to_column": "loan_id",
        },
    )
)

_APPROVED_COMPUTED_FIELDS: tuple[MappingProxyType[str, str], ...] = _freeze_records(
    (
        {
            "name": "remaining_due",
            "table": "payments",
            "expression": "amount_due - amount_paid",
            "description": "Unpaid portion of a scheduled payment.",
        },
        {
            "name": "ltv_percent",
            "table": "loans",
            "expression": "current_balance / NULLIF(collateral_value, 0) * 100",
            "description": "Loan-to-value percentage for a loan.",
        },
    )
)

_RESTRICTED_CONTACT_FIELDS: frozenset[str] = frozenset({"phone", "email"})

_CONTACT_EXCLUSION_NOTE = (
    "phone and email are excluded unless the user explicitly requests contact details."
)


def _freeze_profile(profile: dict[str, Any]) -> MappingProxyType[str, Any]:
    return MappingProxyType(
        {
            "name": profile["name"],
            "category": profile["category"],
            "recommended_fields": tuple(profile["recommended_fields"]),
            "related_tables": tuple(profile["related_tables"]),
            "computed_aliases": tuple(profile["computed_aliases"]),
            "exclude_contact_fields_unless_requested": True,
            "notes": profile["notes"],
        }
    )


_PROJECTION_PROFILE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "name": "customer_list",
        "category": "customer list",
        "recommended_fields": ("customer_id", "full_name"),
        "related_tables": ("customers",),
        "computed_aliases": (),
        "notes": (
            "Compact customer listing. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
    {
        "name": "customer_detail",
        "category": "single-entity customer lookup",
        "recommended_fields": (
            "customer_id",
            "full_name",
            "loan_type",
            "current_balance",
            "collateral_value",
            "ltv_percent",
            "next_due_date",
            "amount_due",
            "amount_paid",
            "remaining_due",
            "due_date",
            "item_type",
            "item_description",
            "appraised_value",
            "item_status",
        ),
        "related_tables": ("customers", "loans", "payments", "collateral_items"),
        "computed_aliases": ("ltv_percent", "remaining_due"),
        "notes": (
            "Customer identity plus connected loan, payment, and collateral context. "
            "Omit irrelevant connected fields when not needed. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
    {
        "name": "overdue_payments",
        "category": "list/operational overdue or missed payments",
        "recommended_fields": (
            "customer_id",
            "full_name",
            "loan_type",
            "amount_due",
            "amount_paid",
            "remaining_due",
            "due_date",
            "ltv_percent",
        ),
        "related_tables": ("customers", "loans", "payments"),
        "computed_aliases": ("remaining_due", "ltv_percent"),
        "notes": (
            "Business-complete overdue/missed payment rows. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
    {
        "name": "due_soon",
        "category": "list/operational payments due soon",
        "recommended_fields": (
            "customer_id",
            "full_name",
            "loan_type",
            "amount_due",
            "amount_paid",
            "remaining_due",
            "due_date",
        ),
        "related_tables": ("customers", "loans", "payments"),
        "computed_aliases": ("remaining_due",),
        "notes": (
            "Upcoming unpaid payment rows with customer and loan context. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
    {
        "name": "high_risk_loans",
        "category": "list/operational high-risk loans",
        "recommended_fields": (
            "customer_id",
            "full_name",
            "loan_type",
            "current_balance",
            "collateral_value",
            "ltv_percent",
            "next_due_date",
        ),
        "related_tables": ("customers", "loans"),
        "computed_aliases": ("ltv_percent",),
        "notes": (
            "High LTV / high-risk loan listing with customer context. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
    {
        "name": "collateral_detail",
        "category": "list/lookup collateral",
        "recommended_fields": (
            "customer_id",
            "full_name",
            "item_type",
            "item_description",
            "appraised_value",
            "item_status",
        ),
        "related_tables": ("customers", "loans", "collateral_items"),
        "computed_aliases": (),
        "notes": (
            "Collateral item detail with owning customer context. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
    {
        "name": "aggregate_ranking",
        "category": "aggregate/ranking",
        "recommended_fields": ("customer_id", "full_name"),
        "related_tables": ("customers", "loans", "payments"),
        "computed_aliases": ("total_overdue",),
        "notes": (
            "Return entity identifier/name plus one clearly aliased aggregate metric "
            "(for example total_overdue). Include ORDER BY the metric and LIMIT when "
            "appropriate. Keep the SELECT compact; do not dump full payment or "
            "collateral row detail. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
    {
        "name": "aggregate_summary",
        "category": "count/summary",
        "recommended_fields": (),
        "related_tables": ("customers", "loans", "payments", "collateral_items", "accounts"),
        "computed_aliases": ("total_overdue", "missed_payment_count"),
        "notes": (
            "Return one clearly aliased metric (COUNT/SUM/AVG/MAX/MIN). Use GROUP BY "
            "only when the user asks for a breakdown. Keep the result compact. "
            + _CONTACT_EXCLUSION_NOTE
        ),
    },
)

_PROJECTION_PROFILES: tuple[MappingProxyType[str, Any], ...] = tuple(
    _freeze_profile(profile) for profile in _PROJECTION_PROFILE_DEFS
)

# Cross-check verified database metadata: approved tables align with REQUIRED_SCHEMA.
for _table in _APPROVED_TABLE_FIELDS:
    if _table not in REQUIRED_SCHEMA:
        raise RuntimeError(f"Approved table '{_table}' missing from database.REQUIRED_SCHEMA")

# Trace-query column hints from database.TABLES remain a subset of approved fields.
for _table, _columns in TABLES.items():
    if _table not in _APPROVED_TABLE_FIELDS:
        continue
    approved = set(_APPROVED_TABLE_FIELDS[_table])
    missing = [column for column in _columns if column not in approved]
    if missing:
        raise RuntimeError(
            f"database.TABLES['{_table}'] columns not approved: {', '.join(missing)}"
        )

_TABLE_RELATIONSHIPS: dict[str, tuple[MappingProxyType[str, str], ...]] = {
    table: tuple(
        relationship
        for relationship in _APPROVED_RELATIONSHIPS
        if relationship["from_table"] == table or relationship["to_table"] == table
    )
    for table in _APPROVED_TABLE_FIELDS
}

_TABLE_COMPUTED_FIELDS: dict[str, tuple[MappingProxyType[str, str], ...]] = {
    table: tuple(field for field in _APPROVED_COMPUTED_FIELDS if field["table"] == table)
    for table in _APPROVED_TABLE_FIELDS
}

_FROZEN_APPROVED_SCHEMA: MappingProxyType[str, Any] = MappingProxyType(
    {
        "tables": MappingProxyType(
            {
                table: MappingProxyType(
                    {
                        "fields": fields,
                        "restricted_contact_fields": tuple(
                            column
                            for column in fields
                            if column in _RESTRICTED_CONTACT_FIELDS
                        ),
                        "relationships": _TABLE_RELATIONSHIPS[table],
                        "computed_fields": _TABLE_COMPUTED_FIELDS[table],
                    }
                )
                for table, fields in _APPROVED_TABLE_FIELDS.items()
            }
        ),
        "relationships": _APPROVED_RELATIONSHIPS,
        "computed_fields": _APPROVED_COMPUTED_FIELDS,
        "restricted_contact_fields": _RESTRICTED_CONTACT_FIELDS,
        "projection_profiles": _PROJECTION_PROFILES,
        "source_metadata": MappingProxyType(
            {
                "required_schema_tables": tuple(REQUIRED_SCHEMA.keys()),
                "trace_query_tables": tuple(TABLES.keys()),
            }
        ),
    }
)


def list_approved_tables() -> list[str]:
    """Return sorted approved table names (a new list on each call)."""
    return sorted(_APPROVED_TABLE_FIELDS.keys())


def _serialize_projection_profile(profile: MappingProxyType[str, Any]) -> dict[str, Any]:
    return {
        "name": profile["name"],
        "category": profile["category"],
        "recommended_fields": list(profile["recommended_fields"]),
        "related_tables": list(profile["related_tables"]),
        "computed_aliases": list(profile["computed_aliases"]),
        "exclude_contact_fields_unless_requested": bool(
            profile["exclude_contact_fields_unless_requested"]
        ),
        "notes": profile["notes"],
    }


def list_projection_profiles() -> list[dict[str, Any]]:
    """Return deep-copied advisory domain projection profiles."""
    return [_serialize_projection_profile(profile) for profile in _PROJECTION_PROFILES]


def describe_approved_table(table_name: str) -> dict[str, Any]:
    """Return a deep copy describing one approved table."""
    normalized = (table_name or "").strip()
    if normalized not in _APPROVED_TABLE_FIELDS:
        raise UnknownTableError(f"Unknown approved table: {table_name}")

    table_meta = _FROZEN_APPROVED_SCHEMA["tables"][normalized]
    return {
        "table": normalized,
        "fields": list(table_meta["fields"]),
        "relationships": [dict(relationship) for relationship in table_meta["relationships"]],
        "computed_fields": [dict(field) for field in table_meta["computed_fields"]],
        "restricted_contact_fields": list(table_meta["restricted_contact_fields"]),
    }


def get_approved_schema() -> dict[str, Any]:
    """Return a deep copy of the full approved schema metadata."""
    return deepcopy(
        {
            "tables": {
                table: describe_approved_table(table)
                for table in _APPROVED_TABLE_FIELDS
            },
            "relationships": [dict(relationship) for relationship in _APPROVED_RELATIONSHIPS],
            "computed_fields": [dict(field) for field in _APPROVED_COMPUTED_FIELDS],
            "restricted_contact_fields": sorted(_RESTRICTED_CONTACT_FIELDS),
            "projection_profiles": list_projection_profiles(),
        }
    )
