-- =============================================================================
-- Production cleanup: duplicate collateral_items by serial_number
-- For MySQL Workbench — keep oldest row (MIN(item_id)), delete extras only.
-- =============================================================================
-- BEFORE YOU START IN WORKBENCH:
--   1. Disable Autocommit (Query menu → Autocommit, or lightning bolt toolbar).
--   2. Run this script in ONE query tab / one session.
--   3. Review every result grid.
--   4. Type COMMIT; only if all AFTER checks pass — otherwise ROLLBACK;
-- =============================================================================

START TRANSACTION;

-- -----------------------------------------------------------------------------
-- BEFORE: total row count
-- Expect (if seed ran 3x): 15
-- -----------------------------------------------------------------------------
SELECT COUNT(*) AS total_rows_before
FROM collateral_items;

-- -----------------------------------------------------------------------------
-- BEFORE: duplicates by serial_number
-- keep_item_id = oldest row to retain
-- -----------------------------------------------------------------------------
SELECT
    serial_number,
    item_description,
    loan_id,
    COUNT(*) AS duplicate_count,
    MIN(item_id) AS keep_item_id,
    GROUP_CONCAT(item_id ORDER BY item_id) AS all_item_ids
FROM collateral_items
GROUP BY serial_number, item_description, loan_id
HAVING COUNT(*) > 1
ORDER BY serial_number;

-- -----------------------------------------------------------------------------
-- BEFORE: rows that WILL be deleted (extras only)
-- For IPH-5050 expect item_id 10 and 15 (keep 5)
-- -----------------------------------------------------------------------------
SELECT
    ci.item_id AS will_delete_item_id,
    d.keep_item_id AS will_keep_item_id,
    ci.loan_id,
    ci.item_description,
    ci.serial_number
FROM collateral_items ci
INNER JOIN (
    SELECT
        serial_number,
        MIN(item_id) AS keep_item_id
    FROM collateral_items
    GROUP BY serial_number
    HAVING COUNT(*) > 1
) d ON ci.serial_number <=> d.serial_number
WHERE ci.item_id <> d.keep_item_id
ORDER BY ci.serial_number, ci.item_id;

-- -----------------------------------------------------------------------------
-- DELETE: remove only duplicate extras; keep MIN(item_id) per serial_number
-- -----------------------------------------------------------------------------
DELETE ci
FROM collateral_items ci
INNER JOIN (
    SELECT
        serial_number,
        MIN(item_id) AS keep_item_id
    FROM collateral_items
    GROUP BY serial_number
    HAVING COUNT(*) > 1
) d ON ci.serial_number <=> d.serial_number
WHERE ci.item_id <> d.keep_item_id;

-- -----------------------------------------------------------------------------
-- AFTER: expect total_rows_after = 5
-- -----------------------------------------------------------------------------
SELECT COUNT(*) AS total_rows_after
FROM collateral_items;

-- -----------------------------------------------------------------------------
-- AFTER: expect EMPTY (no duplicate serials)
-- -----------------------------------------------------------------------------
SELECT
    serial_number,
    COUNT(*) AS copies
FROM collateral_items
GROUP BY serial_number
HAVING COUNT(*) > 1;

-- -----------------------------------------------------------------------------
-- AFTER: remaining inventory — one row per serial
-- -----------------------------------------------------------------------------
SELECT
    item_id,
    loan_id,
    item_description,
    serial_number
FROM collateral_items
ORDER BY item_id;

-- -----------------------------------------------------------------------------
-- AFTER: iPhone — expect exactly ONE row (item_id 5, IPH-5050)
-- -----------------------------------------------------------------------------
SELECT
    item_id,
    loan_id,
    item_description,
    serial_number
FROM collateral_items
WHERE serial_number = 'IPH-5050';

-- -----------------------------------------------------------------------------
-- AFTER: owner still correct — expect one Priya Nair | iPhone 15 Pro
-- -----------------------------------------------------------------------------
SELECT
    c.full_name,
    ci.item_id,
    ci.item_description,
    ci.serial_number,
    l.loan_id
FROM customers c
JOIN loans l ON c.customer_id = l.customer_id
JOIN collateral_items ci ON l.loan_id = ci.loan_id
WHERE ci.serial_number = 'IPH-5050';

-- =============================================================================
-- FINALIZE (run ONE of these manually after reviewing results):
--
--   COMMIT;
--
--   -- or, if anything looks wrong:
--   ROLLBACK;
-- =============================================================================
