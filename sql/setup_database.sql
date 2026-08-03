USE telleriq_db;

-- Phase 1 greenfield: tenant registry (Store 1 only) + empty users table.
CREATE TABLE stores (
    store_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    store_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO stores (store_id, store_name) VALUES (1, 'Store 1');

CREATE TABLE users (
    user_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    store_id INT NOT NULL,
    username VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_username (username),
    CONSTRAINT fk_users_store
        FOREIGN KEY (store_id) REFERENCES stores (store_id)
);
-- No demo users/credentials in Phase 1.

CREATE TABLE customers (
    customer_id INT PRIMARY KEY AUTO_INCREMENT,
    store_id INT NOT NULL,
    full_name VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    UNIQUE KEY uq_customers_id_store (customer_id, store_id),
    KEY idx_customers_store_id (store_id),
    CONSTRAINT fk_customers_store
        FOREIGN KEY (store_id) REFERENCES stores (store_id)
);

CREATE TABLE accounts (
    account_id INT PRIMARY KEY AUTO_INCREMENT,
    store_id INT NOT NULL,
    customer_id INT,
    account_type VARCHAR(50),
    balance DECIMAL(12,2),
    status VARCHAR(20),
    UNIQUE KEY uq_accounts_id_store (account_id, store_id),
    KEY idx_accounts_store_id (store_id),
    CONSTRAINT fk_accounts_store
        FOREIGN KEY (store_id) REFERENCES stores (store_id),
    CONSTRAINT fk_accounts_customer_store
        FOREIGN KEY (customer_id, store_id)
        REFERENCES customers (customer_id, store_id)
);

CREATE TABLE loans (
    loan_id INT PRIMARY KEY AUTO_INCREMENT,
    store_id INT NOT NULL,
    customer_id INT,
    loan_type VARCHAR(50),
    current_balance DECIMAL(12,2),
    collateral_value DECIMAL(12,2),
    next_due_date DATE,
    UNIQUE KEY uq_loans_id_store (loan_id, store_id),
    KEY idx_loans_store_id (store_id),
    CONSTRAINT fk_loans_store
        FOREIGN KEY (store_id) REFERENCES stores (store_id),
    CONSTRAINT fk_loans_customer_store
        FOREIGN KEY (customer_id, store_id)
        REFERENCES customers (customer_id, store_id)
);

CREATE TABLE payments (
    payment_id INT PRIMARY KEY AUTO_INCREMENT,
    store_id INT NOT NULL,
    loan_id INT,
    amount_due DECIMAL(10,2),
    amount_paid DECIMAL(10,2),
    due_date DATE,
    UNIQUE KEY uq_payments_id_store (payment_id, store_id),
    KEY idx_payments_store_id (store_id),
    CONSTRAINT fk_payments_store
        FOREIGN KEY (store_id) REFERENCES stores (store_id),
    CONSTRAINT fk_payments_loan_store
        FOREIGN KEY (loan_id, store_id)
        REFERENCES loans (loan_id, store_id)
);

-- Existing demo portfolio = Store 1. IDs and values preserved.
INSERT INTO customers (full_name, phone, email, store_id)
VALUES
('Asha Patel', '7325551010', 'asha@email.com', 1),
('Rohan Mehta', '7325552020', 'rohan@email.com', 1),
('Maya Shah', '7325553030', 'maya@email.com', 1),
('Daniel Brooks', '7325554040', 'daniel@email.com', 1),
('Priya Nair', '7325555050', 'priya@email.com', 1);

INSERT INTO accounts (customer_id, account_type, balance, status, store_id)
VALUES
(1, 'Checking', 2450.75, 'Active', 1),
(1, 'Savings', 10800.00, 'Active', 1),
(2, 'Checking', 900.50, 'Active', 1),
(3, 'Checking', 3200.25, 'Active', 1),
(3, 'Savings', 15000.00, 'Active', 1),
(4, 'Checking', 750.40, 'Active', 1),
(4, 'Savings', 5200.00, 'Active', 1),
(5, 'Checking', 1200.00, 'Active', 1),
(5, 'Savings', 9800.00, 'Active', 1);

INSERT INTO loans (customer_id, loan_type, current_balance, collateral_value, next_due_date, store_id)
VALUES
(1, 'Home Loan', 210000, 300000, '2026-06-01', 1),
(2, 'Auto Loan', 28000, 40000, '2026-05-20', 1),
(3, 'Home Loan', 180000, 260000, '2026-06-15', 1),
(4, 'Auto Loan', 22000, 30000, '2026-05-30', 1),
(5, 'Personal Loan', 9000, 12000, '2026-06-05', 1);

INSERT INTO payments (loan_id, amount_due, amount_paid, due_date, store_id)
VALUES
(1, 1850, 1000, '2025-01-01', 1),
(2, 620, 300, '2026-05-01', 1),
(3, 1600, 1600, '2026-06-15', 1),
(4, 540, 200, '2025-12-01', 1),
(5, 350, 0, '2026-06-05', 1);

SELECT * FROM customers;
SELECT * FROM accounts;
SELECT * FROM loans;
SELECT * FROM payments;
