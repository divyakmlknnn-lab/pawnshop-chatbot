-- Phase 1 preflight: read-only orphan / relationship checks.
-- LOCAL MySQL only. Do not run against Render/production.
--
-- If ANY of queries 1-4 return rows, STOP.
-- Do not run phase1_multi_tenant_ownership.sql.
-- Do not repair/delete/change existing business rows automatically.

USE telleriq_db;

-- 1) accounts → customers
SELECT a.account_id, a.customer_id
FROM accounts a
LEFT JOIN customers c ON c.customer_id = a.customer_id
WHERE a.customer_id IS NULL OR c.customer_id IS NULL;

-- 2) loans → customers
SELECT l.loan_id, l.customer_id
FROM loans l
LEFT JOIN customers c ON c.customer_id = l.customer_id
WHERE l.customer_id IS NULL OR c.customer_id IS NULL;

-- 3) payments → loans
SELECT p.payment_id, p.loan_id
FROM payments p
LEFT JOIN loans l ON l.loan_id = p.loan_id
WHERE p.loan_id IS NULL OR l.loan_id IS NULL;

-- 4) collateral_items → loans
SELECT ci.item_id, ci.loan_id
FROM collateral_items ci
LEFT JOIN loans l ON l.loan_id = ci.loan_id
WHERE ci.loan_id IS NULL OR l.loan_id IS NULL;

-- 5) Informational demo surface counts (not a failure condition)
SELECT
  (SELECT COUNT(*) FROM customers) AS customers_cnt,
  (SELECT COUNT(*) FROM accounts) AS accounts_cnt,
  (SELECT COUNT(*) FROM loans) AS loans_cnt,
  (SELECT COUNT(*) FROM payments) AS payments_cnt,
  (SELECT COUNT(*) FROM collateral_items) AS collateral_cnt;
