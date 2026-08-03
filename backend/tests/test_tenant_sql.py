"""Phase 3A: deterministic tenant SQL injection + fail-closed MCP gate."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from pawnshop_mcp.server import mcp
from sql_validation import validate_readonly_sql
from tenant_sql import (
    TRUSTED_STORE_ENV,
    apply_tenant_scope,
    clear_unlaunched_trusted_store_id,
    inject_tenant_predicates,
    parse_trusted_store_id,
    tenancy_enforcement_enabled,
)


def _norm(sql: str) -> str:
    return " ".join(sql.split())


class ParseTrustedStoreIdTests(unittest.TestCase):
    def test_accepts_positive_int(self):
        self.assertEqual(parse_trusted_store_id(1), 1)
        self.assertEqual(parse_trusted_store_id("2"), 2)

    def test_rejects_invalid(self):
        for raw in (None, "", "0", -1, "1.5", "abc", True, False, "01x"):
            self.assertIsNone(parse_trusted_store_id(raw), msg=repr(raw))


class TenancyFlagTests(unittest.TestCase):
    def test_defaults_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TENANCY_ENFORCEMENT", None)
            self.assertFalse(tenancy_enforcement_enabled())

    def test_enabled_values(self):
        for value in ("1", "true", "YES", "on"):
            with patch.dict(os.environ, {"TENANCY_ENFORCEMENT": value}):
                self.assertTrue(tenancy_enforcement_enabled())


class TenantInjectionTests(unittest.TestCase):
    def test_single_table_without_where(self):
        sql = "SELECT customer_id, full_name FROM customers"
        scoped = inject_tenant_predicates(sql, 1)
        self.assertEqual(
            _norm(scoped),
            "SELECT customer_id, full_name FROM customers WHERE customers.store_id = 1",
        )
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_single_table_with_where(self):
        sql = "SELECT customer_id FROM customers WHERE full_name = 'Priya Nair'"
        scoped = inject_tenant_predicates(sql, 1)
        self.assertEqual(
            _norm(scoped),
            "SELECT customer_id FROM customers WHERE (full_name = 'Priya Nair') "
            "AND customers.store_id = 1",
        )

    def test_where_containing_or(self):
        sql = (
            "SELECT customer_id FROM customers c "
            "WHERE c.full_name = 'A' OR c.full_name = 'B'"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertEqual(
            _norm(scoped),
            "SELECT customer_id FROM customers c "
            "WHERE (c.full_name = 'A' OR c.full_name = 'B') AND c.store_id = 1",
        )

    def test_inner_join(self):
        sql = (
            "SELECT c.full_name, l.loan_id FROM customers c "
            "INNER JOIN loans l ON c.customer_id = l.customer_id"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertEqual(
            _norm(scoped),
            "SELECT c.full_name, l.loan_id FROM customers c "
            "INNER JOIN loans l ON c.customer_id = l.customer_id "
            "WHERE c.store_id = 1 AND l.store_id = 1",
        )
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_multiple_inner_joins(self):
        sql = (
            "SELECT c.full_name, p.payment_id FROM customers c "
            "INNER JOIN loans l ON c.customer_id = l.customer_id "
            "INNER JOIN payments p ON l.loan_id = p.loan_id"
        )
        scoped = inject_tenant_predicates(sql, 2)
        self.assertIn("c.store_id = 2", scoped)
        self.assertIn("l.store_id = 2", scoped)
        self.assertIn("p.store_id = 2", scoped)
        self.assertNotIn("AND p.store_id", scoped.split("ON l.loan_id = p.loan_id")[1].split("WHERE")[0])
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_left_join(self):
        sql = (
            "SELECT c.full_name, p.payment_id FROM customers c "
            "LEFT JOIN loans l ON c.customer_id = l.customer_id "
            "LEFT JOIN payments p ON l.loan_id = p.loan_id"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn(
            "LEFT JOIN loans l ON c.customer_id = l.customer_id AND l.store_id = 1",
            _norm(scoped),
        )
        self.assertIn(
            "LEFT JOIN payments p ON l.loan_id = p.loan_id AND p.store_id = 1",
            _norm(scoped),
        )
        self.assertIn("WHERE c.store_id = 1", _norm(scoped))
        # Child LEFT JOIN predicates must not appear only in WHERE.
        where_part = _norm(scoped).split("WHERE", 1)[1]
        self.assertNotIn("l.store_id", where_part)
        self.assertNotIn("p.store_id", where_part)
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_multiple_left_joins(self):
        sql = (
            "SELECT c.full_name, ci.item_type FROM customers c "
            "LEFT JOIN loans l ON c.customer_id = l.customer_id "
            "LEFT JOIN collateral_items ci ON l.loan_id = ci.loan_id"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("AND l.store_id = 1", scoped)
        self.assertIn("AND ci.store_id = 1", scoped)
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_mixed_inner_and_left_join(self):
        sql = (
            "SELECT c.full_name, p.amount_due FROM customers c "
            "INNER JOIN loans l ON c.customer_id = l.customer_id "
            "LEFT JOIN payments p ON l.loan_id = p.loan_id"
        )
        scoped = inject_tenant_predicates(sql, 1)
        normalized = _norm(scoped)
        self.assertIn(
            "LEFT JOIN payments p ON l.loan_id = p.loan_id AND p.store_id = 1",
            normalized,
        )
        self.assertIn("WHERE c.store_id = 1 AND l.store_id = 1", normalized)
        where_part = normalized.split("WHERE", 1)[1]
        self.assertNotIn("p.store_id", where_part)
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_aliases(self):
        sql = "SELECT cust.full_name FROM customers AS cust"
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("cust.store_id = 1", scoped)

    def test_group_by_aggregate(self):
        sql = (
            "SELECT c.full_name, SUM(p.amount_due - p.amount_paid) AS total_owed "
            "FROM customers c "
            "JOIN loans l ON c.customer_id = l.customer_id "
            "JOIN payments p ON l.loan_id = p.loan_id "
            "GROUP BY c.customer_id, c.full_name"
        )
        scoped = inject_tenant_predicates(sql, 1)
        normalized = _norm(scoped)
        self.assertIn(
            "WHERE c.store_id = 1 AND l.store_id = 1 AND p.store_id = 1 GROUP BY",
            normalized,
        )
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_order_by(self):
        sql = (
            "SELECT c.full_name FROM customers c "
            "ORDER BY c.full_name ASC"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertEqual(
            _norm(scoped),
            "SELECT c.full_name FROM customers c WHERE c.store_id = 1 ORDER BY c.full_name ASC",
        )

    def test_limit(self):
        sql = "SELECT customer_id FROM customers LIMIT 5"
        scoped = inject_tenant_predicates(sql, 1)
        self.assertEqual(
            _norm(scoped),
            "SELECT customer_id FROM customers WHERE customers.store_id = 1 LIMIT 5",
        )

    def test_computed_remaining_due(self):
        sql = (
            "SELECT p.payment_id, (p.amount_due - p.amount_paid) AS remaining_due "
            "FROM payments p"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("p.store_id = 1", scoped)
        self.assertIn("remaining_due", scoped)
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_computed_ltv_percent(self):
        sql = (
            "SELECT l.loan_id, "
            "(l.current_balance / NULLIF(l.collateral_value, 0) * 100) AS ltv_percent "
            "FROM loans l"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("l.store_id = 1", scoped)
        self.assertIn("ltv_percent", scoped)
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_projection_enriched_customer_detail_style_sql(self):
        sql = (
            "SELECT c.customer_id, c.full_name, a.account_id, a.account_type, "
            "l.loan_id, l.loan_type, l.current_balance, l.collateral_value, "
            "(l.current_balance / NULLIF(l.collateral_value, 0) * 100) AS ltv_percent, "
            "p.payment_id, p.due_date, p.amount_due, p.amount_paid, "
            "(p.amount_due - p.amount_paid) AS remaining_due, "
            "ci.item_type, ci.item_description, ci.appraised_value "
            "FROM customers c "
            "LEFT JOIN accounts a ON c.customer_id = a.customer_id "
            "LEFT JOIN loans l ON c.customer_id = l.customer_id "
            "LEFT JOIN payments p ON l.loan_id = p.loan_id "
            "LEFT JOIN collateral_items ci ON l.loan_id = ci.loan_id "
            "WHERE c.full_name = 'Priya Nair'"
        )
        scoped = inject_tenant_predicates(sql, 1)
        normalized = _norm(scoped)
        self.assertIn("AND a.store_id = 1", normalized)
        self.assertIn("AND l.store_id = 1", normalized)
        self.assertIn("AND p.store_id = 1", normalized)
        self.assertIn("AND ci.store_id = 1", normalized)
        self.assertIn(
            "WHERE (c.full_name = 'Priya Nair') AND c.store_id = 1",
            normalized,
        )
        self.assertTrue(
            validate_readonly_sql(scoped, allow_tenant_predicates=True)["valid"]
        )

    def test_store1_and_store2_produce_different_scoped_sql(self):
        sql = (
            "SELECT c.full_name FROM customers c "
            "INNER JOIN loans l ON c.customer_id = l.customer_id "
            "WHERE c.full_name = 'Priya Nair'"
        )
        scoped_1 = inject_tenant_predicates(sql, 1)
        scoped_2 = inject_tenant_predicates(sql, 2)
        self.assertNotEqual(scoped_1, scoped_2)
        self.assertIn("c.store_id = 1", scoped_1)
        self.assertIn("l.store_id = 1", scoped_1)
        self.assertIn("c.store_id = 2", scoped_2)
        self.assertIn("l.store_id = 2", scoped_2)

    def test_gemini_cannot_select_store_id_without_tenant_mode(self):
        result = validate_readonly_sql("SELECT store_id FROM customers")
        self.assertFalse(result["valid"])

    def test_allow_tenant_predicates_still_rejects_select_store_id(self):
        result = validate_readonly_sql(
            "SELECT c.store_id FROM customers c",
            allow_tenant_predicates=True,
        )
        self.assertFalse(result["valid"])
        self.assertIn("store_id", result.get("reason") or "")

    def test_right_join_fails_closed_without_rewrite(self):
        sql = (
            "SELECT c.full_name, l.loan_id FROM customers c "
            "RIGHT JOIN loans l ON c.customer_id = l.customer_id"
        )
        self.assertTrue(validate_readonly_sql(sql)["valid"])
        with self.assertRaises(ValueError) as ctx:
            inject_tenant_predicates(sql, 1)
        self.assertIn("RIGHT JOIN", str(ctx.exception))
        scoped = apply_tenant_scope(sql, 1)
        self.assertFalse(scoped.applied)
        self.assertIsNone(scoped.sql)


class TenantSqlSpacingTests(unittest.TestCase):
    """Regression: clause-boundary whitespace after tenant WHERE injection."""

    def _assert_no_glued_tokens(self, sql: str) -> None:
        self.assertNotRegex(sql, r"\dORDER\b")
        self.assertNotRegex(sql, r"\dGROUP\b")
        self.assertNotRegex(sql, r"\dHAVING\b")
        self.assertNotRegex(sql, r"\dLIMIT\b")
        self.assertNotIn("1ORDER", sql)
        self.assertNotIn("1LIMIT", sql)
        self.assertNotIn("customersAS", sql)
        self.assertNotIn("paymentsAS", sql)
        self.assertNotIn("loansAS", sql)

    def test_where_plus_order_by_spacing(self):
        sql = (
            "SELECT c.full_name FROM customers AS c "
            "WHERE c.full_name = 'A' "
            "ORDER BY c.full_name"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("c.store_id = 1 ORDER BY", scoped)
        self._assert_no_glued_tokens(scoped)
        self.assertIn("customers AS c", scoped)

    def test_where_plus_group_by_spacing(self):
        sql = (
            "SELECT c.full_name, COUNT(l.loan_id) AS loan_count "
            "FROM customers AS c "
            "JOIN loans AS l ON c.customer_id = l.customer_id "
            "WHERE c.customer_id > 0 "
            "GROUP BY c.customer_id, c.full_name"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("l.store_id = 1 GROUP BY", scoped)
        self._assert_no_glued_tokens(scoped)
        self.assertIn("customers AS c", scoped)
        self.assertIn("loans AS l", scoped)

    def test_group_by_plus_having_spacing(self):
        sql = (
            "SELECT c.full_name, SUM(p.amount_due) AS total_due "
            "FROM customers AS c "
            "JOIN loans AS l ON c.customer_id = l.customer_id "
            "JOIN payments AS p ON l.loan_id = p.loan_id "
            "GROUP BY c.customer_id, c.full_name "
            "HAVING SUM(p.amount_due) > 0"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("p.store_id = 1 GROUP BY", scoped)
        self.assertIn("GROUP BY c.customer_id, c.full_name HAVING", _norm(scoped))
        self._assert_no_glued_tokens(scoped)
        self.assertIn("payments AS p", scoped)

    def test_limit_spacing(self):
        sql = "SELECT customer_id FROM customers WHERE customer_id > 0 LIMIT 5"
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("customers.store_id = 1 LIMIT", scoped)
        self._assert_no_glued_tokens(scoped)

    def test_no_where_plus_order_by_spacing(self):
        sql = "SELECT c.full_name FROM customers AS c ORDER BY c.full_name"
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("c.store_id = 1 ORDER BY", scoped)
        self._assert_no_glued_tokens(scoped)
        self.assertIn("customers AS c", scoped)

    def test_multiline_sql_spacing(self):
        sql = (
            "SELECT c.full_name\n"
            "FROM customers AS c\n"
            "JOIN loans AS l ON c.customer_id = l.customer_id\n"
            "JOIN payments AS p ON l.loan_id = p.loan_id\n"
            "WHERE p.amount_due > 0\n"
            "ORDER BY p.due_date\n"
            "LIMIT 10"
        )
        scoped = inject_tenant_predicates(sql, 1)
        self.assertIn("p.store_id = 1 ORDER BY", scoped)
        self._assert_no_glued_tokens(scoped)
        self.assertIn("customers AS c", scoped)
        self.assertIn("payments AS p", scoped)

    def test_live_overdue_sql_spacing_through_apply_tenant_scope(self):
        sql = (
            "SELECT c.customer_id, c.full_name, l.loan_type, p.amount_due, "
            "p.amount_paid, (p.amount_due - p.amount_paid) AS remaining_due, "
            "p.due_date, "
            "(l.current_balance / NULLIF(l.collateral_value, 0) * 100) AS ltv_percent "
            "FROM customers c "
            "JOIN loans l ON c.customer_id = l.customer_id "
            "JOIN payments p ON l.loan_id = p.loan_id "
            "WHERE p.due_date < CURRENT_DATE AND p.amount_paid < p.amount_due "
            "ORDER BY p.due_date"
        )
        result = apply_tenant_scope(sql, 1)
        self.assertTrue(result.applied, result.reason)
        scoped = result.sql or ""
        self.assertIn("p.store_id = 1 ORDER BY", scoped)
        self.assertIn("c.store_id = 1", scoped)
        self.assertIn("l.store_id = 1", scoped)
        self._assert_no_glued_tokens(scoped)
        # Revalidation must keep a single trailing LIMIT, not 1LIMIT / double LIMIT glue.
        self.assertNotIn("1LIMIT", scoped)
        self.assertEqual(scoped.upper().count("LIMIT"), 1)
        revalidation = validate_readonly_sql(scoped, allow_tenant_predicates=True)
        self.assertTrue(revalidation["valid"], revalidation.get("reason"))


class ApplyTenantScopeTests(unittest.TestCase):
    def test_invalid_store_id_fails_closed(self):
        result = apply_tenant_scope("SELECT customer_id FROM customers", 0)
        self.assertFalse(result.applied)
        self.assertIsNone(result.sql)

    def test_revalidation_failure_fails_closed(self):
        sql = "SELECT customer_id FROM customers"
        first = validate_readonly_sql(sql)
        self.assertTrue(first["valid"])

        def fake_validate(query, *, allow_contact_fields=False, allow_tenant_predicates=False):
            if allow_tenant_predicates:
                return {
                    "valid": False,
                    "reason": "forced revalidation failure",
                    "normalized_sql": None,
                    "tables_used": [],
                    "columns_used": [],
                }
            return validate_readonly_sql(query)

        with patch("tenant_sql.validate_readonly_sql", side_effect=fake_validate):
            result = apply_tenant_scope(sql, 1, prevalidated=first)
        self.assertFalse(result.applied)
        self.assertIsNone(result.sql)
        self.assertIn("revalidation", (result.reason or "").lower())


class ExecuteSafeSqlTenantGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_enforcement_off_unchanged_sql_behavior(self):
        trace_result = {
            "sql": "SELECT customer_id FROM customers LIMIT 100",
            "results": [{"customer_id": 1}],
        }
        with (
            patch.dict(os.environ, {"TENANCY_ENFORCEMENT": "0"}, clear=False),
            patch(
                "pawnshop_mcp.server.run_traced_query",
                return_value=trace_result,
            ) as mock_run,
            patch(
                "pawnshop_mcp.server.extract_rows",
                return_value=[{"customer_id": 1}],
            ),
        ):
            os.environ.pop(TRUSTED_STORE_ENV, None)
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertTrue(payload["success"])
        self.assertEqual(
            payload["sql"],
            "SELECT customer_id FROM customers LIMIT 100",
        )
        mock_run.assert_called_once_with(
            "SELECT customer_id FROM customers LIMIT 100",
            tables_used={"customers": []},
        )

    async def test_missing_trusted_store_id_fails_closed(self):
        with (
            patch.dict(os.environ, {"TENANCY_ENFORCEMENT": "1"}, clear=False),
            patch("pawnshop_mcp.server.run_traced_query") as mock_run,
        ):
            os.environ.pop(TRUSTED_STORE_ENV, None)
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertFalse(payload["success"])
        self.assertIsNone(payload["sql"])
        self.assertEqual(payload["rows"], [])
        mock_run.assert_not_called()

    async def test_invalid_trusted_store_id_fails_closed(self):
        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "1", TRUSTED_STORE_ENV: "0"},
                clear=False,
            ),
            patch("pawnshop_mcp.server.run_traced_query") as mock_run,
        ):
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertFalse(payload["success"])
        self.assertIsNone(payload["sql"])
        mock_run.assert_not_called()

    async def test_enforcement_on_executes_scoped_sql_and_audit(self):
        scoped_rows = [{"customer_id": 9}]
        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "1", TRUSTED_STORE_ENV: "1"},
                clear=False,
            ),
            patch(
                "pawnshop_mcp.server.run_traced_query",
                return_value={"sql": "scoped", "results": scoped_rows},
            ) as mock_run,
            patch(
                "pawnshop_mcp.server.extract_rows",
                return_value=scoped_rows,
            ),
        ):
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["rows"], scoped_rows)
        executed_sql = mock_run.call_args.args[0]
        self.assertIn("store_id = 1", executed_sql)
        self.assertEqual(payload["sql"], executed_sql)
        self.assertTrue(payload["tenant_scope"]["applied"])
        self.assertEqual(payload["tenant_scope"]["store_id"], 1)

    async def test_user_supplied_store_id_in_sql_cannot_override_trusted_identity(self):
        """Gemini cannot filter by store_id; first validation rejects it."""
        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "1", TRUSTED_STORE_ENV: "1"},
                clear=False,
            ),
            patch("pawnshop_mcp.server.run_traced_query") as mock_run,
        ):
            result = await mcp.call_tool(
                "execute_safe_sql",
                {
                    "sql": (
                        "SELECT customer_id FROM customers "
                        "WHERE customers.store_id = 2"
                    )
                },
            )
        payload = json.loads(result[0].text)
        self.assertFalse(payload["success"])
        mock_run.assert_not_called()

    async def test_revalidation_failure_does_not_execute(self):
        first_ok = validate_readonly_sql("SELECT customer_id FROM customers")

        def fake_validate(query, *, allow_contact_fields=False, allow_tenant_predicates=False):
            if allow_tenant_predicates:
                return {
                    "valid": False,
                    "reason": "forced revalidation failure",
                    "normalized_sql": None,
                    "tables_used": [],
                    "columns_used": [],
                }
            return first_ok if "store_id" not in query else first_ok

        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "1", TRUSTED_STORE_ENV: "1"},
                clear=False,
            ),
            patch("pawnshop_mcp.server.validate_readonly_sql", side_effect=fake_validate),
            patch("tenant_sql.validate_readonly_sql", side_effect=fake_validate),
            patch("pawnshop_mcp.server.run_traced_query") as mock_run,
        ):
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertFalse(payload["success"])
        self.assertIsNone(payload["sql"])
        mock_run.assert_not_called()

    async def test_trusted_store_env_ignored_when_enforcement_off(self):
        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "0", TRUSTED_STORE_ENV: "2"},
                clear=False,
            ),
            patch(
                "pawnshop_mcp.server.run_traced_query",
                return_value={"sql": "x", "results": []},
            ) as mock_run,
            patch("pawnshop_mcp.server.extract_rows", return_value=[]),
        ):
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertTrue(payload["success"])
        self.assertEqual(
            mock_run.call_args.args[0],
            "SELECT customer_id FROM customers LIMIT 100",
        )
        self.assertNotIn("store_id", payload["sql"])

    async def test_dotenv_only_trusted_store_fails_closed(self):
        """Client omitted launch env; .env-only value must not become identity."""
        with (
            patch.dict(os.environ, {"TENANCY_ENFORCEMENT": "1"}, clear=False),
            patch("pawnshop_mcp.server.run_traced_query") as mock_run,
        ):
            os.environ.pop(TRUSTED_STORE_ENV, None)
            # Simulate load_dotenv() inserting the key after launch without it.
            os.environ[TRUSTED_STORE_ENV] = "99"
            clear_unlaunched_trusted_store_id(present_at_process_launch=False)
            self.assertNotIn(TRUSTED_STORE_ENV, os.environ)

            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertFalse(payload["success"])
        self.assertIsNone(payload["sql"])
        mock_run.assert_not_called()

    async def test_explicit_launch_trusted_store_still_works(self):
        """Client-supplied launch env survives dotenv provenance clearing."""
        scoped_rows = [{"customer_id": 3}]
        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "1", TRUSTED_STORE_ENV: "2"},
                clear=False,
            ),
            patch(
                "pawnshop_mcp.server.run_traced_query",
                return_value={"sql": "scoped", "results": scoped_rows},
            ) as mock_run,
            patch(
                "pawnshop_mcp.server.extract_rows",
                return_value=scoped_rows,
            ),
        ):
            clear_unlaunched_trusted_store_id(present_at_process_launch=True)
            self.assertEqual(os.environ.get(TRUSTED_STORE_ENV), "2")
            result = await mcp.call_tool(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
            )
        payload = json.loads(result[0].text)
        self.assertTrue(payload["success"])
        executed_sql = mock_run.call_args.args[0]
        self.assertIn("store_id = 2", executed_sql)
        self.assertEqual(payload["sql"], executed_sql)

    async def test_right_join_enforcement_on_fails_closed_no_db(self):
        sql = (
            "SELECT c.full_name, l.loan_id FROM customers c "
            "RIGHT JOIN loans l ON c.customer_id = l.customer_id"
        )
        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "1", TRUSTED_STORE_ENV: "1"},
                clear=False,
            ),
            patch("pawnshop_mcp.server.run_traced_query") as mock_run,
        ):
            result = await mcp.call_tool("execute_safe_sql", {"sql": sql})
        payload = json.loads(result[0].text)
        self.assertFalse(payload["success"])
        self.assertIsNone(payload["sql"])
        self.assertIn("RIGHT JOIN", payload.get("error") or "")
        mock_run.assert_not_called()

    async def test_left_join_still_scopes_correctly_under_enforcement(self):
        sql = (
            "SELECT c.full_name, p.payment_id FROM customers c "
            "LEFT JOIN loans l ON c.customer_id = l.customer_id "
            "LEFT JOIN payments p ON l.loan_id = p.loan_id"
        )
        with (
            patch.dict(
                os.environ,
                {"TENANCY_ENFORCEMENT": "1", TRUSTED_STORE_ENV: "1"},
                clear=False,
            ),
            patch(
                "pawnshop_mcp.server.run_traced_query",
                return_value={"sql": "scoped", "results": []},
            ) as mock_run,
            patch("pawnshop_mcp.server.extract_rows", return_value=[]),
        ):
            result = await mcp.call_tool("execute_safe_sql", {"sql": sql})
        payload = json.loads(result[0].text)
        self.assertTrue(payload["success"])
        executed = mock_run.call_args.args[0]
        self.assertIn(
            "LEFT JOIN loans l ON c.customer_id = l.customer_id AND l.store_id = 1",
            " ".join(executed.split()),
        )
        self.assertIn(
            "LEFT JOIN payments p ON l.loan_id = p.loan_id AND p.store_id = 1",
            " ".join(executed.split()),
        )
        self.assertIn("c.store_id = 1", executed)
        where_part = executed.upper().split("WHERE", 1)[1]
        self.assertNotIn("L.STORE_ID", where_part)
        self.assertNotIn("P.STORE_ID", where_part)


class TrustedStoreProvenanceTests(unittest.TestCase):
    def test_clear_unlaunched_removes_dotenv_only_value(self):
        with patch.dict(os.environ, {TRUSTED_STORE_ENV: "99"}, clear=False):
            clear_unlaunched_trusted_store_id(present_at_process_launch=False)
            self.assertNotIn(TRUSTED_STORE_ENV, os.environ)

    def test_clear_unlaunched_keeps_explicit_launch_value(self):
        with patch.dict(os.environ, {TRUSTED_STORE_ENV: "1"}, clear=False):
            clear_unlaunched_trusted_store_id(present_at_process_launch=True)
            self.assertEqual(os.environ.get(TRUSTED_STORE_ENV), "1")


class McpClientTrustedStoreEnvTests(unittest.TestCase):
    def test_ambient_trusted_store_env_is_cleared_unless_explicit(self):
        from pawnshop_mcp import client as mcp_client

        parent = {
            "PATH": "/usr/bin",
            "DB_HOST": "localhost",
            "DB_USER": "root",
            "DB_PASSWORD": "x",
            "DB_NAME": "telleriq_db",
            TRUSTED_STORE_ENV: "99",
        }
        with patch.dict(os.environ, parent, clear=True):
            params = mcp_client._server_parameters()
            self.assertNotIn(TRUSTED_STORE_ENV, params.env)

            params_set = mcp_client._server_parameters(trusted_store_id=1)
            self.assertEqual(params_set.env[TRUSTED_STORE_ENV], "1")

    def test_invalid_explicit_trusted_store_not_set(self):
        from pawnshop_mcp import client as mcp_client

        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            params = mcp_client._server_parameters(trusted_store_id="0")
            self.assertNotIn(TRUSTED_STORE_ENV, params.env)


class LlmChatTrustedStorePropagationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import lazily; some environments segfault on google.genai import in
        # tight sandbox runs. Skip cleanly if unavailable.
        try:
            import llm_chat as llm_chat_module
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"llm_chat unavailable: {exc}") from exc
        cls.llm_chat = llm_chat_module

    def test_call_mcp_tool_safe_forwards_trusted_store_id(self):
        with patch.object(self.llm_chat, "call_mcp_tool") as mock_call:
            mock_call.return_value = {"success": True}
            self.llm_chat._call_mcp_tool_safe(
                "execute_safe_sql",
                {"sql": "SELECT customer_id FROM customers"},
                trusted_store_id=2,
            )
        mock_call.assert_called_once_with(
            "execute_safe_sql",
            {"sql": "SELECT customer_id FROM customers"},
            trusted_store_id=2,
        )

    def test_sanitize_strips_gemini_store_id_args(self):
        args = {
            "sql": "SELECT customer_id FROM customers",
            "store_id": 99,
            "trusted_store_id": 99,
        }
        cleaned = self.llm_chat._sanitize_mcp_tool_args("execute_safe_sql", args)
        self.assertEqual(cleaned, {"sql": "SELECT customer_id FROM customers"})
        self.assertNotIn("store_id", args)


if __name__ == "__main__":
    unittest.main()
