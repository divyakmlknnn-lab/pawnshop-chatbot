import os
from decimal import Decimal
from datetime import date, datetime
import pymysql


def get_connection():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        port=int(os.environ.get("DB_PORT", 3306)),
        cursorclass=pymysql.cursors.DictCursor,
    )


def _clean(rows):
    for row in rows:
        for key, value in row.items():
            if isinstance(value, Decimal):
                row[key] = float(value)
            elif isinstance(value, (date, datetime)):
                row[key] = value.isoformat()
    return rows


def run_query(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    result = _clean(cursor.fetchall())
    cursor.close()
    conn.close()
    return result


def search_customers(name: str):
    return run_query(
        """
        SELECT customer_id, full_name, phone, email
        FROM customers
        WHERE full_name LIKE %s
        ORDER BY full_name
        """,
        (f"%{name}%",),
    )


def get_accounts(customer_id: int):
    return run_query(
        """
        SELECT account_type, balance, status
        FROM accounts
        WHERE customer_id = %s
        """,
        (customer_id,),
    )


def get_loans(customer_id: int):
    return run_query(
        """
        SELECT loan_id, loan_type, current_balance, collateral_value, next_due_date,
               ROUND((current_balance / collateral_value) * 100, 2) AS ltv_percent
        FROM loans
        WHERE customer_id = %s
        """,
        (customer_id,),
    )


def get_payments(customer_id: int):
    return run_query(
        """
        SELECT l.loan_type, p.amount_due, p.amount_paid,
               (p.amount_due - p.amount_paid) AS remaining_due, p.due_date
        FROM payments p
        JOIN loans l ON p.loan_id = l.loan_id
        WHERE l.customer_id = %s
        ORDER BY p.due_date
        """,
        (customer_id,),
    )


def get_collateral(customer_id: int = None):
    sql = """
        SELECT c.full_name, c.phone, ci.item_type, ci.item_description,
               ci.appraised_value, ci.item_status, ci.forfeiture_date, l.loan_type
        FROM collateral_items ci
        JOIN loans l ON ci.loan_id = l.loan_id
        JOIN customers c ON l.customer_id = c.customer_id
    """
    if customer_id:
        sql += " WHERE c.customer_id = %s"
        return run_query(sql, (customer_id,))
    return run_query(sql)


def get_overdue_customers():
    return run_query(
        """
        SELECT c.customer_id, c.full_name, c.phone, l.loan_type,
               ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent,
               p.amount_due, p.amount_paid,
               (p.amount_due - p.amount_paid) AS remaining_due, p.due_date
        FROM customers c
        JOIN loans l ON c.customer_id = l.customer_id
        JOIN payments p ON l.loan_id = p.loan_id
        WHERE p.due_date < CURDATE() AND p.amount_paid < p.amount_due
        ORDER BY p.due_date ASC
        """
    )


def get_due_soon_customers():
    return run_query(
        """
        SELECT c.customer_id, c.full_name, c.phone, l.loan_type,
               ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent,
               p.amount_due, p.amount_paid,
               (p.amount_due - p.amount_paid) AS remaining_due, p.due_date
        FROM customers c
        JOIN loans l ON c.customer_id = l.customer_id
        JOIN payments p ON l.loan_id = p.loan_id
        WHERE p.due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
          AND p.amount_paid < p.amount_due
        ORDER BY p.due_date ASC
        """
    )


def get_missed_payments():
    return get_overdue_customers()


def get_high_risk_loans(ltv_threshold: float = 75.0):
    return run_query(
        """
        SELECT c.customer_id, c.full_name, c.phone, l.loan_type,
               l.current_balance, l.collateral_value,
               ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent,
               l.next_due_date
        FROM customers c
        JOIN loans l ON c.customer_id = l.customer_id
        WHERE (l.current_balance / l.collateral_value) * 100 >= %s
        ORDER BY ltv_percent DESC
        """,
        (ltv_threshold,),
    )


def get_collateral_at_risk():
    return run_query(
        """
        SELECT c.full_name, c.phone, l.loan_type, ci.item_description,
               ci.appraised_value, ci.item_status, ci.forfeiture_date,
               ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent
        FROM collateral_items ci
        JOIN loans l ON ci.loan_id = l.loan_id
        JOIN customers c ON l.customer_id = c.customer_id
        WHERE ci.forfeiture_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
           OR (l.current_balance / l.collateral_value) * 100 >= 75
        ORDER BY ci.forfeiture_date ASC
        """
    )


def get_today_priorities():
    overdue = get_overdue_customers()
    due_soon = get_due_soon_customers()
    high_risk = get_high_risk_loans()
    return {
        "overdue": overdue,
        "due_soon": due_soon,
        "high_risk": high_risk[:5],
    }


REQUIRED_SCHEMA = {
    "customers": ["customer_id", "full_name", "phone", "email"],
    "accounts": ["customer_id", "account_type", "balance", "status"],
    "loans": [
        "loan_id",
        "customer_id",
        "loan_type",
        "current_balance",
        "collateral_value",
        "next_due_date",
    ],
    "payments": ["loan_id", "amount_due", "amount_paid", "due_date"],
    "collateral_items": [
        "loan_id",
        "item_type",
        "item_description",
        "appraised_value",
        "item_status",
        "forfeiture_date",
    ],
}


def verify_schema():
    db_name = os.environ.get("DB_NAME", "telleriq_db")
    conn = get_connection()
    cursor = conn.cursor()
    errors = []

    for table, columns in REQUIRED_SCHEMA.items():
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            """,
            (db_name, table),
        )
        if cursor.fetchone()["cnt"] == 0:
            errors.append(f"Missing table: {table}")
            continue

        for column in columns:
            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name = %s
                """,
                (db_name, table, column),
            )
            if cursor.fetchone()["cnt"] == 0:
                errors.append(f"Missing column: {table}.{column}")

    cursor.close()
    conn.close()

    if errors:
        raise RuntimeError(
            "Database schema validation failed for "
            f"'{db_name}'. Apply sql/setup_database.sql and "
            "sql/telleriq_collateral_setup.sql, then restart.\n  - "
            + "\n  - ".join(errors)
        )


def resolve_customer_id(customer_id: int = None, customer_name: str = None):
    if customer_id:
        rows = run_query(
            "SELECT customer_id, full_name, phone, email FROM customers WHERE customer_id = %s",
            (customer_id,),
        )
        return rows[0] if rows else None
    if customer_name:
        rows = search_customers(customer_name)
        return rows[0] if len(rows) == 1 else rows
    return None


def get_customer(customer_id: int):
    return resolve_customer_id(customer_id=customer_id)
