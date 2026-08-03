#!/usr/bin/env python3
"""One-shot local seed for Phase 2 demo identity (NOT portfolio data).

Creates:
  - Store 2 registry row (stores table only)
  - Store 1 demo user A
  - Store 2 demo user B

Does NOT create Store 2 customers/accounts/loans/payments/collateral.

Usage (from backend/ with .env loaded):
  python scripts/seed_phase2_demo_users.py

Optional env:
  DEMO_USER_A_PASSWORD   (default: demo-store1-pass)
  DEMO_USER_B_PASSWORD   (default: demo-store2-pass)

This script is intentionally NOT run by the application at startup.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

# Allow running as `python scripts/seed_phase2_demo_users.py` from backend/.
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

from auth import hash_password  # noqa: E402
from database import get_connection  # noqa: E402


STORE_2_ID = 2
STORE_2_NAME = "Store 2"

USER_A = {
    "username": "store1_user_a",
    "store_id": 1,
    "display_name": "Store 1 User A",
    "password_env": "DEMO_USER_A_PASSWORD",
    "password_default": "demo-store1-pass",
}
USER_B = {
    "username": "store2_user_b",
    "store_id": 2,
    "display_name": "Store 2 User B",
    "password_env": "DEMO_USER_B_PASSWORD",
    "password_default": "demo-store2-pass",
}


def _password_for(user: dict) -> str:
    return os.environ.get(user["password_env"]) or user["password_default"]


def _execute_write(sql: str, params: tuple | None = None) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        affected = cursor.rowcount
        conn.commit()
        cursor.close()
        return affected
    finally:
        conn.close()


def _fetch_one(sql: str, params: tuple | None = None) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        row = cursor.fetchone()
        cursor.close()
        return row
    finally:
        conn.close()


def ensure_store_2() -> None:
    existing = _fetch_one(
        "SELECT store_id, store_name FROM stores WHERE store_id = %s",
        (STORE_2_ID,),
    )
    if existing:
        print(f"Store {STORE_2_ID} already present: {existing['store_name']}")
        return
    _execute_write(
        "INSERT INTO stores (store_id, store_name) VALUES (%s, %s)",
        (STORE_2_ID, STORE_2_NAME),
    )
    print(f"Inserted stores row store_id={STORE_2_ID} name={STORE_2_NAME!r}")


def upsert_user(user: dict) -> None:
    password = _password_for(user)
    password_hash = hash_password(password)
    existing = _fetch_one(
        "SELECT user_id, store_id FROM users WHERE username = %s",
        (user["username"],),
    )
    if existing:
        _execute_write(
            """
            UPDATE users
            SET store_id = %s,
                password_hash = %s,
                display_name = %s,
                is_active = 1
            WHERE username = %s
            """,
            (
                user["store_id"],
                password_hash,
                user["display_name"],
                user["username"],
            ),
        )
        print(
            f"Updated user {user['username']!r} "
            f"(user_id={existing['user_id']}, store_id={user['store_id']})"
        )
        return

    _execute_write(
        """
        INSERT INTO users (store_id, username, password_hash, display_name, is_active)
        VALUES (%s, %s, %s, %s, 1)
        """,
        (
            user["store_id"],
            user["username"],
            password_hash,
            user["display_name"],
        ),
    )
    print(f"Inserted user {user['username']!r} store_id={user['store_id']}")


def main() -> int:
    required = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(
            "Missing required DB environment variables: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    store_1 = _fetch_one("SELECT store_id FROM stores WHERE store_id = 1")
    if not store_1:
        print(
            "Store 1 is missing. Apply Phase 1 ownership migration before seeding.",
            file=sys.stderr,
        )
        return 1

    ensure_store_2()
    upsert_user(USER_A)
    upsert_user(USER_B)
    print("Phase 2 demo identity seed complete.")
    print("No Store 2 portfolio/business rows were created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
