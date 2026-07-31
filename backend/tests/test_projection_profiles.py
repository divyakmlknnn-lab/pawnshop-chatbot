"""Focused tests for deterministic SELECT projection enrichment."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from intent import (
    COLLATERAL_RISK,
    CUSTOMER_SUMMARY,
    HIGH_RISK_LOANS,
    MISSED_PAYMENTS,
    OVERDUE_CUSTOMERS,
    TOTAL_OVERDUE,
)
from projection_profiles import (
    enrich_select_projection,
    profile_for_intent,
)
from sql_validation import validate_readonly_sql


class ProjectionProfileMappingTests(unittest.TestCase):
    def test_intent_maps_to_deterministic_profiles(self):
        self.assertEqual(profile_for_intent(CUSTOMER_SUMMARY), "customer_detail")
        self.assertEqual(profile_for_intent(OVERDUE_CUSTOMERS), "overdue_payments")
        self.assertEqual(profile_for_intent(MISSED_PAYMENTS), "overdue_payments")
        self.assertEqual(profile_for_intent(HIGH_RISK_LOANS), "high_risk_loans")
        self.assertEqual(profile_for_intent(COLLATERAL_RISK), "collateral_detail")
        self.assertIsNone(profile_for_intent(TOTAL_OVERDUE))
        self.assertIsNone(profile_for_intent("UNKNOWN"))


class ProjectionEnrichmentTests(unittest.TestCase):
    def test_customer_detail_thin_query_becomes_rich_multi_table(self):
        thin = (
            "SELECT customer_id, full_name "
            "FROM customers "
            "WHERE full_name = 'Priya Nair'"
        )
        result = enrich_select_projection(thin, intent=CUSTOMER_SUMMARY)

        self.assertTrue(result.applied, result.reason)
        self.assertEqual(result.profile, "customer_detail")
        sql = result.sql.lower()
        self.assertIn("join loans", sql)
        self.assertIn("join payments", sql)
        self.assertIn("join collateral_items", sql)
        for field in (
            "loan_type",
            "current_balance",
            "remaining_due",
            "ltv_percent",
            "item_type",
            "appraised_value",
        ):
            self.assertIn(field, sql)
        self.assertNotIn("phone", sql)
        self.assertNotIn("email", sql)

        validation = validate_readonly_sql(result.sql)
        self.assertTrue(validation["valid"], validation.get("reason"))

    def test_overdue_thin_query_becomes_rich_payment_customer_loan(self):
        thin = (
            "SELECT c.full_name "
            "FROM customers c "
            "JOIN loans l ON l.customer_id = c.customer_id "
            "JOIN payments p ON p.loan_id = l.loan_id "
            "WHERE p.due_date < CURDATE() AND p.amount_paid < p.amount_due"
        )
        result = enrich_select_projection(thin, intent=OVERDUE_CUSTOMERS)

        self.assertTrue(result.applied, result.reason)
        sql = result.sql
        self.assertIn("amount_due", sql.lower())
        self.assertIn("remaining_due", sql.lower())
        self.assertIn("loan_type", sql.lower())
        self.assertIn("ltv_percent", sql.lower())
        # Existing joins preserved; no invented tables.
        self.assertNotIn("collateral_items", sql.lower())
        self.assertTrue(validate_readonly_sql(result.sql)["valid"])

    def test_overdue_without_joins_adds_approved_joins(self):
        thin = (
            "SELECT full_name FROM customers "
            "WHERE full_name = 'Asha Patel'"
        )
        result = enrich_select_projection(thin, intent=MISSED_PAYMENTS)
        self.assertTrue(result.applied, result.reason)
        sql = result.sql.lower()
        self.assertIn("join loans", sql)
        self.assertIn("join payments", sql)
        self.assertIn("remaining_due", sql)
        self.assertTrue(validate_readonly_sql(result.sql)["valid"])

    def test_ambiguous_where_skips_join_expansion(self):
        # Bare customer_id is shared by customers/loans; preserve WHERE exactly
        # by refusing join expansion rather than rewriting the predicate.
        thin = "SELECT full_name FROM customers WHERE customer_id = 1"
        result = enrich_select_projection(thin, intent=MISSED_PAYMENTS)
        sql = result.sql.lower()
        self.assertNotIn("join loans", sql)
        self.assertNotIn("join payments", sql)
        self.assertIn("where customer_id = 1", sql)

    def test_collateral_thin_query_gains_collateral_fields(self):
        thin = (
            "SELECT c.full_name "
            "FROM customers c "
            "JOIN loans l ON l.customer_id = c.customer_id "
            "JOIN collateral_items ci ON ci.loan_id = l.loan_id "
            "WHERE ci.item_type = 'iPhone'"
        )
        result = enrich_select_projection(thin, intent=COLLATERAL_RISK)
        self.assertTrue(result.applied, result.reason)
        sql = result.sql.lower()
        self.assertIn("item_type", sql)
        self.assertIn("item_description", sql)
        self.assertIn("appraised_value", sql)
        self.assertIn("item_status", sql)
        self.assertTrue(validate_readonly_sql(result.sql)["valid"])

    def test_aggregate_queries_remain_unchanged(self):
        aggregate = (
            "SELECT COUNT(payment_id) AS missed_payment_count "
            "FROM payments "
            "WHERE due_date < CURDATE() AND amount_paid < amount_due"
        )
        result = enrich_select_projection(aggregate, intent=MISSED_PAYMENTS)
        self.assertFalse(result.applied)
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "aggregate_query")
        self.assertEqual(result.sql, aggregate)

        ranking = (
            "SELECT c.customer_id, c.full_name, "
            "SUM(p.amount_due - p.amount_paid) AS total_overdue "
            "FROM customers c "
            "JOIN loans l ON l.customer_id = c.customer_id "
            "JOIN payments p ON p.loan_id = l.loan_id "
            "WHERE p.due_date < CURDATE() "
            "GROUP BY c.customer_id, c.full_name "
            "ORDER BY total_overdue DESC LIMIT 5"
        )
        result = enrich_select_projection(ranking, intent=OVERDUE_CUSTOMERS)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "aggregate_query")
        self.assertEqual(result.sql, ranking)

    def test_where_clause_preserved_exactly(self):
        where = "full_name = 'Priya Nair'"
        thin = f"SELECT customer_id, full_name FROM customers WHERE {where}"
        result = enrich_select_projection(thin, intent=CUSTOMER_SUMMARY)
        self.assertTrue(result.applied, result.reason)
        # Exact WHERE predicate text must survive enrichment.
        self.assertIn(f"WHERE {where}", result.sql)

    def test_never_adds_phone_or_email_by_default(self):
        thin = (
            "SELECT customer_id, full_name FROM customers "
            "WHERE full_name = 'Priya Nair'"
        )
        result = enrich_select_projection(thin, intent=CUSTOMER_SUMMARY)
        self.assertTrue(result.applied, result.reason)
        self.assertNotRegex(result.sql, r"(?i)\bphone\b")
        self.assertNotRegex(result.sql, r"(?i)\bemail\b")

    def test_unsafe_unknown_joins_are_never_added(self):
        # accounts has no path to collateral_items without going through customers/loans.
        # Enrichment may add only approved relationship edges.
        thin = "SELECT account_id, balance FROM accounts WHERE status = 'active'"
        result = enrich_select_projection(thin, intent=COLLATERAL_RISK)
        if result.applied:
            sql = result.sql.lower()
            # Every JOIN must reference an approved table pair.
            self.assertNotIn("join unknown", sql)
            for fragment in ("join customers", "join loans", "join collateral_items"):
                if fragment in sql:
                    validation = validate_readonly_sql(result.sql)
                    self.assertTrue(validation["valid"], validation.get("reason"))
            # No non-schema join predicates.
            self.assertNotIn("on 1=1", sql)
        else:
            self.assertIn(
                result.reason,
                {
                    "required_joins_unavailable",
                    "nothing_to_add",
                    "no_actionable_fields",
                },
            )

    def test_invalid_enriched_sql_falls_back_to_original(self):
        thin = (
            "SELECT customer_id, full_name "
            "FROM customers "
            "WHERE full_name = 'Priya Nair'"
        )
        with patch(
            "projection_profiles.validate_readonly_sql",
            side_effect=[
                {"valid": False, "reason": "forced validation failure"},
            ],
        ):
            result = enrich_select_projection(thin, intent=CUSTOMER_SUMMARY)

        self.assertFalse(result.applied)
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "validation_failed")
        self.assertEqual(result.sql, thin)
        self.assertIsNotNone(result.attempted_sql)
        self.assertEqual(result.validation_error, "forced validation failure")

    def test_final_enriched_sql_passes_existing_validator(self):
        cases = [
            (
                CUSTOMER_SUMMARY,
                "SELECT customer_id, full_name FROM customers WHERE full_name = 'A'",
            ),
            (
                OVERDUE_CUSTOMERS,
                "SELECT c.full_name FROM customers c "
                "JOIN loans l ON l.customer_id = c.customer_id "
                "JOIN payments p ON p.loan_id = l.loan_id "
                "WHERE p.due_date < CURDATE()",
            ),
            (
                HIGH_RISK_LOANS,
                "SELECT l.loan_id FROM loans l "
                "JOIN customers c ON c.customer_id = l.customer_id "
                "WHERE l.current_balance > 0",
            ),
            (
                COLLATERAL_RISK,
                "SELECT ci.item_id FROM collateral_items ci "
                "JOIN loans l ON l.loan_id = ci.loan_id "
                "JOIN customers c ON c.customer_id = l.customer_id "
                "WHERE ci.item_status = 'held'",
            ),
        ]
        for intent, sql in cases:
            with self.subTest(intent=intent):
                result = enrich_select_projection(sql, intent=intent)
                self.assertTrue(result.applied, result.reason)
                validation = validate_readonly_sql(result.sql)
                self.assertTrue(validation["valid"], validation.get("reason"))


class ExecutePathEnrichmentIntegrationTests(unittest.TestCase):
    def test_execute_safe_sql_enriches_before_mcp_call(self):
        from intent import IntentClassification
        from llm_chat import _execute_tool_call

        classification = IntentClassification(
            intent=CUSTOMER_SUMMARY,
            confidence=0.9,
            tool="execute_safe_sql",
            args={},
        )
        tool_args = {
            "sql": (
                "SELECT customer_id, full_name "
                "FROM customers "
                "WHERE full_name = 'Priya Nair'"
            )
        }
        captured = {}

        def fake_mcp(tool_name, tool_args_inner):
            captured["tool"] = tool_name
            captured["sql"] = tool_args_inner.get("sql")
            return {
                "success": True,
                "rows": [],
                "trace": {"sql": tool_args_inner.get("sql"), "tables_used": {}, "rows": []},
            }

        with patch("llm_chat._call_mcp_tool_safe", side_effect=fake_mcp):
            result = _execute_tool_call(
                "execute_safe_sql",
                tool_args,
                classification=classification,
                user_message="Show Priya Nair details",
            )

        self.assertIn("join loans", captured["sql"].lower())
        self.assertTrue(result["projection_enrichment"]["applied"])
        self.assertEqual(tool_args["sql"], captured["sql"])

    def test_execute_safe_sql_records_skip_on_validation_fallback(self):
        from intent import IntentClassification
        from llm_chat import _execute_tool_call

        classification = IntentClassification(
            intent=CUSTOMER_SUMMARY,
            confidence=0.9,
            tool="execute_safe_sql",
            args={},
        )
        original = "SELECT customer_id, full_name FROM customers WHERE full_name = 'A'"
        tool_args = {"sql": original}

        with patch(
            "llm_chat.enrich_select_projection",
            return_value=__import__(
                "projection_profiles", fromlist=["EnrichmentResult"]
            ).EnrichmentResult(
                sql=original,
                original_sql=original,
                applied=False,
                skipped=True,
                reason="validation_failed",
                profile="customer_detail",
                attempted_sql="SELECT bad FROM customers",
                validation_error="forced",
            ),
        ), patch(
            "llm_chat._call_mcp_tool_safe",
            return_value={"success": True, "rows": [], "trace": {}},
        ) as mcp_mock:
            result = _execute_tool_call(
                "execute_safe_sql",
                tool_args,
                classification=classification,
                user_message="customer A",
            )

        mcp_mock.assert_called_once()
        self.assertEqual(tool_args["sql"], original)
        self.assertTrue(result["projection_enrichment"]["skipped"])
        self.assertEqual(
            result["projection_enrichment"]["reason"],
            "validation_failed",
        )


if __name__ == "__main__":
    unittest.main()
