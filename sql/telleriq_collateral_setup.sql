CREATE TABLE IF NOT EXISTS collateral_items (
    item_id INT AUTO_INCREMENT PRIMARY KEY,
    loan_id INT,
    item_type VARCHAR(100),
    item_description VARCHAR(255),
    appraised_value DECIMAL(10,2),
    serial_number VARCHAR(100),
    item_status VARCHAR(50),
    forfeiture_date DATE,
    FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
);

INSERT INTO collateral_items 
(loan_id, item_type, item_description, appraised_value, serial_number, item_status, forfeiture_date)
VALUES
(1, 'Jewelry', '22K gold chain', 300000.00, 'GLD-1001', 'Held', '2026-06-15'),
(2, 'Vehicle', '2018 Honda Civic', 18000.00, 'VIN-2020-AUTO', 'Held', '2026-06-10'),
(3, 'Electronics', 'MacBook Pro 14 inch', 2200.00, 'MBP-3321', 'Held', '2026-06-20'),
(4, 'Vehicle', '2017 Toyota Camry', 15000.00, 'VIN-4040-CAR', 'Held', '2026-06-05'),
(5, 'Electronics', 'iPhone 15 Pro', 1200.00, 'IPH-5050', 'Held', '2026-06-12');