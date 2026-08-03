#!/usr/bin/env python3
"""Phase 3C: idempotent Store 2 demo portfolio seed (manual local use only).

Creates/refreshes ONLY the known Store 2 demo portfolio rows:
  - 3 customers, 3 accounts, 3 loans, 3 payments, 3 collateral items

Does NOT:
  - modify Store 1 rows
  - create users / change auth
  - broadly DELETE Store 2 data
  - run at application startup

Usage (from backend/ with .env loaded):
  python scripts/seed_phase3c_store2_portfolio.py

Requires store_id=2 to already exist (Phase 2 seed).
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

from database import get_connection  # noqa: E402

STORE_2_ID = 2

DEMO_EMAILS: tuple[str, ...] = (
    "elena.vargas@store2.telleriq.demo",
    "marcus.chen@store2.telleriq.demo",
    "sofia.alvarez@store2.telleriq.demo",
)

DEMO_SERIALS: tuple[str, ...] = (
    "S2-PLT-9001",
    "S2-ELC-9002",
    "S2-VIN-9003",
)

# Relative offsets keep Elena overdue / Marcus due-soon / collateral risk states fresh.
DEMO_PORTFOLIO: tuple[dict[str, Any], ...] = (
    {
        "full_name": "Elena Vargas",
        "phone": "5515558101",
        "email": DEMO_EMAILS[0],
        "account": {
            "account_type": "Checking",
            "balance": 410.00,
            "status": "Active",
        },
        "loan": {
            "loan_type": "Jewelry Loan",
            "current_balance": 8500.00,
            "collateral_value": 10000.00,
            "next_due_offset_days": -15,
            "payment": {
                "amount_due": 480.00,
                "amount_paid": 100.00,
                "due_offset_days": -20,
            },
            "collateral": {
                "item_type": "Jewelry",
                "item_description": "Platinum tennis bracelet",
                "appraised_value": 10000.00,
                "serial_number": DEMO_SERIALS[0],
                "item_status": "Held",
                "forfeiture_offset_days": 12,
            },
        },
    },
    {
        "full_name": "Marcus Chen",
        "phone": "5515558102",
        "email": DEMO_EMAILS[1],
        "account": {
            "account_type": "Checking",
            "balance": 2750.50,
            "status": "Active",
        },
        "loan": {
            "loan_type": "Electronics Loan",
            "current_balance": 2400.00,
            "collateral_value": 4000.00,
            "next_due_offset_days": 7,
            "payment": {
                "amount_due": 350.00,
                "amount_paid": 0.00,
                "due_offset_days": 5,
            },
            "collateral": {
                "item_type": "Electronics",
                "item_description": "Samsung Galaxy Watch Ultra",
                "appraised_value": 400.00,
                "serial_number": DEMO_SERIALS[1],
                "item_status": "Held",
                "forfeiture_offset_days": 120,
            },
        },
    },
    {
        "full_name": "Sofia Alvarez",
        "phone": "5515558103",
        "email": DEMO_EMAILS[2],
        "account": {
            "account_type": "Checking",
            "balance": 1890.00,
            "status": "Active",
        },
        "loan": {
            "loan_type": "Auto Loan",
            "current_balance": 12000.00,
            "collateral_value": 24000.00,
            "next_due_offset_days": 45,
            "payment": {
                "amount_due": 400.00,
                "amount_paid": 400.00,
                "due_offset_days": 45,
            },
            "collateral": {
                "item_type": "Vehicle",
                "item_description": "2019 Subaru Outback",
                "appraised_value": 18000.00,
                "serial_number": DEMO_SERIALS[2],
                "item_status": "Held",
                "forfeiture_offset_days": 90,
            },
        },
    },
)


def offset_date(days: int, *, today: date | None = None) -> date:
    base = today or date.today()
    return base + timedelta(days=days)


def require_store_2(cursor) -> None:
    cursor.execute(
        "SELECT store_id, store_name FROM stores WHERE store_id = %s",
        (STORE_2_ID,),
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(
            "Store 2 is missing. Run Phase 2 seed "
            "(scripts/seed_phase2_demo_users.py) before Phase 3C."
        )


def upsert_customer(cursor, customer: dict[str, Any]) -> int:
    email = customer["email"]
    cursor.execute(
        """
        SELECT customer_id
        FROM customers
        WHERE store_id = %s AND email = %s
        LIMIT 1
        """,
        (STORE_2_ID, email),
    )
    existing = cursor.fetchone()
    if existing:
        customer_id = int(existing["customer_id"])
        cursor.execute(
            """
            UPDATE customers
            SET full_name = %s,
                phone = %s
            WHERE customer_id = %s AND store_id = %s
            """,
            (customer["full_name"], customer["phone"], customer_id, STORE_2_ID),
        )
        return customer_id

    cursor.execute(
        """
        INSERT INTO customers (store_id, full_name, phone, email)
        VALUES (%s, %s, %s, %s)
        """,
        (STORE_2_ID, customer["full_name"], customer["phone"], email),
    )
    return int(cursor.lastrowid)


def upsert_account(cursor, customer_id: int, account: dict[str, Any]) -> int:
    cursor.execute(
        """
        SELECT account_id
        FROM accounts
        WHERE store_id = %s
          AND customer_id = %s
          AND account_type = %s
        LIMIT 1
        """,
        (STORE_2_ID, customer_id, account["account_type"]),
    )
    existing = cursor.fetchone()
    if existing:
        account_id = int(existing["account_id"])
        cursor.execute(
            """
            UPDATE accounts
            SET balance = %s,
                status = %s
            WHERE account_id = %s AND store_id = %s
            """,
            (account["balance"], account["status"], account_id, STORE_2_ID),
        )
        return account_id

    cursor.execute(
        """
        INSERT INTO accounts (store_id, customer_id, account_type, balance, status)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            STORE_2_ID,
            customer_id,
            account["account_type"],
            account["balance"],
            account["status"],
        ),
    )
    return int(cursor.lastrowid)


def upsert_loan(
    cursor,
    customer_id: int,
    loan: dict[str, Any],
    *,
    today: date,
) -> int:
    next_due = offset_date(loan["next_due_offset_days"], today=today)
    cursor.execute(
        """
        SELECT loan_id
        FROM loans
        WHERE store_id = %s
          AND customer_id = %s
          AND loan_type = %s
        LIMIT 1
        """,
        (STORE_2_ID, customer_id, loan["loan_type"]),
    )
    existing = cursor.fetchone()
    if existing:
        loan_id = int(existing["loan_id"])
        cursor.execute(
            """
            UPDATE loans
            SET current_balance = %s,
                collateral_value = %s,
                next_due_date = %s
            WHERE loan_id = %s AND store_id = %s
            """,
            (
                loan["current_balance"],
                loan["collateral_value"],
                next_due,
                loan_id,
                STORE_2_ID,
            ),
        )
        return loan_id

    cursor.execute(
        """
        INSERT INTO loans (
            store_id, customer_id, loan_type,
            current_balance, collateral_value, next_due_date
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            STORE_2_ID,
            customer_id,
            loan["loan_type"],
            loan["current_balance"],
            loan["collateral_value"],
            next_due,
        ),
    )
    return int(cursor.lastrowid)


def payment_natural_key(payment: dict[str, Any]) -> tuple[float, float]:
    """Stable Phase 3C payment identity without a schema marker column.

    payments has no dedicated natural-key column. Amounts in DEMO_PORTFOLIO are
    fixed per demo loan, so (amount_due, amount_paid) together with the resolved
    demo loan uniquely identify the Phase 3C payment. Lookups never fall back to
    "oldest payment on loan", so unrelated payments on the same loan are never
    updated. Re-runs refresh due_date only on the matching signature row.
    """
    return (float(payment["amount_due"]), float(payment["amount_paid"]))


def upsert_payment(
    cursor,
    loan_id: int,
    payment: dict[str, Any],
    *,
    today: date,
) -> int:
    due_date = offset_date(payment["due_offset_days"], today=today)
    amount_due, amount_paid = payment_natural_key(payment)
    cursor.execute(
        """
        SELECT payment_id
        FROM payments
        WHERE store_id = %s
          AND loan_id = %s
          AND amount_due = %s
          AND amount_paid = %s
        LIMIT 1
        """,
        (STORE_2_ID, loan_id, amount_due, amount_paid),
    )
    existing = cursor.fetchone()
    if existing:
        payment_id = int(existing["payment_id"])
        cursor.execute(
            """
            UPDATE payments
            SET due_date = %s
            WHERE payment_id = %s
              AND store_id = %s
              AND loan_id = %s
              AND amount_due = %s
              AND amount_paid = %s
            """,
            (
                due_date,
                payment_id,
                STORE_2_ID,
                loan_id,
                amount_due,
                amount_paid,
            ),
        )
        return payment_id

    cursor.execute(
        """
        INSERT INTO payments (store_id, loan_id, amount_due, amount_paid, due_date)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            STORE_2_ID,
            loan_id,
            amount_due,
            amount_paid,
            due_date,
        ),
    )
    return int(cursor.lastrowid)


def upsert_collateral(
    cursor,
    loan_id: int,
    collateral: dict[str, Any],
    *,
    today: date,
) -> int:
    forfeiture = offset_date(collateral["forfeiture_offset_days"], today=today)
    cursor.execute(
        """
        SELECT item_id, store_id
        FROM collateral_items
        WHERE serial_number = %s
        LIMIT 1
        """,
        (collateral["serial_number"],),
    )
    existing = cursor.fetchone()
    if existing:
        if int(existing["store_id"]) != STORE_2_ID:
            raise RuntimeError(
                f"Collateral serial {collateral['serial_number']!r} already belongs "
                f"to store_id={existing['store_id']}; refusing to overwrite."
            )
        item_id = int(existing["item_id"])
        cursor.execute(
            """
            UPDATE collateral_items
            SET loan_id = %s,
                item_type = %s,
                item_description = %s,
                appraised_value = %s,
                item_status = %s,
                forfeiture_date = %s,
                store_id = %s
            WHERE item_id = %s AND store_id = %s
            """,
            (
                loan_id,
                collateral["item_type"],
                collateral["item_description"],
                collateral["appraised_value"],
                collateral["item_status"],
                forfeiture,
                STORE_2_ID,
                item_id,
                STORE_2_ID,
            ),
        )
        return item_id

    cursor.execute(
        """
        INSERT INTO collateral_items (
            store_id, loan_id, item_type, item_description,
            appraised_value, serial_number, item_status, forfeiture_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            STORE_2_ID,
            loan_id,
            collateral["item_type"],
            collateral["item_description"],
            collateral["appraised_value"],
            collateral["serial_number"],
            collateral["item_status"],
            forfeiture,
        ),
    )
    return int(cursor.lastrowid)


def seed_portfolio(cursor, *, today: date | None = None) -> dict[str, list[int]]:
    """Upsert the Phase 3C Store 2 demo portfolio using the given cursor."""
    seed_day = today or date.today()
    require_store_2(cursor)

    created = {
        "customers": [],
        "accounts": [],
        "loans": [],
        "payments": [],
        "collateral_items": [],
    }

    for customer in DEMO_PORTFOLIO:
        customer_id = upsert_customer(cursor, customer)
        created["customers"].append(customer_id)

        account_id = upsert_account(cursor, customer_id, customer["account"])
        created["accounts"].append(account_id)

        loan = customer["loan"]
        loan_id = upsert_loan(cursor, customer_id, loan, today=seed_day)
        created["loans"].append(loan_id)

        payment_id = upsert_payment(cursor, loan_id, loan["payment"], today=seed_day)
        created["payments"].append(payment_id)

        item_id = upsert_collateral(
            cursor, loan_id, loan["collateral"], today=seed_day
        )
        created["collateral_items"].append(item_id)

    return created


def _scalar(cursor, sql: str, params: tuple | None = None) -> int:
    cursor.execute(sql, params or ())
    row = cursor.fetchone()
    if not row:
        return 0
    return int(next(iter(row.values())))


def _demo_loan_match_clause() -> tuple[str, tuple[Any, ...]]:
    """SQL OR-clause matching exactly the three Phase 3C (email, loan_type) pairs."""
    parts: list[str] = []
    params: list[Any] = []
    for customer in DEMO_PORTFOLIO:
        parts.append("(c.email = %s AND l.loan_type = %s)")
        params.extend([customer["email"], customer["loan"]["loan_type"]])
    return "(" + " OR ".join(parts) + ")", tuple(params)


def _demo_payment_match_clause() -> tuple[str, tuple[Any, ...]]:
    """SQL OR-clause matching Phase 3C payments by loan key + amount signature."""
    parts: list[str] = []
    params: list[Any] = []
    for customer in DEMO_PORTFOLIO:
        amount_due, amount_paid = payment_natural_key(customer["loan"]["payment"])
        parts.append(
            "(c.email = %s AND l.loan_type = %s "
            "AND p.amount_due = %s AND p.amount_paid = %s)"
        )
        params.extend(
            [
                customer["email"],
                customer["loan"]["loan_type"],
                amount_due,
                amount_paid,
            ]
        )
    return "(" + " OR ".join(parts) + ")", tuple(params)


def verify_seed(cursor) -> dict[str, int]:
    """Fail closed if the Phase 3C demo portfolio is incomplete or cross-owned.

    All counts and dashboard-style metrics are scoped to Phase 3C natural keys
    only. Unrelated Store 2 rows must not affect pass/fail.
    """
    email_placeholders = ", ".join(["%s"] * len(DEMO_EMAILS))
    serial_placeholders = ", ".join(["%s"] * len(DEMO_SERIALS))
    loan_match, loan_params = _demo_loan_match_clause()
    payment_match, payment_params = _demo_payment_match_clause()

    counts = {
        "customers": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n FROM customers
            WHERE store_id = %s AND email IN ({email_placeholders})
            """,
            (STORE_2_ID, *DEMO_EMAILS),
        ),
        "accounts": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n
            FROM accounts a
            JOIN customers c
              ON c.customer_id = a.customer_id AND c.store_id = a.store_id
            WHERE a.store_id = %s
              AND c.email IN ({email_placeholders})
              AND a.account_type = %s
            """,
            (STORE_2_ID, *DEMO_EMAILS, "Checking"),
        ),
        "loans": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n
            FROM loans l
            JOIN customers c
              ON c.customer_id = l.customer_id AND c.store_id = l.store_id
            WHERE l.store_id = %s
              AND {loan_match}
            """,
            (STORE_2_ID, *loan_params),
        ),
        "payments": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n
            FROM payments p
            JOIN loans l
              ON l.loan_id = p.loan_id AND l.store_id = p.store_id
            JOIN customers c
              ON c.customer_id = l.customer_id AND c.store_id = l.store_id
            WHERE p.store_id = %s
              AND {payment_match}
            """,
            (STORE_2_ID, *payment_params),
        ),
        "collateral_items": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n FROM collateral_items
            WHERE store_id = %s AND serial_number IN ({serial_placeholders})
            """,
            (STORE_2_ID, *DEMO_SERIALS),
        ),
    }

    expected = {
        "customers": 3,
        "accounts": 3,
        "loans": 3,
        "payments": 3,
        "collateral_items": 3,
    }
    for key, want in expected.items():
        if counts[key] != want:
            raise RuntimeError(
                f"Phase 3C demo {key} count is {counts[key]}, expected {want}."
            )

    # Dashboard-style expectations from Phase 3C demo rows only.
    metrics = {
        "total_customers": counts["customers"],
        "overdue_payments": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n
            FROM payments p
            JOIN loans l
              ON l.loan_id = p.loan_id AND l.store_id = p.store_id
            JOIN customers c
              ON c.customer_id = l.customer_id AND c.store_id = l.store_id
            WHERE p.store_id = %s
              AND {payment_match}
              AND p.due_date < CURDATE()
              AND p.amount_paid < p.amount_due
            """,
            (STORE_2_ID, *payment_params),
        ),
        "high_risk_loans": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n
            FROM loans l
            JOIN customers c
              ON c.customer_id = l.customer_id AND c.store_id = l.store_id
            WHERE l.store_id = %s
              AND {loan_match}
              AND (l.current_balance / l.collateral_value) * 100 >= 75
            """,
            (STORE_2_ID, *loan_params),
        ),
        "collateral_at_risk": _scalar(
            cursor,
            f"""
            SELECT COUNT(*) AS n
            FROM collateral_items ci
            JOIN loans l
              ON ci.loan_id = l.loan_id AND ci.store_id = l.store_id
            WHERE ci.store_id = %s
              AND ci.serial_number IN ({serial_placeholders})
              AND (
                ci.forfeiture_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
                OR (l.current_balance / l.collateral_value) * 100 >= 75
              )
            """,
            (STORE_2_ID, *DEMO_SERIALS),
        ),
    }

    expected_metrics = {
        "total_customers": 3,
        "overdue_payments": 1,
        "high_risk_loans": 1,
        "collateral_at_risk": 1,
    }
    for key, want in expected_metrics.items():
        if metrics[key] != want:
            raise RuntimeError(
                f"Phase 3C demo metric {key} is {metrics[key]}, expected {want}."
            )

    violations = 0
    violations += _scalar(
        cursor,
        f"""
        SELECT COUNT(*) AS n
        FROM accounts a
        JOIN customers c ON a.customer_id = c.customer_id
        JOIN customers demo
          ON demo.customer_id = a.customer_id AND demo.store_id = a.store_id
        WHERE a.store_id = %s
          AND demo.email IN ({email_placeholders})
          AND a.account_type = %s
          AND (c.store_id <> %s OR a.store_id <> c.store_id)
        """,
        (STORE_2_ID, *DEMO_EMAILS, "Checking", STORE_2_ID),
    )
    violations += _scalar(
        cursor,
        f"""
        SELECT COUNT(*) AS n
        FROM loans l
        JOIN customers c ON l.customer_id = c.customer_id
        WHERE l.store_id = %s
          AND {loan_match}
          AND (c.store_id <> %s OR l.store_id <> c.store_id)
        """,
        (STORE_2_ID, *loan_params, STORE_2_ID),
    )
    violations += _scalar(
        cursor,
        f"""
        SELECT COUNT(*) AS n
        FROM payments p
        JOIN loans l ON p.loan_id = l.loan_id
        JOIN customers c
          ON c.customer_id = l.customer_id AND c.store_id = l.store_id
        WHERE p.store_id = %s
          AND {payment_match}
          AND (l.store_id <> %s OR p.store_id <> l.store_id)
        """,
        (STORE_2_ID, *payment_params, STORE_2_ID),
    )
    violations += _scalar(
        cursor,
        f"""
        SELECT COUNT(*) AS n
        FROM collateral_items ci
        JOIN loans l ON ci.loan_id = l.loan_id
        WHERE ci.store_id = %s
          AND ci.serial_number IN ({serial_placeholders})
          AND (l.store_id <> %s OR ci.store_id <> l.store_id)
        """,
        (STORE_2_ID, *DEMO_SERIALS, STORE_2_ID),
    )
    if violations:
        raise RuntimeError(
            f"Cross-store ownership violations detected: {violations}."
        )

    return {**counts, **metrics, "ownership_violations": 0}


def run_seed(*, today: date | None = None) -> dict[str, Any]:
    """Execute Phase 3C seed in a single transaction; rollback on any failure."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        try:
            # Explicit transaction boundary for engines/settings that autocommit.
            cursor.execute("START TRANSACTION")
            created = seed_portfolio(cursor, today=today)
            metrics = verify_seed(cursor)
            conn.commit()
            return {"created": created, "metrics": metrics}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    finally:
        conn.close()


def main() -> int:
    required = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(
            "Missing required DB environment variables: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    try:
        result = run_seed()
    except Exception as exc:
        print(f"Phase 3C Store 2 portfolio seed FAILED and was rolled back: {exc}", file=sys.stderr)
        return 1

    metrics = result["metrics"]
    print("Phase 3C Store 2 portfolio seed complete.")
    print(
        "Demo customers: Elena Vargas, Marcus Chen, Sofia Alvarez "
        f"(store_id={STORE_2_ID})."
    )
    print(
        "Verified counts/metrics: "
        f"customers={metrics['customers']}, "
        f"accounts={metrics['accounts']}, "
        f"loans={metrics['loans']}, "
        f"payments={metrics['payments']}, "
        f"collateral={metrics['collateral_items']}, "
        f"overdue={metrics['overdue_payments']}, "
        f"high_risk={metrics['high_risk_loans']}, "
        f"collateral_at_risk={metrics['collateral_at_risk']}."
    )
    print("Store 1 rows were not modified. No broad Store 2 deletes were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
