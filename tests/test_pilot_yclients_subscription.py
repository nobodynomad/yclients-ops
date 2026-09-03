from datetime import date
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pilot_yclients_subscription import (
    build_document_payload,
    build_goods_transaction_payload,
    execute_planned_card,
    infer_period_days,
    issuance_write_request_count,
    pending_type_titles,
    select_issued_card,
    validate_preflight,
)


class AuditCountingTests(unittest.TestCase):
    def test_new_abonement_uses_four_write_requests(self):
        self.assertEqual(issuance_write_request_count(), 4)


class PeriodInferenceTests(unittest.TestCase):
    def test_infer_period_days_uses_default_card_readback(self):
        card = {
            "created_date": "2026-07-21T10:00:00+00:00",
            "activated_date": "2026-07-21T10:00:00+00:00",
            "expiration_date": "2027-07-21T10:00:00+00:00",
            "period": 365,
            "period_unit_id": 1,
        }

        result = infer_period_days(card, date(2028, 7, 15))

        self.assertIn(result["base"], {"created_date", "activated_date"})
        self.assertEqual(result["period_days"], (date(2028, 7, 15) - date(2026, 7, 21)).days)
        self.assertEqual(result["expected_expiration"], "2028-07-15")


class IssuedCardSelectionTests(unittest.TestCase):
    def test_selects_only_new_matching_card_id(self):
        before = [
            {"id": 10, "type": {"title": "Другой тип"}},
            {"id": 20, "type": {"title": "Групповая консультация"}},
        ]
        after = before + [
            {"id": 30, "type": {"title": "Групповая консультация"}, "united_balance_services_count": 14}
        ]

        selected = select_issued_card(before, after, "Групповая консультация")

        self.assertEqual(selected["id"], 30)

    def test_rejects_ambiguous_new_matching_cards(self):
        after = [
            {"id": 30, "type": {"title": "Групповая консультация"}},
            {"id": 31, "type": {"title": "Групповая консультация"}},
        ]

        with self.assertRaises(ValueError):
            select_issued_card([], after, "Групповая консультация")


class PreflightAndIdempotencyTests(unittest.TestCase):
    def test_preflight_requires_exactly_the_approved_client(self):
        validate_preflight(
            approved_client_id=424,
            exact_contact_match_ids=[424],
            active_cards=[],
            planned_type_titles=["Индивидуальная консультация", "Групповая консультация"],
        )

        with self.assertRaises(ValueError):
            validate_preflight(
                approved_client_id=424,
                exact_contact_match_ids=[425],
                active_cards=[],
                planned_type_titles=["Индивидуальная консультация"],
            )

    def test_pending_types_skip_completed_ledger_operation(self):
        planned = ["Индивидуальная консультация", "Групповая консультация"]
        ledger = {
            "operations": {
                "Индивидуальная консультация": {"stage": "completed", "card_id": 100},
                "Групповая консультация": {"stage": "pending"},
            }
        }

        self.assertEqual(pending_type_titles(planned, ledger), ["Групповая консультация"])
    def test_pending_types_do_not_retry_partially_started_operation(self):
        planned = ["Индивидуальная консультация"]
        ledger = {
            "operations": {
                "Индивидуальная консультация": {"stage": "issued", "card_id": 100},
            }
        }

        self.assertEqual(pending_type_titles(planned, ledger), [])


class MembershipSalePayloadTests(unittest.TestCase):
    def test_builds_official_sale_document_and_single_good_transaction(self):
        document = build_document_payload(
            storage_id=2255377,
            create_date="2026-07-21 16:00:00",
            comment="FF pilot 1ac27f880b",
        )
        transaction = build_goods_transaction_payload(
            document_id=777,
            good_id=36892736,
            client_id=424798380,
            cost=1,
            comment="FF pilot 1ac27f880b",
        )

        self.assertEqual(document, {
            "type_id": 1,
            "storage_id": 2255377,
            "create_date": "2026-07-21 16:00:00",
            "comment": "FF pilot 1ac27f880b",
        })
        self.assertEqual(transaction, {
            "document_id": 777,
            "good_id": 36892736,
            "amount": 1,
            "cost_per_unit": 1,
            "discount": 0,
            "cost": 1,
            "operation_unit_type": 1,
            "client_id": 424798380,
            "comment": "FF pilot 1ac27f880b",
        })


class OperationExecutionTests(unittest.TestCase):
    def test_executes_issue_balance_period_and_readback_in_order(self):
        default = {
            "id": 30,
            "type": {"title": "Групповая консультация"},
            "created_date": "2026-07-21T10:00:00+00:00",
            "activated_date": "2026-07-21T10:00:00+00:00",
            "expiration_date": "2027-07-21T10:00:00+00:00",
            "period": 365,
            "period_unit_id": 1,
            "united_balance_services_count": 14,
        }
        balanced = {**default, "united_balance_services_count": 13}
        final = {**balanced, "expiration_date": "2028-07-15T10:00:00+00:00"}

        class FakeAPI:
            def __init__(self):
                self.calls = []
                self.reads = iter([[default], [balanced], [final]])

            def issue_card(self, phone, type_id):
                self.calls.append(("issue", phone, type_id))

            def active_subscriptions(self, phone):
                self.calls.append(("read", phone))
                return next(self.reads)

            def set_balance(self, card_id, quantity):
                self.calls.append(("balance", card_id, quantity))

            def set_period(self, card_id, period_days):
                self.calls.append(("period", card_id, period_days))

        api = FakeAPI()
        states = []

        result = execute_planned_card(
            api=api,
            before_cards=[],
            phone="79000000000",
            type_id=123,
            type_title="Групповая консультация",
            quantity=13,
            target_expiration=date(2028, 7, 15),
            persist=lambda state: states.append(dict(state)),
        )

        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["card_id"], 30)
        self.assertEqual(result["verified_balance"], 13)
        self.assertEqual(result["verified_expiration"], "2028-07-15")
        self.assertEqual([call[0] for call in api.calls], ["issue", "read", "balance", "read", "period", "read"])
        self.assertEqual(states[-1]["stage"], "completed")


if __name__ == "__main__":
    unittest.main()
