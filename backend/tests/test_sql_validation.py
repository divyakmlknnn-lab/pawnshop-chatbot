import unittest

from sql_validation import validate_readonly_sql


class SqlValidationValidTests(unittest.TestCase):
    def test_simple_select(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers")
        self.assertTrue(result["valid"])
        self.assertEqual(result["normalized_sql"], "SELECT customer_id FROM customers LIMIT 100")
        self.assertEqual(result["tables_used"], ["customers"])
        self.assertEqual(result["columns_used"], ["customer_id"])
        self.assertIsNone(result["reason"])

    def test_explicit_columns(self):
        result = validate_readonly_sql(
            "SELECT customer_id, full_name FROM customers LIMIT 25"
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["normalized_sql"], "SELECT customer_id, full_name FROM customers LIMIT 25")
        self.assertEqual(result["columns_used"], ["customer_id", "full_name"])

    def test_approved_join(self):
        sql = (
            "SELECT c.full_name, l.loan_type "
            "FROM customers c "
            "JOIN loans l ON c.customer_id = l.customer_id "
            "LIMIT 50"
        )
        result = validate_readonly_sql(sql)
        self.assertTrue(result["valid"])
        self.assertEqual(result["tables_used"], ["customers", "loans"])
        self.assertIn("full_name", result["columns_used"])
        self.assertIn("loan_type", result["columns_used"])
        self.assertIn("customer_id", result["columns_used"])

    def test_computed_field_remaining_due_expression(self):
        sql = "SELECT amount_due - amount_paid AS remaining_due FROM payments LIMIT 10"
        result = validate_readonly_sql(sql)
        self.assertTrue(result["valid"])
        self.assertIn("remaining_due", result["columns_used"])
        self.assertIn("amount_due", result["columns_used"])
        self.assertIn("amount_paid", result["columns_used"])

    def test_computed_field_ltv_percent_expression(self):
        sql = (
            "SELECT current_balance / NULLIF(collateral_value, 0) * 100 AS ltv_percent "
            "FROM loans LIMIT 10"
        )
        result = validate_readonly_sql(sql)
        self.assertTrue(result["valid"])
        self.assertIn("ltv_percent", result["columns_used"])

    def test_limit_preservation(self):
        sql = "SELECT loan_id FROM loans LIMIT 100"
        result = validate_readonly_sql(sql)
        self.assertTrue(result["valid"])
        self.assertEqual(result["normalized_sql"], "SELECT loan_id FROM loans LIMIT 100")

    def test_limit_insertion(self):
        sql = "SELECT loan_id FROM loans"
        result = validate_readonly_sql(sql)
        self.assertTrue(result["valid"])
        self.assertEqual(result["normalized_sql"], "SELECT loan_id FROM loans LIMIT 100")

    def test_contact_fields_allowed_when_explicitly_enabled(self):
        sql = "SELECT phone, email FROM customers LIMIT 10"
        result = validate_readonly_sql(sql, allow_contact_fields=True)
        self.assertTrue(result["valid"])
        self.assertEqual(result["columns_used"], ["email", "phone"])


class SqlValidationInvalidTests(unittest.TestCase):
    def test_delete_rejected(self):
        result = validate_readonly_sql("DELETE FROM customers")
        self.assertFalse(result["valid"])
        self.assertIn("DELETE", result["reason"])

    def test_update_rejected(self):
        result = validate_readonly_sql("UPDATE customers SET full_name = 'x'")
        self.assertFalse(result["valid"])
        self.assertIn("UPDATE", result["reason"])

    def test_drop_rejected(self):
        result = validate_readonly_sql("DROP TABLE customers")
        self.assertFalse(result["valid"])
        self.assertIn("DROP", result["reason"])

    def test_insert_rejected(self):
        result = validate_readonly_sql("INSERT INTO customers (full_name) VALUES ('x')")
        self.assertFalse(result["valid"])
        self.assertIn("INSERT", result["reason"])

    def test_multiple_statements_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers; SELECT loan_id FROM loans")
        self.assertFalse(result["valid"])
        self.assertIn("one SQL statement", result["reason"])

    def test_dash_comment_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers -- sneaky")
        self.assertFalse(result["valid"])
        self.assertIn("comments", result["reason"])

    def test_hash_comment_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers # sneaky")
        self.assertFalse(result["valid"])
        self.assertIn("comments", result["reason"])

    def test_block_comment_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers /* sneaky */")
        self.assertFalse(result["valid"])
        self.assertIn("comments", result["reason"])

    def test_unknown_table_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM mystery_table")
        self.assertFalse(result["valid"])
        self.assertIn("Unknown table", result["reason"])

    def test_unknown_column_rejected(self):
        result = validate_readonly_sql("SELECT not_a_column FROM customers")
        self.assertFalse(result["valid"])
        self.assertIn("Unknown column", result["reason"])

    def test_system_schema_rejected(self):
        result = validate_readonly_sql("SELECT table_name FROM information_schema.tables")
        self.assertFalse(result["valid"])
        self.assertIn("Schema-qualified table names are not allowed.", result["reason"])

    def test_select_star_rejected(self):
        result = validate_readonly_sql("SELECT * FROM customers")
        self.assertFalse(result["valid"])
        self.assertIn("SELECT *", result["reason"])

    def test_contact_fields_rejected_by_default(self):
        result = validate_readonly_sql("SELECT phone, email FROM customers LIMIT 10")
        self.assertFalse(result["valid"])
        self.assertIn("Restricted contact fields", result["reason"])

    def test_limit_over_100_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers LIMIT 101")
        self.assertFalse(result["valid"])
        self.assertIn("LIMIT must be 100", result["reason"])

    def test_invalid_join_rejected(self):
        sql = (
            "SELECT c.full_name "
            "FROM customers c "
            "JOIN payments p ON c.customer_id = p.loan_id"
        )
        result = validate_readonly_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("JOIN is not an approved relationship", result["reason"])

    def test_blank_sql_rejected(self):
        result = validate_readonly_sql("   ")
        self.assertFalse(result["valid"])
        self.assertIn("blank", result["reason"])

    def test_load_data_rejected(self):
        result = validate_readonly_sql("LOAD DATA INFILE '/tmp/x' INTO TABLE customers")
        self.assertFalse(result["valid"])
        self.assertIn("LOAD DATA", result["reason"])


class SqlValidationSecurityFixTests(unittest.TestCase):
    def test_union_with_email_rejected(self):
        sql = "SELECT full_name FROM customers UNION SELECT email FROM customers"
        result = validate_readonly_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("UNION queries are not allowed.", result["reason"])

    def test_from_subquery_aliasing_phone_rejected(self):
        sql = "SELECT customer_id FROM (SELECT phone AS customer_id FROM customers) t"
        result = validate_readonly_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("Subqueries and nested SELECT statements are not allowed.", result["reason"])

    def test_contact_field_in_nested_where_subquery_rejected(self):
        sql = (
            "SELECT customer_id FROM customers "
            "WHERE customer_id IN (SELECT customer_id FROM customers WHERE email = 'a@b.com')"
        )
        result = validate_readonly_sql(sql)
        self.assertFalse(result["valid"])
        self.assertIn("Subqueries and nested SELECT statements are not allowed.", result["reason"])

    def test_into_outfile_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers INTO OUTFILE '/tmp/x'")
        self.assertFalse(result["valid"])
        self.assertIn("INTO OUTFILE and INTO DUMPFILE are not allowed.", result["reason"])

    def test_into_dumpfile_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers INTO DUMPFILE '/tmp/x'")
        self.assertFalse(result["valid"])
        self.assertIn("INTO OUTFILE and INTO DUMPFILE are not allowed.", result["reason"])

    def test_limit_offset_count_syntax_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers LIMIT 0, 500")
        self.assertFalse(result["valid"])
        self.assertIn("LIMIT offset,count syntax is not allowed.", result["reason"])

    def test_limit_hex_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers LIMIT 0x100")
        self.assertFalse(result["valid"])
        self.assertIn("LIMIT must use a decimal integer.", result["reason"])

    def test_comma_separated_from_tables_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers, payments")
        self.assertFalse(result["valid"])
        self.assertIn("Comma-separated FROM tables are not allowed.", result["reason"])

    def test_cross_join_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM customers CROSS JOIN payments")
        self.assertFalse(result["valid"])
        self.assertIn("CROSS JOIN is not allowed.", result["reason"])

    def test_arbitrary_schema_prefix_rejected(self):
        result = validate_readonly_sql("SELECT customer_id FROM staging.customers")
        self.assertFalse(result["valid"])
        self.assertIn("Schema-qualified table names are not allowed.", result["reason"])

    def test_normalized_sql_contains_exactly_one_limit(self):
        cases = [
            "SELECT customer_id FROM customers",
            "SELECT customer_id FROM customers LIMIT 25",
            "SELECT customer_id, full_name FROM customers LIMIT 25 OFFSET 5",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                result = validate_readonly_sql(sql)
                self.assertTrue(result["valid"])
                self.assertIsNotNone(result["normalized_sql"])
                self.assertEqual(result["normalized_sql"].upper().count("LIMIT"), 1)


if __name__ == "__main__":
    unittest.main()
