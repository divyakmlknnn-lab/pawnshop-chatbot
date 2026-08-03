"""Focused unit tests for Phase 3C Store 2 portfolio seeder (no real MySQL)."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BACKEND_ROOT, "scripts")
SEED_PATH = os.path.join(SCRIPTS_DIR, "seed_phase3c_store2_portfolio.py")


def _load_seed_module():
    """Load the seed script as a module without executing main()."""
    if BACKEND_ROOT not in sys.path:
        sys.path.insert(0, BACKEND_ROOT)
    spec = importlib.util.spec_from_file_location(
        "seed_phase3c_store2_portfolio", SEED_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with patch.dict(os.environ, {"DB_HOST": "unused"}, clear=False):
        with patch("database.get_connection", return_value=MagicMock()):
            spec.loader.exec_module(module)
    return module


seed = _load_seed_module()


def _ltv_percent(balance: float, collateral: float) -> float:
    return (balance / collateral) * 100


def _norm(sql: str) -> str:
    return " ".join(sql.split()).lower()


class FakeCursor:
    """Minimal in-memory cursor that understands Phase 3C seed/verify SQL."""

    def __init__(self, db: "FakeDB"):
        self.db = db
        self.lastrowid = None
        self.rowcount = 0
        self._result = None
        self._results = None

    def execute(self, sql: str, params=None):
        params = params or ()
        n = _norm(sql)
        self._result = None
        self._results = None
        self.lastrowid = None
        self.rowcount = 0

        if n == "start transaction":
            return

        if "from stores where store_id" in n:
            store_id = params[0]
            row = next((s for s in self.db.stores if s["store_id"] == store_id), None)
            self._result = row
            return

        if n.startswith("select customer_id from customers"):
            store_id, email = params
            row = next(
                (
                    c
                    for c in self.db.customers
                    if c["store_id"] == store_id and c["email"] == email
                ),
                None,
            )
            self._result = {"customer_id": row["customer_id"]} if row else None
            return

        if n.startswith("insert into customers"):
            customer_id = self.db.next_id("customer")
            self.db.customers.append(
                {
                    "customer_id": customer_id,
                    "store_id": params[0],
                    "full_name": params[1],
                    "phone": params[2],
                    "email": params[3],
                }
            )
            self.lastrowid = customer_id
            self.rowcount = 1
            return

        if n.startswith("update customers"):
            full_name, phone, customer_id, store_id = params
            for c in self.db.customers:
                if c["customer_id"] == customer_id and c["store_id"] == store_id:
                    c["full_name"] = full_name
                    c["phone"] = phone
                    self.rowcount = 1
                    return
            return

        if n.startswith("select account_id from accounts"):
            store_id, customer_id, account_type = params
            row = next(
                (
                    a
                    for a in self.db.accounts
                    if a["store_id"] == store_id
                    and a["customer_id"] == customer_id
                    and a["account_type"] == account_type
                ),
                None,
            )
            self._result = {"account_id": row["account_id"]} if row else None
            return

        if n.startswith("insert into accounts"):
            account_id = self.db.next_id("account")
            self.db.accounts.append(
                {
                    "account_id": account_id,
                    "store_id": params[0],
                    "customer_id": params[1],
                    "account_type": params[2],
                    "balance": params[3],
                    "status": params[4],
                }
            )
            self.lastrowid = account_id
            self.rowcount = 1
            return

        if n.startswith("update accounts"):
            balance, status, account_id, store_id = params
            for a in self.db.accounts:
                if a["account_id"] == account_id and a["store_id"] == store_id:
                    a["balance"] = balance
                    a["status"] = status
                    self.rowcount = 1
                    return
            return

        if n.startswith("select loan_id from loans"):
            store_id, customer_id, loan_type = params
            row = next(
                (
                    loan
                    for loan in self.db.loans
                    if loan["store_id"] == store_id
                    and loan["customer_id"] == customer_id
                    and loan["loan_type"] == loan_type
                ),
                None,
            )
            self._result = {"loan_id": row["loan_id"]} if row else None
            return

        if n.startswith("insert into loans"):
            loan_id = self.db.next_id("loan")
            self.db.loans.append(
                {
                    "loan_id": loan_id,
                    "store_id": params[0],
                    "customer_id": params[1],
                    "loan_type": params[2],
                    "current_balance": params[3],
                    "collateral_value": params[4],
                    "next_due_date": params[5],
                }
            )
            self.lastrowid = loan_id
            self.rowcount = 1
            return

        if n.startswith("update loans"):
            (
                current_balance,
                collateral_value,
                next_due,
                loan_id,
                store_id,
            ) = params
            for loan in self.db.loans:
                if loan["loan_id"] == loan_id and loan["store_id"] == store_id:
                    loan["current_balance"] = current_balance
                    loan["collateral_value"] = collateral_value
                    loan["next_due_date"] = next_due
                    self.rowcount = 1
                    return
            return

        if n.startswith("select payment_id from payments"):
            store_id, loan_id, amount_due, amount_paid = params
            row = next(
                (
                    p
                    for p in self.db.payments
                    if p["store_id"] == store_id
                    and p["loan_id"] == loan_id
                    and float(p["amount_due"]) == float(amount_due)
                    and float(p["amount_paid"]) == float(amount_paid)
                ),
                None,
            )
            self._result = {"payment_id": row["payment_id"]} if row else None
            return

        if n.startswith("insert into payments"):
            payment_id = self.db.next_id("payment")
            self.db.payments.append(
                {
                    "payment_id": payment_id,
                    "store_id": params[0],
                    "loan_id": params[1],
                    "amount_due": params[2],
                    "amount_paid": params[3],
                    "due_date": params[4],
                }
            )
            self.lastrowid = payment_id
            self.rowcount = 1
            return

        if n.startswith("update payments"):
            (
                due_date,
                payment_id,
                store_id,
                loan_id,
                amount_due,
                amount_paid,
            ) = params
            for p in self.db.payments:
                if (
                    p["payment_id"] == payment_id
                    and p["store_id"] == store_id
                    and p["loan_id"] == loan_id
                    and float(p["amount_due"]) == float(amount_due)
                    and float(p["amount_paid"]) == float(amount_paid)
                ):
                    p["due_date"] = due_date
                    self.rowcount = 1
                    return
            return

        if n.startswith("select item_id, store_id from collateral_items"):
            serial = params[0]
            row = next(
                (i for i in self.db.collateral if i["serial_number"] == serial),
                None,
            )
            self._result = (
                {"item_id": row["item_id"], "store_id": row["store_id"]}
                if row
                else None
            )
            return

        if n.startswith("insert into collateral_items"):
            item_id = self.db.next_id("item")
            self.db.collateral.append(
                {
                    "item_id": item_id,
                    "store_id": params[0],
                    "loan_id": params[1],
                    "item_type": params[2],
                    "item_description": params[3],
                    "appraised_value": params[4],
                    "serial_number": params[5],
                    "item_status": params[6],
                    "forfeiture_date": params[7],
                }
            )
            self.lastrowid = item_id
            self.rowcount = 1
            return

        if n.startswith("update collateral_items"):
            (
                loan_id,
                item_type,
                item_description,
                appraised_value,
                item_status,
                forfeiture,
                store_id_set,
                item_id,
                store_id_where,
            ) = params
            for item in self.db.collateral:
                if (
                    item["item_id"] == item_id
                    and item["store_id"] == store_id_where
                ):
                    item["loan_id"] = loan_id
                    item["item_type"] = item_type
                    item["item_description"] = item_description
                    item["appraised_value"] = appraised_value
                    item["item_status"] = item_status
                    item["forfeiture_date"] = forfeiture
                    item["store_id"] = store_id_set
                    self.rowcount = 1
                    return
            return

        if "select count(*) as n" in n:
            self._result = {"n": self.db.eval_count(n, params)}
            return

        raise AssertionError(f"Unhandled SQL in FakeCursor: {sql!r} params={params!r}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._results or ([] if self._result is None else [self._result])

    def close(self):
        return None


class FakeDB:
    def __init__(self, *, today: date):
        self.today = today
        self.stores = [{"store_id": 2, "store_name": "Store 2"}]
        self.customers: list[dict] = []
        self.accounts: list[dict] = []
        self.loans: list[dict] = []
        self.payments: list[dict] = []
        self.collateral: list[dict] = []
        self._seqs = {
            "customer": 1000,
            "account": 2000,
            "loan": 3000,
            "payment": 4000,
            "item": 5000,
        }

    def next_id(self, kind: str) -> int:
        self._seqs[kind] += 1
        return self._seqs[kind]

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def _customer_by_id(self, customer_id: int):
        return next(
            (c for c in self.customers if c["customer_id"] == customer_id), None
        )

    def _loan_by_id(self, loan_id: int):
        return next((loan for loan in self.loans if loan["loan_id"] == loan_id), None)

    def _demo_loan_pairs(self) -> set[tuple[str, str]]:
        return {
            (c["email"], c["loan"]["loan_type"]) for c in seed.DEMO_PORTFOLIO
        }

    def _demo_payment_keys(self) -> set[tuple[str, str, float, float]]:
        keys = set()
        for c in seed.DEMO_PORTFOLIO:
            due, paid = seed.payment_natural_key(c["loan"]["payment"])
            keys.add((c["email"], c["loan"]["loan_type"], due, paid))
        return keys

    def eval_count(self, nsql: str, params: tuple) -> int:
        today = self.today
        window_end = today + timedelta(days=30)

        # Customers by demo emails
        if (
            "from customers" in nsql
            and "email in" in nsql
            and "join" not in nsql
            and "store_id <>" not in nsql
        ):
            store_id = params[0]
            emails = set(params[1:])
            return sum(
                1
                for c in self.customers
                if c["store_id"] == store_id and c["email"] in emails
            )

        # Demo Checking accounts
        if "from accounts a" in nsql and "account_type" in nsql and "<>" not in nsql:
            store_id = params[0]
            emails = set(params[1:-1])
            account_type = params[-1]
            count = 0
            for a in self.accounts:
                c = self._customer_by_id(a["customer_id"])
                if (
                    a["store_id"] == store_id
                    and c
                    and c["store_id"] == a["store_id"]
                    and c["email"] in emails
                    and a["account_type"] == account_type
                ):
                    count += 1
            return count

        # Demo loans (email + loan_type pairs) optionally with high-risk
        if "from loans l" in nsql and "from payments" not in nsql:
            store_id = params[0]
            # params after store_id are email, loan_type repeating, maybe trailing store for ownership
            pairs = []
            i = 1
            while i + 1 < len(params) and isinstance(params[i], str):
                # stop when we hit a trailing int store_id for ownership checks
                if i + 1 == len(params) - 1 and isinstance(params[-1], int):
                    break
                if isinstance(params[i], str) and isinstance(params[i + 1], str):
                    pairs.append((params[i], params[i + 1]))
                    i += 2
                else:
                    break
            pair_set = set(pairs) if pairs else self._demo_loan_pairs()
            high_risk_only = ">= 75" in nsql
            ownership_bad = "store_id <>" in nsql or "<>" in nsql
            count = 0
            for loan in self.loans:
                c = self._customer_by_id(loan["customer_id"])
                if not c or loan["store_id"] != store_id:
                    continue
                if (c["email"], loan["loan_type"]) not in pair_set:
                    continue
                if high_risk_only:
                    ltv = _ltv_percent(
                        float(loan["current_balance"]),
                        float(loan["collateral_value"]),
                    )
                    if ltv < 75:
                        continue
                if ownership_bad:
                    if c["store_id"] != store_id or loan["store_id"] != c["store_id"]:
                        count += 1
                    continue
                count += 1
            return count

        # Payments (demo signature and/or overdue)
        if "from payments p" in nsql:
            store_id = params[0]
            # Reconstruct payment keys from params: email, loan_type, due, paid repeating
            keys = []
            i = 1
            while i + 3 < len(params):
                if isinstance(params[i], str) and isinstance(params[i + 1], str):
                    keys.append(
                        (
                            params[i],
                            params[i + 1],
                            float(params[i + 2]),
                            float(params[i + 3]),
                        )
                    )
                    i += 4
                else:
                    break
            key_set = set(keys) if keys else self._demo_payment_keys()
            overdue_only = "due_date < curdate()" in nsql
            ownership_bad = "store_id <>" in nsql or (
                "l.store_id <>" in nsql or "<>" in nsql and "amount_due" in nsql
            )
            # ownership query also has <> 
            count = 0
            for p in self.payments:
                loan = self._loan_by_id(p["loan_id"])
                if not loan or p["store_id"] != store_id:
                    continue
                c = self._customer_by_id(loan["customer_id"])
                if not c:
                    continue
                key = (
                    c["email"],
                    loan["loan_type"],
                    float(p["amount_due"]),
                    float(p["amount_paid"]),
                )
                if key not in key_set:
                    continue
                if overdue_only:
                    if not (
                        p["due_date"] < today
                        and float(p["amount_paid"]) < float(p["amount_due"])
                    ):
                        continue
                if "l.store_id <>" in nsql or (
                    "cross" in nsql
                ):
                    pass
                if "<>" in nsql and "amount_due" in nsql:
                    if loan["store_id"] != store_id or p["store_id"] != loan["store_id"]:
                        count += 1
                    continue
                count += 1
            return count

        # Collateral by serials, optionally at-risk / ownership
        if "from collateral_items" in nsql:
            store_id = params[0]
            serials = [p for p in params[1:] if isinstance(p, str)]
            serial_set = set(serials)
            at_risk = "forfeiture_date" in nsql and "date_add" in nsql
            ownership_bad = "<>" in nsql
            count = 0
            for item in self.collateral:
                if item["store_id"] != store_id or item["serial_number"] not in serial_set:
                    continue
                loan = self._loan_by_id(item["loan_id"])
                if ownership_bad:
                    if (
                        not loan
                        or loan["store_id"] != store_id
                        or item["store_id"] != loan["store_id"]
                    ):
                        count += 1
                    continue
                if at_risk:
                    if not loan:
                        continue
                    ltv = _ltv_percent(
                        float(loan["current_balance"]),
                        float(loan["collateral_value"]),
                    )
                    if not (
                        item["forfeiture_date"] <= window_end or ltv >= 75
                    ):
                        continue
                count += 1
            return count

        # Account ownership bad rows
        if "from accounts a" in nsql and "<>" in nsql:
            return 0

        raise AssertionError(f"Unhandled COUNT SQL: {nsql!r} params={params!r}")


class DatasetShapeTests(unittest.TestCase):
    def test_three_demo_customers_and_emails(self):
        self.assertEqual(len(seed.DEMO_PORTFOLIO), 3)
        names = [row["full_name"] for row in seed.DEMO_PORTFOLIO]
        self.assertEqual(names, ["Elena Vargas", "Marcus Chen", "Sofia Alvarez"])
        self.assertEqual(
            list(seed.DEMO_EMAILS),
            [
                "elena.vargas@store2.telleriq.demo",
                "marcus.chen@store2.telleriq.demo",
                "sofia.alvarez@store2.telleriq.demo",
            ],
        )

    def test_serials_are_s2_prefixed_and_unique(self):
        serials = [
            row["loan"]["collateral"]["serial_number"] for row in seed.DEMO_PORTFOLIO
        ]
        self.assertEqual(serials, list(seed.DEMO_SERIALS))
        self.assertTrue(all(s.startswith("S2-") for s in serials))
        self.assertEqual(len(serials), len(set(serials)))

    def test_loan_types_and_ltv_roles(self):
        elena, marcus, sofia = seed.DEMO_PORTFOLIO
        self.assertEqual(elena["loan"]["loan_type"], "Jewelry Loan")
        self.assertEqual(marcus["loan"]["loan_type"], "Electronics Loan")
        self.assertEqual(sofia["loan"]["loan_type"], "Auto Loan")
        self.assertAlmostEqual(
            _ltv_percent(
                elena["loan"]["current_balance"], elena["loan"]["collateral_value"]
            ),
            85.0,
        )


class PaymentNaturalKeyTests(unittest.TestCase):
    def test_upsert_payment_matches_amount_signature_not_oldest(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.lastrowid = 55
        payment = seed.DEMO_PORTFOLIO[0]["loan"]["payment"]

        seed.upsert_payment(cursor, loan_id=10, payment=payment, today=date(2026, 8, 3))

        select_sql, select_params = cursor.execute.call_args_list[0][0]
        self.assertIn("amount_due = %s", select_sql)
        self.assertIn("amount_paid = %s", select_sql)
        self.assertNotIn("ORDER BY", select_sql)
        self.assertEqual(
            select_params,
            (2, 10, float(payment["amount_due"]), float(payment["amount_paid"])),
        )

    def test_upsert_payment_never_updates_unrelated_payment(self):
        today = date(2026, 8, 3)
        db = FakeDB(today=today)
        cursor = db.cursor()
        # Seed portfolio once
        seed.seed_portfolio(cursor, today=today)
        elena = next(
            c for c in db.customers if c["email"] == seed.DEMO_EMAILS[0]
        )
        elena_loan = next(
            loan
            for loan in db.loans
            if loan["customer_id"] == elena["customer_id"]
            and loan["loan_type"] == "Jewelry Loan"
        )
        unrelated_id = db.next_id("payment")
        db.payments.insert(
            0,
            {
                "payment_id": unrelated_id,
                "store_id": 2,
                "loan_id": elena_loan["loan_id"],
                "amount_due": 999.0,
                "amount_paid": 1.0,
                "due_date": date(2020, 1, 1),
            },
        )
        before = next(p for p in db.payments if p["payment_id"] == unrelated_id).copy()

        seed.upsert_payment(
            cursor,
            loan_id=elena_loan["loan_id"],
            payment=seed.DEMO_PORTFOLIO[0]["loan"]["payment"],
            today=today + timedelta(days=1),
        )

        after = next(p for p in db.payments if p["payment_id"] == unrelated_id)
        self.assertEqual(after, before)
        demo_payments = [
            p
            for p in db.payments
            if p["loan_id"] == elena_loan["loan_id"]
            and float(p["amount_due"]) == 480.0
        ]
        self.assertEqual(len(demo_payments), 1)


class RequireStore2Tests(unittest.TestCase):
    def test_missing_store_2_raises(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        with self.assertRaisesRegex(RuntimeError, "Store 2 is missing"):
            seed.require_store_2(cursor)


class UpsertCollateralTests(unittest.TestCase):
    def test_refuses_serial_owned_by_other_store(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"item_id": 9, "store_id": 1}
        collateral = seed.DEMO_PORTFOLIO[0]["loan"]["collateral"]
        with self.assertRaisesRegex(RuntimeError, "already belongs"):
            seed.upsert_collateral(
                cursor, loan_id=10, collateral=collateral, today=date(2026, 8, 3)
            )


class RunSeedTransactionTests(unittest.TestCase):
    def test_rolls_back_when_verification_fails(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        with patch.object(seed, "get_connection", return_value=conn):
            with patch.object(seed, "seed_portfolio", return_value={}):
                with patch.object(
                    seed, "verify_seed", side_effect=RuntimeError("bad metrics")
                ):
                    with self.assertRaisesRegex(RuntimeError, "bad metrics"):
                        seed.run_seed()
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()


class DemoScopedVerificationTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 3)
        self.db = FakeDB(today=self.today)
        self.cursor = self.db.cursor()
        seed.seed_portfolio(self.cursor, today=self.today)

    def test_verify_passes_with_unrelated_store2_customer(self):
        self.db.customers.append(
            {
                "customer_id": self.db.next_id("customer"),
                "store_id": 2,
                "full_name": "Unrelated Person",
                "phone": "000",
                "email": "unrelated@store2.example",
            }
        )
        metrics = seed.verify_seed(self.cursor)
        self.assertEqual(metrics["total_customers"], 3)
        self.assertEqual(metrics["customers"], 3)

    def test_verify_passes_with_unrelated_store2_overdue_payment(self):
        # Unrelated customer + overdue payment must not inflate demo overdue metric.
        cust_id = self.db.next_id("customer")
        loan_id = self.db.next_id("loan")
        self.db.customers.append(
            {
                "customer_id": cust_id,
                "store_id": 2,
                "full_name": "Other Overdue",
                "phone": "000",
                "email": "other.overdue@store2.example",
            }
        )
        self.db.loans.append(
            {
                "loan_id": loan_id,
                "store_id": 2,
                "customer_id": cust_id,
                "loan_type": "Personal Loan",
                "current_balance": 1000.0,
                "collateral_value": 2000.0,
                "next_due_date": self.today - timedelta(days=1),
            }
        )
        self.db.payments.append(
            {
                "payment_id": self.db.next_id("payment"),
                "store_id": 2,
                "loan_id": loan_id,
                "amount_due": 200.0,
                "amount_paid": 0.0,
                "due_date": self.today - timedelta(days=10),
            }
        )
        metrics = seed.verify_seed(self.cursor)
        self.assertEqual(metrics["overdue_payments"], 1)

    def test_verify_passes_with_unrelated_store2_high_risk_loan(self):
        cust_id = self.db.next_id("customer")
        self.db.customers.append(
            {
                "customer_id": cust_id,
                "store_id": 2,
                "full_name": "Risky Other",
                "phone": "000",
                "email": "risky.other@store2.example",
            }
        )
        self.db.loans.append(
            {
                "loan_id": self.db.next_id("loan"),
                "store_id": 2,
                "customer_id": cust_id,
                "loan_type": "Personal Loan",
                "current_balance": 9000.0,
                "collateral_value": 10000.0,  # 90% LTV
                "next_due_date": self.today + timedelta(days=10),
            }
        )
        metrics = seed.verify_seed(self.cursor)
        self.assertEqual(metrics["high_risk_loans"], 1)

    def test_verify_passes_with_unrelated_store2_collateral_at_risk(self):
        cust_id = self.db.next_id("customer")
        loan_id = self.db.next_id("loan")
        self.db.customers.append(
            {
                "customer_id": cust_id,
                "store_id": 2,
                "full_name": "Collateral Other",
                "phone": "000",
                "email": "collateral.other@store2.example",
            }
        )
        self.db.loans.append(
            {
                "loan_id": loan_id,
                "store_id": 2,
                "customer_id": cust_id,
                "loan_type": "Personal Loan",
                "current_balance": 1000.0,
                "collateral_value": 5000.0,
                "next_due_date": self.today + timedelta(days=10),
            }
        )
        self.db.collateral.append(
            {
                "item_id": self.db.next_id("item"),
                "store_id": 2,
                "loan_id": loan_id,
                "item_type": "Jewelry",
                "item_description": "Unrelated ring",
                "appraised_value": 500.0,
                "serial_number": "S2-OTHER-9999",
                "item_status": "Held",
                "forfeiture_date": self.today + timedelta(days=5),
            }
        )
        metrics = seed.verify_seed(self.cursor)
        self.assertEqual(metrics["collateral_at_risk"], 1)

    def test_extra_children_on_demo_customer_are_not_counted(self):
        elena = next(c for c in self.db.customers if c["email"] == seed.DEMO_EMAILS[0])
        self.db.accounts.append(
            {
                "account_id": self.db.next_id("account"),
                "store_id": 2,
                "customer_id": elena["customer_id"],
                "account_type": "Savings",
                "balance": 50.0,
                "status": "Active",
            }
        )
        self.db.loans.append(
            {
                "loan_id": self.db.next_id("loan"),
                "store_id": 2,
                "customer_id": elena["customer_id"],
                "loan_type": "Personal Loan",
                "current_balance": 500.0,
                "collateral_value": 1000.0,
                "next_due_date": self.today + timedelta(days=20),
            }
        )
        jewelry = next(
            loan
            for loan in self.db.loans
            if loan["customer_id"] == elena["customer_id"]
            and loan["loan_type"] == "Jewelry Loan"
        )
        self.db.payments.append(
            {
                "payment_id": self.db.next_id("payment"),
                "store_id": 2,
                "loan_id": jewelry["loan_id"],
                "amount_due": 111.0,
                "amount_paid": 0.0,
                "due_date": self.today - timedelta(days=3),
            }
        )
        metrics = seed.verify_seed(self.cursor)
        self.assertEqual(metrics["accounts"], 3)
        self.assertEqual(metrics["loans"], 3)
        self.assertEqual(metrics["payments"], 3)
        # Extra overdue on Elena's loan must not count toward demo overdue.
        self.assertEqual(metrics["overdue_payments"], 1)

    def test_repeated_seed_is_idempotent(self):
        first_customers = {c["email"]: c["customer_id"] for c in self.db.customers
                           if c["email"] in seed.DEMO_EMAILS}
        first_payment_ids = sorted(
            p["payment_id"]
            for p in self.db.payments
            if (float(p["amount_due"]), float(p["amount_paid"]))
            in {seed.payment_natural_key(c["loan"]["payment"]) for c in seed.DEMO_PORTFOLIO}
        )
        first_serials = sorted(i["serial_number"] for i in self.db.collateral
                               if i["serial_number"] in seed.DEMO_SERIALS)

        seed.seed_portfolio(self.cursor, today=self.today + timedelta(days=2))
        metrics = seed.verify_seed(self.cursor)

        second_customers = {c["email"]: c["customer_id"] for c in self.db.customers
                            if c["email"] in seed.DEMO_EMAILS}
        second_payment_ids = sorted(
            p["payment_id"]
            for p in self.db.payments
            if (float(p["amount_due"]), float(p["amount_paid"]))
            in {seed.payment_natural_key(c["loan"]["payment"]) for c in seed.DEMO_PORTFOLIO}
        )
        second_serials = sorted(i["serial_number"] for i in self.db.collateral
                                if i["serial_number"] in seed.DEMO_SERIALS)

        self.assertEqual(first_customers, second_customers)
        self.assertEqual(first_payment_ids, second_payment_ids)
        self.assertEqual(first_serials, second_serials)
        self.assertEqual(metrics["customers"], 3)
        self.assertEqual(metrics["payments"], 3)
        self.assertEqual(
            len([c for c in self.db.customers if c["email"] in seed.DEMO_EMAILS]),
            3,
        )

    def test_demo_match_clauses_cover_exact_keys(self):
        loan_sql, loan_params = seed._demo_loan_match_clause()
        self.assertIn("Jewelry Loan", loan_params)
        self.assertIn("Electronics Loan", loan_params)
        self.assertIn("Auto Loan", loan_params)
        pay_sql, pay_params = seed._demo_payment_match_clause()
        self.assertIn(480.0, pay_params)
        self.assertIn(350.0, pay_params)
        self.assertIn(400.0, pay_params)
        self.assertTrue(loan_sql.startswith("("))
        self.assertTrue(pay_sql.startswith("("))


class Store1SafetyTests(unittest.TestCase):
    def test_seed_does_not_touch_store1_rows(self):
        today = date(2026, 8, 3)
        db = FakeDB(today=today)
        # Preload Store 1 customer that must remain untouched.
        db.customers.append(
            {
                "customer_id": 1,
                "store_id": 1,
                "full_name": "Asha Patel",
                "phone": "111",
                "email": "asha@store1.example",
            }
        )
        before = [c.copy() for c in db.customers if c["store_id"] == 1]
        seed.seed_portfolio(db.cursor(), today=today)
        after = [c for c in db.customers if c["store_id"] == 1]
        self.assertEqual(after, before)
        self.assertTrue(all(c["store_id"] == 2 for c in db.customers if c["email"] in seed.DEMO_EMAILS))


if __name__ == "__main__":
    unittest.main()
