import os
import unittest
from unittest.mock import patch

import database
from app import app
from auth import SESSION_STORE_ID, SESSION_USER_ID


class DashboardStatsHelperTests(unittest.TestCase):
    @patch("database.get_collateral_at_risk")
    @patch("database.get_high_risk_loans")
    @patch("database.get_overdue_account_count", return_value=4)
    @patch("database.get_customer_count")
    def test_get_dashboard_stats_uses_existing_queries(
        self,
        mock_customer_count,
        mock_overdue_count,
        mock_high_risk,
        mock_collateral,
    ):
        mock_customer_count.return_value = {
            "sql": "SELECT COUNT(*) AS count FROM customers",
            "rows": [{"count": 5}],
            "tables_used": {"customers": ["customer_id"]},
        }
        mock_high_risk.return_value = {
            "sql": "high-risk",
            "rows": [{"customer_id": 5}],
            "tables_used": {},
        }
        mock_collateral.return_value = {
            "sql": "collateral",
            "rows": [{"item_description": "a"}, {"item_description": "b"}],
            "tables_used": {},
        }

        stats = database.get_dashboard_stats()

        self.assertEqual(
            stats,
            {
                "total_customers": 5,
                "overdue_payments": 4,
                "high_risk_loans": 1,
                "collateral_at_risk": 2,
            },
        )
        mock_customer_count.assert_called_once_with(store_id=None)
        mock_overdue_count.assert_called_once_with(store_id=None)
        mock_high_risk.assert_called_once_with(store_id=None)
        mock_collateral.assert_called_once_with(store_id=None)

    @patch("database.get_collateral_at_risk")
    @patch("database.get_high_risk_loans")
    @patch("database.get_overdue_account_count", return_value=1)
    @patch("database.get_customer_count")
    def test_get_dashboard_stats_forwards_store_id(
        self,
        mock_customer_count,
        mock_overdue_count,
        mock_high_risk,
        mock_collateral,
    ):
        mock_customer_count.return_value = {
            "sql": "scoped",
            "rows": [{"count": 2}],
            "tables_used": {},
        }
        mock_high_risk.return_value = {"sql": "x", "rows": [], "tables_used": {}}
        mock_collateral.return_value = {"sql": "y", "rows": [], "tables_used": {}}

        stats = database.get_dashboard_stats(store_id=2)

        self.assertEqual(
            set(stats.keys()),
            {
                "total_customers",
                "overdue_payments",
                "high_risk_loans",
                "collateral_at_risk",
            },
        )
        mock_customer_count.assert_called_once_with(store_id=2)
        mock_overdue_count.assert_called_once_with(store_id=2)
        mock_high_risk.assert_called_once_with(store_id=2)
        mock_collateral.assert_called_once_with(store_id=2)

    @patch("database.run_traced_scalar")
    def test_customer_count_unscoped_sql_unchanged(self, mock_scalar):
        mock_scalar.return_value = {
            "sql": "SELECT COUNT(*) AS count FROM customers",
            "rows": [{"count": 0}],
            "tables_used": {},
        }
        database.get_customer_count()
        mock_scalar.assert_called_once_with(
            "SELECT COUNT(*) AS count FROM customers",
            (),
            {"customers": ["customer_id"]},
            "count",
        )

    @patch("database.run_traced_scalar")
    def test_customer_count_scoped_sql_and_params(self, mock_scalar):
        mock_scalar.return_value = {
            "sql": "scoped",
            "rows": [{"count": 0}],
            "tables_used": {},
        }
        database.get_customer_count(store_id=1)
        sql, params, _tables, _label = mock_scalar.call_args.args
        self.assertIn("store_id = %s", sql)
        self.assertEqual(params, (1,))

    @patch("database.run_scalar")
    def test_overdue_unscoped_sql_unchanged(self, mock_scalar):
        mock_scalar.return_value = 3
        database.get_overdue_account_count()
        sql = mock_scalar.call_args.args[0]
        self.assertNotIn("store_id", sql)
        self.assertIn("CURDATE()", sql)
        self.assertEqual(mock_scalar.call_args.kwargs.get("params"), None)
        # positional params default
        if len(mock_scalar.call_args.args) > 1:
            self.assertIsNone(mock_scalar.call_args.args[1])

    @patch("database.run_scalar")
    def test_overdue_scoped_sql_and_params(self, mock_scalar):
        mock_scalar.return_value = 1
        database.get_overdue_account_count(store_id=1)
        sql, params = mock_scalar.call_args.args[:2]
        self.assertIn("p.store_id = %s", sql)
        self.assertEqual(params, (1,))

    @patch("database.run_traced_query")
    def test_high_risk_unscoped_sql_unchanged(self, mock_query):
        mock_query.return_value = {"sql": "x", "rows": [], "tables_used": {}}
        database.get_high_risk_loans()
        sql, params = mock_query.call_args.args[:2]
        self.assertNotIn("store_id", sql)
        self.assertEqual(params, (75.0,))

    @patch("database.run_traced_query")
    def test_high_risk_scoped_constrains_customers_and_loans(self, mock_query):
        mock_query.return_value = {"sql": "x", "rows": [], "tables_used": {}}
        database.get_high_risk_loans(store_id=1)
        sql, params = mock_query.call_args.args[:2]
        self.assertIn("c.store_id = %s", sql)
        self.assertIn("l.store_id = %s", sql)
        self.assertEqual(params, (75.0, 1, 1))

    @patch("database.run_traced_query")
    def test_collateral_unscoped_sql_unchanged(self, mock_query):
        mock_query.return_value = {"sql": "x", "rows": [], "tables_used": {}}
        database.get_collateral_at_risk()
        sql, params = mock_query.call_args.args[:2]
        self.assertNotIn("store_id", sql)
        self.assertIsNone(params)

    @patch("database.run_traced_query")
    def test_collateral_scoped_constrains_all_three_tables(self, mock_query):
        mock_query.return_value = {"sql": "x", "rows": [], "tables_used": {}}
        database.get_collateral_at_risk(store_id=2)
        sql, params = mock_query.call_args.args[:2]
        self.assertIn("ci.store_id = %s", sql)
        self.assertIn("l.store_id = %s", sql)
        self.assertIn("c.store_id = %s", sql)
        # Business OR must stay parenthesized before tenant ANDs.
        self.assertIn("WHERE (", " ".join(sql.split()))
        self.assertEqual(params, (2, 2, 2))


class DashboardStatsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.addCleanup(lambda: os.environ.pop("TENANCY_ENFORCEMENT", None))
        os.environ["TENANCY_ENFORCEMENT"] = "0"
        os.environ["AUTH_REQUIRED"] = "0"

    @patch("app.get_dashboard_stats")
    def test_enforcement_off_unchanged_response(self, mock_stats):
        mock_stats.return_value = {
            "total_customers": 5,
            "overdue_payments": 4,
            "high_risk_loans": 1,
            "collateral_at_risk": 2,
        }
        os.environ["TENANCY_ENFORCEMENT"] = "0"

        response = self.client.get("/dashboard/stats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), mock_stats.return_value)
        mock_stats.assert_called_once_with()

    @patch("app.get_dashboard_stats")
    def test_enforcement_off_helper_called_without_store_id(self, mock_stats):
        mock_stats.return_value = {
            "total_customers": 0,
            "overdue_payments": 0,
            "high_risk_loans": 0,
            "collateral_at_risk": 0,
        }
        os.environ["TENANCY_ENFORCEMENT"] = "0"
        self.client.get("/dashboard/stats")
        mock_stats.assert_called_once_with()

    @patch("app.get_dashboard_stats")
    def test_enforcement_on_missing_session_returns_401(self, mock_stats):
        os.environ["TENANCY_ENFORCEMENT"] = "1"
        response = self.client.get("/dashboard/stats")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Authentication required", response.get_json()["error"])
        mock_stats.assert_not_called()

    @patch("app.get_dashboard_stats")
    def test_enforcement_on_missing_identity_does_not_hit_helpers(self, mock_stats):
        os.environ["TENANCY_ENFORCEMENT"] = "1"
        os.environ["AUTH_REQUIRED"] = "0"
        response = self.client.get("/dashboard/stats")
        self.assertEqual(response.status_code, 401)
        mock_stats.assert_not_called()

    @patch("app.get_dashboard_stats")
    @patch("auth.get_user_by_id")
    def test_enforcement_on_store1_passes_store_id_1(self, mock_user, mock_stats):
        os.environ["TENANCY_ENFORCEMENT"] = "1"
        mock_user.return_value = {
            "user_id": 1,
            "store_id": 1,
            "username": "store1_user_a",
            "password_hash": "x",
            "display_name": "Store 1 User A",
            "is_active": 1,
            "store_name": "Store 1",
        }
        mock_stats.return_value = {
            "total_customers": 5,
            "overdue_payments": 4,
            "high_risk_loans": 1,
            "collateral_at_risk": 2,
        }
        with self.client.session_transaction() as session:
            session[SESSION_USER_ID] = 1
            session[SESSION_STORE_ID] = 1

        response = self.client.get("/dashboard/stats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.get_json().keys()),
            {
                "total_customers",
                "overdue_payments",
                "high_risk_loans",
                "collateral_at_risk",
            },
        )
        mock_stats.assert_called_once_with(store_id=1)

    @patch("app.get_dashboard_stats")
    @patch("auth.get_user_by_id")
    def test_enforcement_on_store2_passes_store_id_2(self, mock_user, mock_stats):
        os.environ["TENANCY_ENFORCEMENT"] = "1"
        mock_user.return_value = {
            "user_id": 2,
            "store_id": 2,
            "username": "store2_user_b",
            "password_hash": "x",
            "display_name": "Store 2 User B",
            "is_active": 1,
            "store_name": "Store 2",
        }
        mock_stats.return_value = {
            "total_customers": 0,
            "overdue_payments": 0,
            "high_risk_loans": 0,
            "collateral_at_risk": 0,
        }
        with self.client.session_transaction() as session:
            session[SESSION_USER_ID] = 2
            session[SESSION_STORE_ID] = 2

        response = self.client.get("/dashboard/stats")

        self.assertEqual(response.status_code, 200)
        mock_stats.assert_called_once_with(store_id=2)

    @patch("app.get_dashboard_stats")
    @patch("auth.get_user_by_id")
    def test_query_string_store_id_cannot_override_identity(
        self, mock_user, mock_stats
    ):
        os.environ["TENANCY_ENFORCEMENT"] = "1"
        mock_user.return_value = {
            "user_id": 1,
            "store_id": 1,
            "username": "store1_user_a",
            "password_hash": "x",
            "display_name": "A",
            "is_active": 1,
            "store_name": "Store 1",
        }
        mock_stats.return_value = {
            "total_customers": 5,
            "overdue_payments": 0,
            "high_risk_loans": 0,
            "collateral_at_risk": 0,
        }
        with self.client.session_transaction() as session:
            session[SESSION_USER_ID] = 1
            session[SESSION_STORE_ID] = 1

        response = self.client.get("/dashboard/stats?store_id=2")

        self.assertEqual(response.status_code, 200)
        mock_stats.assert_called_once_with(store_id=1)

    @patch("app.get_dashboard_stats")
    @patch("auth.get_user_by_id")
    def test_request_body_store_id_cannot_override_identity(
        self, mock_user, mock_stats
    ):
        os.environ["TENANCY_ENFORCEMENT"] = "1"
        mock_user.return_value = {
            "user_id": 1,
            "store_id": 1,
            "username": "store1_user_a",
            "password_hash": "x",
            "display_name": "A",
            "is_active": 1,
            "store_name": "Store 1",
        }
        mock_stats.return_value = {
            "total_customers": 5,
            "overdue_payments": 0,
            "high_risk_loans": 0,
            "collateral_at_risk": 0,
        }
        with self.client.session_transaction() as session:
            session[SESSION_USER_ID] = 1
            session[SESSION_STORE_ID] = 1

        # GET with JSON body must still use session store_id only.
        response = self.client.open(
            "/dashboard/stats",
            method="GET",
            json={"store_id": 2},
        )

        self.assertEqual(response.status_code, 200)
        mock_stats.assert_called_once_with(store_id=1)

    @patch("app.get_dashboard_stats", side_effect=RuntimeError("db down"))
    def test_dashboard_stats_endpoint_returns_error(self, _mock_stats):
        os.environ["TENANCY_ENFORCEMENT"] = "0"
        response = self.client.get("/dashboard/stats")

        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.get_json())


if __name__ == "__main__":
    unittest.main()
