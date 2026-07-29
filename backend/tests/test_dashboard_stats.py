import unittest
from unittest.mock import patch

import database
from app import app


class DashboardStatsTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

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
        mock_customer_count.assert_called_once_with()
        mock_overdue_count.assert_called_once_with()
        mock_high_risk.assert_called_once_with()
        mock_collateral.assert_called_once_with()

    @patch("app.get_dashboard_stats")
    def test_dashboard_stats_endpoint_returns_json(self, mock_stats):
        mock_stats.return_value = {
            "total_customers": 5,
            "overdue_payments": 4,
            "high_risk_loans": 1,
            "collateral_at_risk": 2,
        }

        response = self.client.get("/dashboard/stats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), mock_stats.return_value)

    @patch("app.get_dashboard_stats", side_effect=RuntimeError("db down"))
    def test_dashboard_stats_endpoint_returns_error(self, _mock_stats):
        response = self.client.get("/dashboard/stats")

        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.get_json())


if __name__ == "__main__":
    unittest.main()
