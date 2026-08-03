-- Phase 1: additive multi-tenant ownership (Store 1 only).
-- LOCAL MySQL only. Do not run against Render/production.
--
-- Prerequisites:
--   1. mysqldump backup of telleriq_db
--   2. sql/phase1_preflight_checks.sql returned ZERO rows for queries 1-4
--
-- This migration:
--   - creates stores (seeds Store 1 only)
--   - creates empty users table (no credential rows)
--   - adds store_id to business tables and backfills existing rows to store_id = 1
--   - adds NOT NULL, indexes, unique keys, store FKs, and composite parent/store FKs
-- Does NOT:
--   - seed Store 2 business data
--   - seed users/passwords
--   - change existing business column values or IDs

USE telleriq_db;

-- ---------------------------------------------------------------------------
-- A) Registry tables
-- ---------------------------------------------------------------------------
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
-- Intentionally no INSERT into users (Phase 2).

-- ---------------------------------------------------------------------------
-- B) Nullable ownership columns
-- ---------------------------------------------------------------------------
ALTER TABLE customers ADD COLUMN store_id INT NULL;
ALTER TABLE accounts ADD COLUMN store_id INT NULL;
ALTER TABLE loans ADD COLUMN store_id INT NULL;
ALTER TABLE payments ADD COLUMN store_id INT NULL;
ALTER TABLE collateral_items ADD COLUMN store_id INT NULL;

-- ---------------------------------------------------------------------------
-- C) Backfill existing rows → Store 1 only (no other column changes)
-- ---------------------------------------------------------------------------
UPDATE customers SET store_id = 1 WHERE store_id IS NULL;

UPDATE accounts a
INNER JOIN customers c ON c.customer_id = a.customer_id
SET a.store_id = 1
WHERE a.store_id IS NULL;

UPDATE loans l
INNER JOIN customers c ON c.customer_id = l.customer_id
SET l.store_id = 1
WHERE l.store_id IS NULL;

UPDATE payments p
INNER JOIN loans l ON l.loan_id = p.loan_id
SET p.store_id = l.store_id
WHERE p.store_id IS NULL;

UPDATE collateral_items ci
INNER JOIN loans l ON l.loan_id = ci.loan_id
SET ci.store_id = l.store_id
WHERE ci.store_id IS NULL;

-- ---------------------------------------------------------------------------
-- D) Post-backfill verification (manual review)
--     All null-counts must be 0.
--     All store_id groupings must show only store_id = 1.
--     If not, STOP before section E.
-- ---------------------------------------------------------------------------
SELECT 'customers' AS t, COUNT(*) AS nulls FROM customers WHERE store_id IS NULL
UNION ALL SELECT 'accounts', COUNT(*) FROM accounts WHERE store_id IS NULL
UNION ALL SELECT 'loans', COUNT(*) FROM loans WHERE store_id IS NULL
UNION ALL SELECT 'payments', COUNT(*) FROM payments WHERE store_id IS NULL
UNION ALL SELECT 'collateral_items', COUNT(*) FROM collateral_items WHERE store_id IS NULL;

SELECT 'customers' AS t, store_id, COUNT(*) AS n FROM customers GROUP BY store_id
UNION ALL SELECT 'accounts', store_id, COUNT(*) FROM accounts GROUP BY store_id
UNION ALL SELECT 'loans', store_id, COUNT(*) FROM loans GROUP BY store_id
UNION ALL SELECT 'payments', store_id, COUNT(*) FROM payments GROUP BY store_id
UNION ALL SELECT 'collateral_items', store_id, COUNT(*) FROM collateral_items GROUP BY store_id;

-- ---------------------------------------------------------------------------
-- E) Harden columns
-- ---------------------------------------------------------------------------
ALTER TABLE customers MODIFY store_id INT NOT NULL;
ALTER TABLE accounts MODIFY store_id INT NOT NULL;
ALTER TABLE loans MODIFY store_id INT NOT NULL;
ALTER TABLE payments MODIFY store_id INT NOT NULL;
ALTER TABLE collateral_items MODIFY store_id INT NOT NULL;

-- ---------------------------------------------------------------------------
-- F) Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_customers_store_id ON customers (store_id);
CREATE INDEX idx_accounts_store_id ON accounts (store_id);
CREATE INDEX idx_loans_store_id ON loans (store_id);
CREATE INDEX idx_payments_store_id ON payments (store_id);
CREATE INDEX idx_collateral_items_store_id ON collateral_items (store_id);

-- ---------------------------------------------------------------------------
-- G) Unique keys required for composite parent/store FKs
--     Existing primary keys (and IDs) are preserved.
-- ---------------------------------------------------------------------------
ALTER TABLE customers
    ADD UNIQUE KEY uq_customers_id_store (customer_id, store_id);
ALTER TABLE loans
    ADD UNIQUE KEY uq_loans_id_store (loan_id, store_id);
ALTER TABLE accounts
    ADD UNIQUE KEY uq_accounts_id_store (account_id, store_id);
ALTER TABLE payments
    ADD UNIQUE KEY uq_payments_id_store (payment_id, store_id);
ALTER TABLE collateral_items
    ADD UNIQUE KEY uq_collateral_items_id_store (item_id, store_id);

-- ---------------------------------------------------------------------------
-- H) store_id → stores(store_id) on every tenant-owned business table
-- ---------------------------------------------------------------------------
ALTER TABLE customers
    ADD CONSTRAINT fk_customers_store
    FOREIGN KEY (store_id) REFERENCES stores (store_id);

ALTER TABLE accounts
    ADD CONSTRAINT fk_accounts_store
    FOREIGN KEY (store_id) REFERENCES stores (store_id);

ALTER TABLE loans
    ADD CONSTRAINT fk_loans_store
    FOREIGN KEY (store_id) REFERENCES stores (store_id);

ALTER TABLE payments
    ADD CONSTRAINT fk_payments_store
    FOREIGN KEY (store_id) REFERENCES stores (store_id);

ALTER TABLE collateral_items
    ADD CONSTRAINT fk_collateral_items_store
    FOREIGN KEY (store_id) REFERENCES stores (store_id);

-- ---------------------------------------------------------------------------
-- I) Composite tenant-consistency FKs
--     Children cannot reference a parent row belonging to another store.
--     Existing collateral_items(loan_id) → loans(loan_id) remains in place.
-- ---------------------------------------------------------------------------
ALTER TABLE accounts
    ADD CONSTRAINT fk_accounts_customer_store
    FOREIGN KEY (customer_id, store_id)
    REFERENCES customers (customer_id, store_id);

ALTER TABLE loans
    ADD CONSTRAINT fk_loans_customer_store
    FOREIGN KEY (customer_id, store_id)
    REFERENCES customers (customer_id, store_id);

ALTER TABLE payments
    ADD CONSTRAINT fk_payments_loan_store
    FOREIGN KEY (loan_id, store_id)
    REFERENCES loans (loan_id, store_id);

ALTER TABLE collateral_items
    ADD CONSTRAINT fk_collateral_loan_store
    FOREIGN KEY (loan_id, store_id)
    REFERENCES loans (loan_id, store_id);
