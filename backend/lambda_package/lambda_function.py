import json
import os
import pymysql
from decimal import Decimal
from datetime import date, datetime


def get_connection():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        port=int(os.environ.get("DB_PORT", 3306)),
        cursorclass=pymysql.cursors.DictCursor
    )


def clean_data(data):
    for row in data:
        for key, value in row.items():
            if isinstance(value, Decimal):
                row[key] = float(value)
            elif isinstance(value, (date, datetime)):
                row[key] = value.isoformat()
    return data


def run_query(sql):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql)
    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return clean_data(result)


def response(data, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(data)
    }


def due_soon():
    sql = """
        SELECT 
            c.customer_id,
            c.full_name,
            c.phone,
            l.loan_type,
            ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent,
            p.amount_due,
            p.amount_paid,
            (p.amount_due - p.amount_paid) AS remaining_due,
            p.due_date
        FROM customers c
        JOIN loans l ON c.customer_id = l.customer_id
        JOIN payments p ON l.loan_id = p.loan_id
        WHERE p.due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
        AND p.amount_paid < p.amount_due
        ORDER BY p.due_date ASC
    """
    return run_query(sql)


def overdue_customers():
    sql = """
        SELECT 
            c.customer_id,
            c.full_name,
            c.phone,
            l.loan_type,
            ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent,
            p.amount_due,
            p.amount_paid,
            (p.amount_due - p.amount_paid) AS remaining_due,
            p.due_date
        FROM customers c
        JOIN loans l ON c.customer_id = l.customer_id
        JOIN payments p ON l.loan_id = p.loan_id
        WHERE p.due_date < CURDATE()
        AND p.amount_paid < p.amount_due
        ORDER BY p.due_date ASC
    """
    return run_query(sql)


def missed_payments():
    sql = """
        SELECT 
            c.customer_id,
            c.full_name,
            c.phone,
            l.loan_type,
            ROUND((l.current_balance / l.collateral_value) * 100, 2) AS ltv_percent,
            p.amount_due,
            p.amount_paid,
            (p.amount_due - p.amount_paid) AS missed_amount,
            p.due_date
        FROM customers c
        JOIN loans l ON c.customer_id = l.customer_id
        JOIN payments p ON l.loan_id = p.loan_id
        WHERE p.due_date < CURDATE()
        AND p.amount_paid < p.amount_due
        ORDER BY p.due_date ASC
    """
    return run_query(sql)


def lambda_handler(event, context):
    try:
        path = event.get("rawPath") or event.get("path", "/")

        if path == "/due-soon":
            return response(due_soon())

        elif path == "/overdue-customers":
            return response(overdue_customers())

        elif path == "/missed-payments":
            return response(missed_payments())

        else:
            return response({
                "message": "TellerIQ Lambda backend is running.",
                "available_routes": ["/due-soon", "/overdue-customers", "/missed-payments"]
            })

    except Exception as e:
        return response({"error": str(e)}, 500)