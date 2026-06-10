CREATE DATABASE local_bank;
USE local_bank;
CREATE TABLE customers (
    customer_id INT PRIMARY KEY AUTO_INCREMENT,
    full_name VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100)
);
CREATE TABLE loans (
    loan_id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT,
    loan_type VARCHAR(50),
    current_balance DECIMAL(12,2),
    collateral_value DECIMAL(12,2),
    next_due_date DATE
);
CREATE TABLE payments (
    payment_id INT PRIMARY KEY AUTO_INCREMENT,
    loan_id INT,
    amount_due DECIMAL(10,2),
    amount_paid DECIMAL(10,2),
    due_date DATE
);
USE local_bank;

INSERT INTO customers (full_name, phone, email)
VALUES
('Asha Patel', '7325551010', 'asha@email.com'),
('Rohan Mehta', '7325552020', 'rohan@email.com');

INSERT INTO loans (customer_id, loan_type, current_balance, collateral_value, next_due_date)
VALUES
(1, 'Home Loan', 210000, 300000, '2026-06-01'),
(2, 'Auto Loan', 28000, 40000, '2026-05-20');

INSERT INTO payments (loan_id, amount_due, amount_paid, due_date)
VALUES
(1, 1850, 1000, '2026-06-01'),
(2, 620, 300, '2026-05-01');
SELECT * FROM customers;
SELECT * FROM loans;
SELECT * FROM payments;
SELECT 
    loan_type,
    current_balance,
    collateral_value,
    ROUND((current_balance / collateral_value) * 100, 2) AS loan_to_value_percent
FROM loans;
SELECT 
    p.loan_id,
    l.loan_type,
    p.amount_due,
    p.amount_paid,
    (p.amount_due - p.amount_paid) AS remaining_due,
    p.due_date
FROM payments p
JOIN loans l ON p.loan_id = l.loan_id;