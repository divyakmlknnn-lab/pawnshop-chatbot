USE telleriq_db;

CREATE TABLE customers (
    customer_id INT PRIMARY KEY AUTO_INCREMENT,
    full_name VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100)
);

CREATE TABLE accounts (
    account_id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT,
    account_type VARCHAR(50),
    balance DECIMAL(12,2),
    status VARCHAR(20)
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

INSERT INTO customers (full_name, phone, email)
VALUES
('Asha Patel', '7325551010', 'asha@email.com'),
('Rohan Mehta', '7325552020', 'rohan@email.com'),
('Maya Shah', '7325553030', 'maya@email.com'),
('Daniel Brooks', '7325554040', 'daniel@email.com'),
('Priya Nair', '7325555050', 'priya@email.com');

INSERT INTO accounts (customer_id, account_type, balance, status)
VALUES
(1, 'Checking', 2450.75, 'Active'),
(1, 'Savings', 10800.00, 'Active'),
(2, 'Checking', 900.50, 'Active'),
(3, 'Checking', 3200.25, 'Active'),
(3, 'Savings', 15000.00, 'Active'),
(4, 'Checking', 750.40, 'Active'),
(4, 'Savings', 5200.00, 'Active'),
(5, 'Checking', 1200.00, 'Active'),
(5, 'Savings', 9800.00, 'Active');

INSERT INTO loans (customer_id, loan_type, current_balance, collateral_value, next_due_date)
VALUES
(1, 'Home Loan', 210000, 300000, '2026-06-01'),
(2, 'Auto Loan', 28000, 40000, '2026-05-20'),
(3, 'Home Loan', 180000, 260000, '2026-06-15'),
(4, 'Auto Loan', 22000, 30000, '2026-05-30'),
(5, 'Personal Loan', 9000, 12000, '2026-06-05');

INSERT INTO payments (loan_id, amount_due, amount_paid, due_date)
VALUES
(1, 1850, 1000, '2025-01-01'),
(2, 620, 300, '2026-05-01'),
(3, 1600, 1600, '2026-06-15'),
(4, 540, 200, '2025-12-01'),
(5, 350, 0, '2026-06-05');

SELECT * FROM customers;
SELECT * FROM accounts;
SELECT * FROM loans;
SELECT * FROM payments;