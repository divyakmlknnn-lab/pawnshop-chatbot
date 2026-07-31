import unittest

import schema_metadata
from schema_metadata import (
    UnknownTableError,
    describe_approved_table,
    get_approved_schema,
    list_approved_tables,
    list_projection_profiles,
)


class SchemaMetadataTests(unittest.TestCase):
    def test_list_approved_tables(self):
        tables = list_approved_tables()
        self.assertEqual(
            tables,
            [
                "accounts",
                "collateral_items",
                "customers",
                "loans",
                "payments",
            ],
        )

    def test_list_approved_tables_is_copy(self):
        first = list_approved_tables()
        second = list_approved_tables()
        self.assertIsNot(first, second)
        first.append("shadow_table")
        self.assertNotIn("shadow_table", list_approved_tables())

    def test_describe_approved_table_customers(self):
        description = describe_approved_table("customers")
        self.assertEqual(description["table"], "customers")
        self.assertEqual(
            description["fields"],
            ["customer_id", "full_name", "phone", "email"],
        )
        self.assertEqual(description["restricted_contact_fields"], ["phone", "email"])
        self.assertEqual(description["computed_fields"], [])
        self.assertEqual(
            description["relationships"],
            [
                {
                    "from_table": "accounts",
                    "from_column": "customer_id",
                    "to_table": "customers",
                    "to_column": "customer_id",
                },
                {
                    "from_table": "loans",
                    "from_column": "customer_id",
                    "to_table": "customers",
                    "to_column": "customer_id",
                },
            ],
        )

    def test_describe_approved_table_payments_relationships_and_computed(self):
        description = describe_approved_table("payments")
        self.assertEqual(
            description["fields"],
            [
                "payment_id",
                "loan_id",
                "amount_due",
                "amount_paid",
                "due_date",
            ],
        )
        self.assertEqual(
            description["relationships"],
            [
                {
                    "from_table": "payments",
                    "from_column": "loan_id",
                    "to_table": "loans",
                    "to_column": "loan_id",
                }
            ],
        )
        self.assertEqual(
            description["computed_fields"],
            [
                {
                    "name": "remaining_due",
                    "table": "payments",
                    "expression": "amount_due - amount_paid",
                    "description": "Unpaid portion of a scheduled payment.",
                }
            ],
        )

    def test_describe_approved_table_loans_computed_field(self):
        description = describe_approved_table("loans")
        self.assertEqual(
            description["computed_fields"],
            [
                {
                    "name": "ltv_percent",
                    "table": "loans",
                    "expression": "current_balance / NULLIF(collateral_value, 0) * 100",
                    "description": "Loan-to-value percentage for a loan.",
                }
            ],
        )

    def test_get_approved_schema_relationships(self):
        schema = get_approved_schema()
        self.assertEqual(
            schema["relationships"],
            [
                {
                    "from_table": "accounts",
                    "from_column": "customer_id",
                    "to_table": "customers",
                    "to_column": "customer_id",
                },
                {
                    "from_table": "loans",
                    "from_column": "customer_id",
                    "to_table": "customers",
                    "to_column": "customer_id",
                },
                {
                    "from_table": "payments",
                    "from_column": "loan_id",
                    "to_table": "loans",
                    "to_column": "loan_id",
                },
                {
                    "from_table": "collateral_items",
                    "from_column": "loan_id",
                    "to_table": "loans",
                    "to_column": "loan_id",
                },
            ],
        )

    def test_get_approved_schema_restricted_contact_fields(self):
        schema = get_approved_schema()
        self.assertEqual(schema["restricted_contact_fields"], ["email", "phone"])

    def test_projection_profiles_exist_with_required_fields(self):
        expected = {
            "customer_list": ["customer_id", "full_name"],
            "customer_detail": [
                "customer_id",
                "full_name",
                "loan_type",
                "current_balance",
                "collateral_value",
                "ltv_percent",
                "next_due_date",
                "amount_due",
                "amount_paid",
                "remaining_due",
                "due_date",
                "item_type",
                "item_description",
                "appraised_value",
                "item_status",
            ],
            "overdue_payments": [
                "customer_id",
                "full_name",
                "loan_type",
                "amount_due",
                "amount_paid",
                "remaining_due",
                "due_date",
                "ltv_percent",
            ],
            "due_soon": [
                "customer_id",
                "full_name",
                "loan_type",
                "amount_due",
                "amount_paid",
                "remaining_due",
                "due_date",
            ],
            "high_risk_loans": [
                "customer_id",
                "full_name",
                "loan_type",
                "current_balance",
                "collateral_value",
                "ltv_percent",
                "next_due_date",
            ],
            "collateral_detail": [
                "customer_id",
                "full_name",
                "item_type",
                "item_description",
                "appraised_value",
                "item_status",
            ],
            "aggregate_ranking": ["customer_id", "full_name"],
            "aggregate_summary": [],
        }

        profiles = {profile["name"]: profile for profile in list_projection_profiles()}
        self.assertEqual(set(profiles), set(expected))

        for name, fields in expected.items():
            profile = profiles[name]
            self.assertEqual(profile["recommended_fields"], fields)
            self.assertTrue(profile["exclude_contact_fields_unless_requested"])
            self.assertTrue(profile["category"])
            self.assertTrue(profile["related_tables"])
            self.assertIn("phone", profile["notes"].lower())
            self.assertIn("email", profile["notes"].lower())

        self.assertIn("total_overdue", profiles["aggregate_ranking"]["computed_aliases"])
        self.assertIn("remaining_due", profiles["overdue_payments"]["computed_aliases"])
        self.assertIn("ltv_percent", profiles["high_risk_loans"]["computed_aliases"])

    def test_get_approved_schema_includes_projection_profiles(self):
        schema = get_approved_schema()
        self.assertIn("projection_profiles", schema)
        names = [profile["name"] for profile in schema["projection_profiles"]]
        self.assertEqual(
            names,
            [
                "customer_list",
                "customer_detail",
                "overdue_payments",
                "due_soon",
                "high_risk_loans",
                "collateral_detail",
                "aggregate_ranking",
                "aggregate_summary",
            ],
        )

    def test_unknown_table_rejection(self):
        with self.assertRaises(UnknownTableError):
            describe_approved_table("not_a_table")

    def test_unknown_table_error_is_distinct_subclass_of_key_error(self):
        self.assertTrue(issubclass(UnknownTableError, KeyError))
        with self.assertRaises(UnknownTableError) as ctx:
            describe_approved_table("missing_table")
        self.assertIs(type(ctx.exception), UnknownTableError)

    def test_internal_relationships_are_deeply_immutable(self):
        relationship = schema_metadata._APPROVED_RELATIONSHIPS[0]
        with self.assertRaises(TypeError):
            relationship["from_table"] = "hacked"

        frozen_relationship = schema_metadata._FROZEN_APPROVED_SCHEMA["relationships"][0]
        with self.assertRaises(TypeError):
            frozen_relationship["from_column"] = "hacked"

    def test_internal_computed_fields_are_deeply_immutable(self):
        computed_field = schema_metadata._APPROVED_COMPUTED_FIELDS[0]
        with self.assertRaises(TypeError):
            computed_field["name"] = "hacked"

        frozen_field = schema_metadata._FROZEN_APPROVED_SCHEMA["computed_fields"][1]
        with self.assertRaises(TypeError):
            frozen_field["expression"] = "hacked"

    def test_mutation_protection_describe(self):
        description = describe_approved_table("accounts")
        description["fields"].append("hacked")
        description["relationships"].append({"from_table": "bad"})
        fresh = describe_approved_table("accounts")
        self.assertNotIn("hacked", fresh["fields"])
        self.assertEqual(len(fresh["relationships"]), 1)

    def test_mutation_protection_get_approved_schema(self):
        schema = get_approved_schema()
        schema["tables"]["customers"]["fields"].append("hacked")
        schema["relationships"].append({"from_table": "bad"})
        schema["computed_fields"][0]["name"] = "changed"
        schema["projection_profiles"][0]["recommended_fields"].append("hacked")

        fresh = get_approved_schema()
        self.assertNotIn("hacked", fresh["tables"]["customers"]["fields"])
        self.assertEqual(len(fresh["relationships"]), 4)
        self.assertEqual(fresh["computed_fields"][0]["name"], "remaining_due")
        self.assertNotIn("hacked", fresh["projection_profiles"][0]["recommended_fields"])

        again = get_approved_schema()
        self.assertEqual(again, fresh)
        self.assertIsNot(again, fresh)


if __name__ == "__main__":
    unittest.main()
