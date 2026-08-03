CREATE TABLE IF NOT EXISTS collateral_items (
    item_id INT AUTO_INCREMENT PRIMARY KEY,
    store_id INT NOT NULL,
    loan_id INT,
    item_type VARCHAR(100),
    item_description VARCHAR(255),
    appraised_value DECIMAL(10,2),
    serial_number VARCHAR(100),
    item_status VARCHAR(50),
    forfeiture_date DATE,
    UNIQUE KEY uq_collateral_serial (serial_number),
    UNIQUE KEY uq_collateral_items_id_store (item_id, store_id),
    KEY idx_collateral_items_store_id (store_id),
    FOREIGN KEY (loan_id) REFERENCES loans(loan_id),
    CONSTRAINT fk_collateral_items_store
        FOREIGN KEY (store_id) REFERENCES stores (store_id),
    CONSTRAINT fk_collateral_loan_store
        FOREIGN KEY (loan_id, store_id)
        REFERENCES loans (loan_id, store_id)
);

-- Existing databases created before uq_collateral_serial need the constraint added.
-- Idempotent: skip ALTER when the unique index already exists.
-- Prerequisite: no duplicate serial_number values. If ADD UNIQUE fails, remove
-- duplicate rows first (keep the lowest item_id per serial), then re-run.
SET @uq_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'collateral_items'
      AND index_name = 'uq_collateral_serial'
);
SET @uq_sql := IF(
    @uq_exists = 0,
    'ALTER TABLE collateral_items ADD UNIQUE KEY uq_collateral_serial (serial_number)',
    'SELECT 1'
);
PREPARE stmt_uq FROM @uq_sql;
EXECUTE stmt_uq;
DEALLOCATE PREPARE stmt_uq;

-- Upsert seed rows by serial_number. Re-runs update the existing sample row
-- instead of inserting another copy.
-- Store 1 only (Phase 1). No Store 2 business seed.
INSERT INTO collateral_items
(loan_id, item_type, item_description, appraised_value, serial_number, item_status, forfeiture_date, store_id)
VALUES
(1, 'Jewelry', '22K gold chain', 300000.00, 'GLD-1001', 'Held', '2026-06-15', 1),
(2, 'Vehicle', '2018 Honda Civic', 18000.00, 'VIN-2020-AUTO', 'Held', '2026-06-10', 1),
(3, 'Electronics', 'MacBook Pro 14 inch', 2200.00, 'MBP-3321', 'Held', '2026-06-20', 1),
(4, 'Vehicle', '2017 Toyota Camry', 15000.00, 'VIN-4040-CAR', 'Held', '2026-06-05', 1),
(5, 'Electronics', 'iPhone 15 Pro', 1200.00, 'IPH-5050', 'Held', '2026-06-12', 1)
ON DUPLICATE KEY UPDATE
    loan_id = VALUES(loan_id),
    item_type = VALUES(item_type),
    item_description = VALUES(item_description),
    appraised_value = VALUES(appraised_value),
    item_status = VALUES(item_status),
    forfeiture_date = VALUES(forfeiture_date),
    store_id = VALUES(store_id);
