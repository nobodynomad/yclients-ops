from datetime import date
import unittest

from build_subscription_dry_run import (
    apply_telegram_overrides,
    completed_operation_keys,
    existing_client_policy,
    parse_period,
    parse_telegram_overrides,
    partition_completed_operations,
    summarize_planned_actions,
)


class TelegramOverrideTests(unittest.TestCase):
    def test_applies_user_confirmed_telegram_by_exact_email(self):
        overrides = parse_telegram_overrides([
            'alice@example.com=@alice_example',
            'bob@example.com=@bob_example',
        ])
        sales = [
            {'user': {'email': 'ALICE@example.com', 'tgUsername': ''}},
            {'user': {'email': 'bob@example.com'}},
        ]
        self.assertEqual(apply_telegram_overrides(sales, overrides), 2)
        self.assertEqual(sales[0]['user']['tgUsername'], 'alice_example')
        self.assertEqual(sales[1]['user']['tgUsername'], 'bob_example')

    def test_rejects_conflicting_existing_username_or_missing_email(self):
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            apply_telegram_overrides(
                [{'user': {'email': 'a@example.com', 'tgUsername': 'otheruser'}}],
                {'a@example.com': 'confirmeduser'},
            )
        with self.assertRaisesRegex(ValueError, 'not found'):
            apply_telegram_overrides([], {'a@example.com': 'confirmeduser'})


class ParsePeriodTests(unittest.TestCase):
    def test_explicit_inclusive_period_builds_exclusive_api_end(self):
        start, end_inclusive, end_exclusive = parse_period(
            "2026-07-01", "2026-07-21", today=date(2026, 7, 21)
        )
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end_inclusive, date(2026, 7, 21))
        self.assertEqual(end_exclusive, date(2026, 7, 22))

    def test_rejects_reversed_period(self):
        with self.assertRaisesRegex(ValueError, "start"):
            parse_period("2026-07-22", "2026-07-21", today=date(2026, 7, 21))

    def test_rejects_future_end(self):
        with self.assertRaisesRegex(ValueError, "future"):
            parse_period("2026-07-01", "2026-07-22", today=date(2026, 7, 21))


class ExistingClientPolicyTests(unittest.TestCase):
    def test_existing_client_with_any_active_card_is_skipped(self):
        self.assertEqual(
            existing_client_policy(active_card_count=2),
            "existing_client_has_subscription_skip_by_policy",
        )

    def test_existing_client_without_active_card_requires_manual_history_proof(self):
        self.assertEqual(
            existing_client_policy(active_card_count=0),
            "existing_client_requires_full_history_manual_eligibility_review",
        )


class ActionSummaryTests(unittest.TestCase):
    def test_excludes_operations_from_exception_sales(self):
        entries = [
            {
                "client_state": "existing",
                "operations": [{"type": "Групповая консультация", "action": "top_up_existing", "family": "ordinary"}],
                "exceptions": [],
            },
            {
                "client_state": "existing",
                "operations": [{"type": "Индивидуальная консультация", "action": "top_up_existing", "family": "ordinary"}],
                "exceptions": ["conflict"],
            },
        ]
        actions, typed = summarize_planned_actions(entries)
        self.assertEqual(actions["top_up_existing"], 1)
        self.assertEqual(actions["set_balance"], 1)
        self.assertEqual(typed, {"Групповая консультация|top_up_existing": 1})


class CompletedOperationTests(unittest.TestCase):
    def test_extracts_completed_pilot_and_mass_operations(self):
        ledgers = [
            {
                "sale_ref": "pilot-ref",
                "operations": {
                    "Индивидуальная консультация": {"stage": "completed"},
                    "Групповая консультация": {"stage": "pending"},
                },
            },
            {
                "operations": {
                    "mass-ref::Групповая консультация": {
                        "stage": "completed",
                        "sale_ref": "mass-ref",
                        "type_title": "Групповая консультация",
                    }
                }
            },
        ]
        self.assertEqual(
            completed_operation_keys(ledgers),
            {
                ("pilot-ref", "Индивидуальная консультация"),
                ("mass-ref", "Групповая консультация"),
            },
        )

    def test_completed_rollback_removes_source_topup_from_completed_keys(self):
        ledgers = [
            {"operations": {
                "mass-ref::Групповая консультация": {
                    "stage": "completed",
                    "action": "top_up_existing",
                    "sale_ref": "mass-ref",
                    "type_title": "Групповая консультация",
                }
            }},
            {"operations": {
                "mass-ref::Групповая консультация": {
                    "stage": "completed",
                    "source_action": "top_up_existing",
                    "sale_ref": "mass-ref",
                    "type_title": "Групповая консультация",
                }
            }},
        ]
        self.assertEqual(completed_operation_keys(ledgers), set())

    def test_partitions_already_completed_types(self):
        ops = [
            {"type": "Индивидуальная консультация", "quantity": 6},
            {"type": "Групповая консультация", "quantity": 13},
        ]
        pending, skipped = partition_completed_operations(
            "pilot-ref",
            ops,
            {("pilot-ref", "Индивидуальная консультация")},
        )
        self.assertEqual([x["type"] for x in pending], ["Групповая консультация"])
        self.assertEqual(skipped, ["Индивидуальная консультация"])


if __name__ == "__main__":
    unittest.main()
