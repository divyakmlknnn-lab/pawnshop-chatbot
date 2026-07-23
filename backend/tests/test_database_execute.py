import unittest
from unittest.mock import MagicMock, patch

import database
from query_trace import is_traced


class DatabaseExecuteTests(unittest.TestCase):
    def setUp(self):
        self.mock_cursor = MagicMock()
        self.mock_cursor.fetchall.return_value = []
        self.mock_conn = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor
        self.connection_patch = patch(
            "database.get_connection",
            return_value=self.mock_conn,
        )
        self.connection_patch.start()

    def tearDown(self):
        self.connection_patch.stop()

    def test_literal_like_percent_executes_without_params_tuple(self):
        sql = (
            "SELECT c.full_name FROM customers c "
            "JOIN loans l ON c.customer_id = l.customer_id "
            "JOIN collateral_items ci ON l.loan_id = ci.loan_id "
            "WHERE ci.item_description LIKE '%iPhone%' LIMIT 100"
        )

        rows = database._execute(sql)

        self.mock_cursor.execute.assert_called_once_with(sql)
        self.assertEqual(rows, [])

    def test_parameterized_like_uses_supplied_params(self):
        sql = "SELECT full_name FROM customers WHERE full_name LIKE %s LIMIT 100"
        params = ("%iPhone%",)

        database._execute(sql, params)

        self.mock_cursor.execute.assert_called_once_with(sql, params)

    def test_run_traced_query_without_params_preserves_trace_shape(self):
        sql = "SELECT customer_id FROM customers LIMIT 100"
        self.mock_cursor.fetchall.return_value = [{"customer_id": 1}]

        trace = database.run_traced_query(sql, tables_used={"customers": []})

        self.mock_cursor.execute.assert_called_once_with(sql)
        self.assertTrue(is_traced(trace))
        self.assertEqual(trace["sql"], sql)
        self.assertEqual(trace["rows"], [{"customer_id": 1}])


if __name__ == "__main__":
    unittest.main()
