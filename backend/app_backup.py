from flask import Flask, jsonify
from flask_cors import CORS
import pymysql

app = Flask(__name__)
CORS(app)

def get_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='kDivya2002*',
        database='local_bank',
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route("/")
def home():
    return "LocalBank Teller Assistant backend is running."

@app.route("/ltv/<int:customer_id>")
def loan_to_value(customer_id):

    conn = get_connection()
    cursor = conn.cursor()

    sql = """
        SELECT 
            loan_type,
            current_balance,
            collateral_value,
            ROUND((current_balance / collateral_value) * 100, 2) AS ltv_percent
        FROM loans
        WHERE customer_id = %s
    """

    cursor.execute(sql, (customer_id,))
    result = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(result)

@app.route("/due/<int:customer_id>")
def remaining_due(customer_id):

    conn = get_connection()
    cursor = conn.cursor()

    sql = """
        SELECT 
            l.loan_type,
            p.amount_due,
            p.amount_paid,
            (p.amount_due - p.amount_paid) AS remaining_due,
            p.due_date
        FROM payments p
        JOIN loans l ON p.loan_id = l.loan_id
        WHERE l.customer_id = %s
    """

    cursor.execute(sql, (customer_id,))
    result = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(result)

@app.route("/account/<int:customer_id>")
def account_summary(customer_id):

    conn = get_connection()
    cursor = conn.cursor()

    sql = """
        SELECT 
            account_type,
            balance,
            status
        FROM accounts
        WHERE customer_id = %s
    """

    cursor.execute(sql, (customer_id,))
    result = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(result)

@app.route("/loan-balance/<int:customer_id>")
def loan_balance(customer_id):

    conn = get_connection()
    cursor = conn.cursor()

    sql = """
        SELECT 
            loan_type,
            current_balance AS remaining_loan_balance,
            collateral_value,
            next_due_date
        FROM loans
        WHERE customer_id = %s
    """

    cursor.execute(sql, (customer_id,))
    result = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(result)

@app.route("/overdue/<int:customer_id>")
def overdue_amount(customer_id):

    conn = get_connection()
    cursor = conn.cursor()

    sql = """
        SELECT 
            l.loan_type,
            SUM(p.amount_due - p.amount_paid) AS overdue_amount
        FROM payments p
        JOIN loans l ON p.loan_id = l.loan_id
        WHERE l.customer_id = %s
        AND p.due_date < CURDATE()
        AND p.amount_paid < p.amount_due
        GROUP BY l.loan_type
    """

    cursor.execute(sql, (customer_id,))
    result = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(result)

@app.route("/chat/<int:customer_id>/<question>")
def chat(customer_id, question):

    question = question.lower()

    if "ltv" in question or "loan to value" in question:
        return loan_to_value(customer_id)

    elif "loan balance" in question or "remaining loan" in question or "balance left" in question:
        return loan_balance(customer_id)

    elif "overdue" in question or "late" in question:
        return overdue_amount(customer_id)

    elif "due" in question or "payment" in question:
        return remaining_due(customer_id)

    elif "account" in question or "balance" in question or "summary" in question:
        return account_summary(customer_id)

    else:
        return jsonify({
        "answer": "I can help with account summary, loan balance, loan-to-value, remaining due, and overdue amounts."
    })

if __name__ == "__main__":
    app.run(debug=True)