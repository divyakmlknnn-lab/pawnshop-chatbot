import os
from decimal import Decimal
from datetime import date, datetime
import pymysql

from query_trace import extract_rows, make_trace


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


def _execute(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    if params is None:
        cursor.execute(sql)
    else:
        cursor.execute(sql, params)
    result = _clean(cursor.fetchall())
    cursor.close()
    conn.close()
    return result


def run_traced_query(sql, params=None, tables_used=None):
    rows = _execute(sql, params)
    return make_trace(sql, tables_used or {}, rows, params)


def run_traced_scalar(sql, params, tables_used, label: str):
    rows = _execute(sql, params)
    value = 0
    if rows:
        value = next(iter(rows[0].values()))
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
    return make_trace(sql, tables_used, [{label: value}], params)


def run_scalar(sql, params=None):
    rows = _execute(sql, params)
    if not rows:
        return 0
    value = next(iter(rows[0].values()))
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


TABLES = {
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


def search_customers(name: str):
    return run_traced_query(
        """
        SELECT customer_id, full_name, phone, email
        FROM customers
        WHERE full_name LIKE %s
        ORDER BY full_name
        """,
        (f"%{name}%",),
        {"customers": TABLES["customers"]},
    )


def list_customers(limit: int = 50):
    return run_traced_query(
        """
        SELECT customer_id, full_name, phone, email
        FROM customers
        ORDER BY full_name
        LIMIT %s
        """,
        (limit,),
        {"customers": TABLES["customers"]},
    )


def get_customer_count():
    return run_traced_scalar(
        "SELECT COUNT(*) AS count FROM customers",
        (),
        {"customers": ["customer_id"]},
        "count",
    )


def get_loan_count():
    return run_traced_scalar(
        "SELECT COUNT(*) AS count FROM loans",
        (),
        {"loans": ["loan_id"]},
        "count",
    )


def get_account_count():
    return run_traced_scalar(
        "SELECT COUNT(*) AS count FROM accounts",
        (),
        {"accounts": ["account_id"]},
        "count",
    )


def get_total_overdue_amount():
    total_trace = run_traced_scalar(
        """
        SELECT COALESCE(SUM(p.amount_due - p.amount_paid), 0) AS total_overdue
        FROM payments p
        WHERE p.due_date < CURDATE()
          AND p.amount_paid < p.amount_due
        """,
        (),
        {"payments": TABLES["payments"]},
        "total_overdue",
    )
    count_trace = run_traced_scalar(
        """
        SELECT COUNT(DISTINCT l.customer_id) AS overdue_customers
        FROM payments p
        JOIN loans l ON p.loan_id = l.loan_id
        WHERE p.due_date < CURDATE()
          AND p.amount_paid < p.amount_due
        """,
        (),
        {
            "payments": TABLES["payments"],
            "loans": ["loan_id", "customer_id"],
        },
        "overdue_customers",
    )
    total_row = extract_rows(total_trace)[0]
    count_row = extract_rows(count_trace)[0]
    return {
        "total_overdue": float(total_row.get("total_overdue") or 0),
        "overdue_customer_count": int(count_row.get("overdue_customers") or 0),
        "_traces": [total_trace, count_trace],
    }


def get_total_portfolio_balance():
    loan_trace = run_traced_scalar(
        """
        SELECT COALESCE(SUM(current_balance), 0) AS total_balance
        FROM loans
        """,
        (),
        {"loans": ["current_balance"]},
        "total_balance",
    )
    account_trace = run_traced_scalar(
        """
        SELECT COALESCE(SUM(balance), 0) AS total_balance
        FROM accounts
        """,
        (),
        {"accounts": ["balance"]},
        "total_balance",
    )
    loan_balance = float(extract_rows(loan_trace)[0].get("total_balance") or 0)
    account_balance = float(extract_rows(account_trace)[0].get("total_balance") or 0)
    return {
        "loan_balance": loan_balance,
        "account_balance": account_balance,
        "total_balance": loan_balance + account_balance,
        "_traces": [loan_trace, account_trace],
    }


def get_portfolio_summary():
    customer_count = get_customer_count()
    loan_count = get_loan_count()
    account_count = get_account_count()
    overdue = get_total_overdue_amount()
    balances = get_total_portfolio_balance()
    due_soon_trace = run_traced_scalar(
        """
        SELECT COUNT(DISTINCT l.customer_id) AS due_soon_count
        FROM payments p
        JOIN loans l ON p.loan_id = l.loan_id
        WHERE p.due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
          AND p.amount_paid < p.amount_due
        """,
        (),
        {
            "payments": TABLES["payments"],
            "loans": ["loan_id", "customer_id"],
        },
        "due_soon_count",
    )
    high_risk_trace = run_traced_scalar(
        """
        SELECT COUNT(*) AS high_risk_count
        FROM loans
        WHERE (current_balance / collateral_value) * 100 >= 75
        """,
        (),
        {"loans": ["current_balance", "collateral_value"]},
        "high_risk_count",
    )
    traces = [
        customer_count,
        loan_count,
        account_count,
        *overdue.get("_traces", []),
        *balances.get("_traces", []),
        due_soon_trace,
        high_risk_trace,
    ]
    return {
        "customer_count": int(extract_rows(customer_count)[0].get("count") or 0),
        "loan_count": int(extract_rows(loan_count)[0].get("count") or 0),
        "account_count": int(extract_rows(account_count)[0].get("count") or 0),
        "total_overdue": overdue["total_overdue"],
        "overdue_customer_count": overdue["overdue_customer_count"],
        "loan_balance": balances["loan_balance"],
        "account_balance": balances["account_balance"],
        "total_balance": balances["total_balance"],
        "due_soon_count": int(extract_rows(due_soon_trace)[0].get("due_soon_count") or 0),
        "high_risk_count": int(extract_rows(high_risk_trace)[0].get("high_risk_count") or 0),
        "_traces": traces,
    }


def get_accounts(customer_id: int):
    return run_traced_query(
        """
        SELECT account_type, balance, status
        FROM accounts
        WHERE customer_id = %s
        """,
        (customer_id,),
        {"accounts": TABLES["accounts"]},
    )


def get_loans(customer_id: int):
    return run_traced_query(
        """
        SELECT loan_id, loan_type, current_balance, collateral_value, next_due_date,
               ROUND((current_balance / collateral_value) * 100, 2) AS ltv_percent
        FROM loans
        WHERE customer_id = %s
        """,
        (customer_id,),
        {"loans": TABLES["loans"]},
    )


def get_payments(customer_id: int):
    return run_traced_query(
        """
        SELECT l.loan_type, p.amount_due, p.amount_paid,
               (p.amount_due - p.amount_paid) AS remaining_due, p.due_date
        FROM payments p
        JOIN loans l ON p.loan_id = l.loan_id
        WHERE l.customer_id = %s
        ORDER BY p.due_date
        """,
        (customer_id,),
        {
            "payments": TABLES["payments"],
            "loans": ["loan_id", "customer_id", "loan_type"],
        },
    )


def get_collateral(customer_id: int = None):
    sql = """
        SELECT c.full_name, c.phone, ci.item_type, ci.item_description,
               ci.appraised_value, ci.item_status, ci.forfeiture_date, l.loan_type
        FROM collateral_items ci
        JOIN loans l ON ci.loan_id = l.loan_id
        JOIN customers c ON l.customer_id = c.customer_id
    """
    tables = {
        "collateral_items": TABLES["collateral_items"],
        "loans": ["loan_id", "customer_id", "loan_type"],
        "customers": ["customer_id", "full_name", "phone"],
    }
    if customer_id:
        sql += " WHERE c.customer_id = %s"
        return run_traced_query(sql, (customer_id,), tables)
    return run_traced_query(sql, None, tables)


OVERDUE_SQL = """
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

OVERDUE_TABLES = {
    "customers": ["customer_id", "full_name", "phone"],
    "loans": ["loan_id", "customer_id", "loan_type", "current_balance", "collateral_value"],
    "payments": ["loan_id", "amount_due", "amount_paid", "due_date"],
}


def get_overdue_customers():
    return run_traced_query(OVERDUE_SQL, None, OVERDUE_TABLES)


def get_due_soon_customers():
    return run_traced_query(
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
        """,
        None,
        OVERDUE_TABLES,
    )


def _payments_due_query(date_condition: str) -> str:
    return f"""
        SELECT c.customer_id, c.full_name, c.phone, l.loan_type,
               ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent,
               p.amount_due, p.amount_paid,
               (p.amount_due - p.amount_paid) AS remaining_due, p.due_date
        FROM customers c
        JOIN loans l ON c.customer_id = l.customer_id
        JOIN payments p ON l.loan_id = p.loan_id
        WHERE {date_condition}
          AND p.amount_paid < p.amount_due
        ORDER BY p.due_date ASC
        """


def get_due_today_customers():
    return run_traced_query(
        _payments_due_query("p.due_date = CURDATE()"),
        None,
        OVERDUE_TABLES,
    )


def get_due_tomorrow_customers():
    return run_traced_query(
        _payments_due_query("p.due_date = DATE_ADD(CURDATE(), INTERVAL 1 DAY)"),
        None,
        OVERDUE_TABLES,
    )


def get_due_this_week_customers():
    return run_traced_query(
        _payments_due_query(
            "p.due_date BETWEEN CURDATE() "
            "AND DATE_ADD(CURDATE(), INTERVAL (6 - WEEKDAY(CURDATE())) DAY)"
        ),
        None,
        OVERDUE_TABLES,
    )


def get_overdue_account_count():
    return int(
        run_scalar(
            """
            SELECT COUNT(*) AS overdue_count
            FROM payments p
            WHERE p.due_date < CURDATE()
              AND p.amount_paid < p.amount_due
            """
        )
    )


def get_next_scheduled_payment():
    rows = extract_rows(
        run_traced_query(
            """
            SELECT c.customer_id, c.full_name, c.phone, l.loan_type,
                   p.amount_due, p.amount_paid,
                   (p.amount_due - p.amount_paid) AS remaining_due, p.due_date
            FROM payments p
            JOIN loans l ON p.loan_id = l.loan_id
            JOIN customers c ON l.customer_id = c.customer_id
            WHERE p.due_date >= CURDATE()
            ORDER BY p.due_date ASC
            LIMIT 1
            """,
            None,
            OVERDUE_TABLES,
        )
    )
    return rows[0] if rows else None


def get_missed_payments():
    return get_overdue_customers()


def get_high_risk_loans(ltv_threshold: float = 75.0):
    return run_traced_query(
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
        {
            "customers": ["customer_id", "full_name", "phone"],
            "loans": TABLES["loans"],
        },
    )


def get_collateral_at_risk():
    return run_traced_query(
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
        """,
        None,
        {
            "collateral_items": TABLES["collateral_items"],
            "loans": ["loan_id", "customer_id", "loan_type", "current_balance", "collateral_value"],
            "customers": ["customer_id", "full_name", "phone"],
        },
    )


def get_today_priorities():
    overdue = get_overdue_customers()
    due_soon = get_due_soon_customers()
    high_risk = get_high_risk_loans()
    return {
        "overdue": overdue,
        "due_soon": due_soon,
        "high_risk": high_risk,
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
        rows = extract_rows(
            run_traced_query(
                "SELECT customer_id, full_name, phone, email FROM customers WHERE customer_id = %s",
                (customer_id,),
                {"customers": TABLES["customers"]},
            )
        )
        return rows[0] if rows else None
    if customer_name:
        rows = extract_rows(search_customers(customer_name))
        return rows[0] if len(rows) == 1 else rows
    return None


def get_customer(customer_id: int):
    return resolve_customer_id(customer_id=customer_id)
