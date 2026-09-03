from datetime import date
import unittest

from mass_yclients_subscriptions import (
    GOOD_IDS,
    configure_period,
    clear_resolved_client_failure,
    execute_issue,
    execute_topup,
    expected_operation_total,
    final_status,
    merge_client_state,
    operation_key,
    recovery_decision,
    select_topup_card,
    validate_artifact,
    validate_execution_action,
    validate_new_client_eligibility,
)


def card(identifier, title, balance, expiration="2028-01-01", status="active"):
    return {
        "id": identifier,
        "type": {"title": title},
        "united_balance_services_count": balance,
        "expiration_date": expiration,
        "status": {"slug": status, "title": "Активирован"},
    }


class BatchArtifactTests(unittest.TestCase):
    def test_executor_allows_only_new_issuance(self):
        validate_execution_action("issue_new")
        with self.assertRaisesRegex(ValueError, "forbidden"):
            validate_execution_action("top_up_existing")

    def test_final_status_requires_no_failures_and_all_operations(self):
        self.assertEqual(final_status(failures=[], completed=3, planned=3), "completed")
        self.assertEqual(final_status(failures=[{"x": 1}], completed=2, planned=3), "partial")
        self.assertEqual(final_status(failures=[], completed=2, planned=3), "partial")

    def test_expected_operation_total_includes_existing_period_ledger(self):
        existing = {'old::Групповая консультация': {'stage': 'completed'}}
        ready = [{'sale_ref': 'new', 'operations': [
            {'type': 'Индивидуальная консультация'},
            {'type': 'Групповая консультация'},
        ]}]
        self.assertEqual(expected_operation_total(existing, ready), 3)

    def test_operation_key_is_stable(self):
        self.assertEqual(
            operation_key("abc123", "Групповая консультация"),
            "abc123::Групповая консультация",
        )

    def test_validates_exact_approved_period_and_source_count(self):
        artifact = {
            "summary": {
                "period": {
                    "purchaseDateFrom_inclusive": "2026-07-01",
                    "purchaseDateThrough_inclusive": "2026-07-21",
                    "purchaseDateTo_exclusive_sent": "2026-07-22",
                },
                "source": {"rows_collected": 52, "unique_purchase_ids": 52},
            },
            "entries": [{}] * 52,
        }
        validate_artifact(artifact, start=date(2026, 7, 1), end=date(2026, 7, 21), source_count=52)
        with self.assertRaisesRegex(ValueError, "period"):
            validate_artifact(artifact, start=date(2026, 7, 2), end=date(2026, 7, 21), source_count=52)

    def test_configures_a_period_specific_ledger(self):
        self.assertEqual(GOOD_IDS['Консультации (3 шт.)'], 35724188)
        self.assertEqual(GOOD_IDS['Консультации (5 шт.)'], 35724211)
        self.assertEqual(GOOD_IDS['Консультации (8 шт.)'], 35724237)
        config = configure_period(date(2026, 7, 22), date(2026, 7, 28), today=date(2026, 7, 28))
        self.assertEqual(config['start'], date(2026, 7, 22))
        self.assertEqual(config['end'], date(2026, 7, 28))
        self.assertTrue(str(config['ledger_path']).endswith('2026-07-22_2026-07-28.json'))
        with self.assertRaisesRegex(ValueError, 'future'):
            configure_period(date(2026, 7, 22), date(2026, 7, 29), today=date(2026, 7, 28))

    def test_new_client_eligibility_rejects_untracked_live_client(self):
        validate_new_client_eligibility('new', None, None)
        validate_new_client_eligibility('new', 42, 42)
        with self.assertRaisesRegex(ValueError, 'appeared'):
            validate_new_client_eligibility('new', 42, None)
        with self.assertRaisesRegex(ValueError, 'new-client'):
            validate_new_client_eligibility('existing', 42, None)

    def test_client_state_merge_preserves_creation_provenance_and_cumulative_writes(self):
        previous = {'stage': 'client_created', 'client_id': 42, 'writes': 1, 'original_last_change_date': None}
        current = {'stage': 'client_verified', 'client_id': 42, 'writes': 0, 'original_last_change_date': 'later'}
        merged = merge_client_state(previous, current)
        self.assertEqual(merged['writes'], 1)
        self.assertIsNone(merged['original_last_change_date'])
        self.assertEqual(merged['stage'], 'client_verified')

    def test_resolved_client_failure_is_removed(self):
        ledger = {'failures': {'abc::__client_or_sale__': {'message': 'old'}, 'other': {}}}
        clear_resolved_client_failure(ledger, 'abc')
        self.assertEqual(ledger['failures'], {'other': {}})


class TopupSelectionTests(unittest.TestCase):
    def test_selects_only_nonexpired_matching_card(self):
        cards = [
            card(1, "Групповая консультация", 2, "2025-01-01", "expired"),
            card(2, "Групповая консультация", 5),
            card(3, "Индивидуальная консультация", 7),
        ]
        self.assertEqual(
            select_topup_card(cards, "Групповая консультация", today=date(2026, 7, 21))["id"],
            2,
        )

    def test_multiple_positive_cards_are_rejected(self):
        cards = [card(1, "Групповая консультация", 2), card(2, "Групповая консультация", 5)]
        with self.assertRaisesRegex(ValueError, "multiple"):
            select_topup_card(cards, "Групповая консультация", today=date(2026, 7, 21))

    def test_multiple_zero_cards_choose_lowest_id(self):
        cards = [card(9, "Групповая консультация", 0), card(2, "Групповая консультация", 0)]
        self.assertEqual(
            select_topup_card(cards, "Групповая консультация", today=date(2026, 7, 21))["id"],
            2,
        )


class RecoveryTests(unittest.TestCase):
    def test_target_balance_means_request_already_applied(self):
        self.assertEqual(recovery_decision(current=18, before=5, target=18), "complete")

    def test_original_balance_is_safe_to_retry(self):
        self.assertEqual(recovery_decision(current=5, before=5, target=18), "retry")

    def test_unexpected_balance_requires_manual_recovery(self):
        self.assertEqual(recovery_decision(current=9, before=5, target=18), "conflict")


class FakeTopupAPI:
    def __init__(self, current):
        self.current = current
        self.set_calls = []

    def active_subscriptions(self, phone):
        return [card(42, "Групповая консультация", self.current, "2028-01-01")]

    def set_balance(self, card_id, quantity):
        self.set_calls.append((card_id, quantity))
        self.current = quantity


class ExecuteTopupTests(unittest.TestCase):
    def test_sets_absolute_balance_and_preserves_expiration(self):
        api = FakeTopupAPI(5)
        states = []
        result = execute_topup(
            api=api,
            phone="79991234567",
            type_title="Групповая консультация",
            quantity=13,
            previous_state=None,
            persist=states.append,
            today=date(2026, 7, 21),
        )
        self.assertEqual(api.set_calls, [(42, 18)])
        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["balance_before"], 5)
        self.assertEqual(result["balance_after"], 18)
        self.assertEqual(result["writes"], 1)
        self.assertEqual(states[0]["stage"], "balance_updating")

    def test_recovers_applied_request_without_second_write(self):
        api = FakeTopupAPI(18)
        state = {
            "stage": "balance_updating",
            "card_id": 42,
            "balance_before": 5,
            "target_balance": 18,
            "expiration_before": "2028-01-01",
        }
        result = execute_topup(
            api=api,
            phone="79991234567",
            type_title="Групповая консультация",
            quantity=13,
            previous_state=state,
            persist=lambda value: None,
            today=date(2026, 7, 21),
        )
        self.assertEqual(api.set_calls, [])
        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["writes"], 0)


class FakeIssueAPI:
    def __init__(self, title="Групповая консультация", balance=14, period=365, period_unit_id=1):
        self.cards = []
        self.calls = []
        self.last_issue_meta = {}
        self.title = title
        self.balance = balance
        self.period = period
        self.period_unit_id = period_unit_id

    def active_subscriptions(self, phone):
        return [dict(item) for item in self.cards]

    def issue_card(self, phone, good_id):
        self.calls.append(("issue", good_id))
        self.last_issue_meta = {"document_id": 10, "goods_transaction_id": 20}
        self.cards = [{
            "id": 100,
            "type": {"title": self.title},
            "united_balance_services_count": self.balance,
            "created_date": "2026-07-21T10:00:00+00:00",
            "activated_date": "2026-07-21T10:00:00+00:00",
            "expiration_date": "2027-07-21T23:59:59+04:00",
            "period": self.period,
            "period_unit_id": self.period_unit_id,
            "status": {"title": "Активирован", "slug": "active"},
        }]

    def set_balance(self, card_id, quantity):
        self.calls.append(("balance", card_id, quantity))
        self.cards[0]["united_balance_services_count"] = quantity

    def set_period(self, card_id, period_days):
        self.calls.append(("period", card_id, period_days))
        self.cards[0]["expiration_date"] = "2028-01-20T23:59:59+04:00"


class ExecuteIssueTests(unittest.TestCase):
    def test_issues_sets_nondefault_values_and_verifies_each_stage(self):
        api = FakeIssueAPI()
        states = []
        result = execute_issue(
            api=api,
            phone="79991234567",
            good_id=34799717,
            type_title="Групповая консультация",
            quantity=13,
            target_expiration=date(2028, 1, 20),
            previous_state=None,
            persist=states.append,
        )
        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["card_id"], 100)
        self.assertEqual(result["verified_balance"], 13)
        self.assertEqual(result["verified_expiration"], "2028-01-20")
        self.assertEqual(result["writes"], 4)
        self.assertEqual([x["stage"] for x in states], ["issuing", "issued", "balance_verified", "completed"])
        self.assertEqual(api.calls[0], ("issue", 34799717))

    def test_package_uses_configured_period_without_period_write(self):
        api = FakeIssueAPI(title="Консультации (3 шт.)", balance=3, period=2, period_unit_id=3)
        states = []
        result = execute_issue(
            api=api,
            phone="79991234567",
            good_id=1,
            type_title="Консультации (3 шт.)",
            quantity=3,
            target_expiration=None,
            previous_state=None,
            persist=states.append,
            configured_period=(2, 3),
        )
        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["verified_balance"], 3)
        self.assertEqual(result["verified_expiration"], "2027-07-21")
        self.assertEqual(result["writes"], 2)
        self.assertFalse(any(call[0] == "period" for call in api.calls))


if __name__ == "__main__":
    unittest.main()
