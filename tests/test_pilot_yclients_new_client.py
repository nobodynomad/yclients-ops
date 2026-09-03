import unittest

from pilot_yclients_new_client import (
    build_source_client,
    ensure_client,
    resolve_client_match,
)


class ClientSourceTests(unittest.TestCase):
    def test_builds_name_with_telegram_and_normalized_contacts(self):
        sale = {
            "user": {
                "name": "Егор",
                "tgUsername": "@egor_test",
                "phone": "8 (999) 123-45-67",
                "email": " EGOR@EXAMPLE.COM ",
                "yclientsClientID": 0,
            }
        }
        self.assertEqual(
            build_source_client(sale),
            {
                "name": "Егор @egor_test",
                "phone": "79991234567",
                "email": "egor@example.com",
                "hint_id": 0,
            },
        )

    def test_rejects_incomplete_source_contacts(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            build_source_client({"user": {"name": "Егор", "phone": "79991234567"}})

    def test_replaces_non_bmp_name_characters_with_yclients_safe_placeholder(self):
        sale = {
            "user": {
                "name": "G😀",
                "tgUsername": "user",
                "phone": "79991234567",
                "email": "g@example.com",
            }
        }
        self.assertEqual(build_source_client(sale)["name"], "G? @user")


class ClientMatchTests(unittest.TestCase):
    def test_no_match_returns_none(self):
        self.assertIsNone(resolve_client_match([], "79991234567", "egor@example.com", 0))

    def test_exact_phone_and_email_match_returns_id(self):
        rows = [{"id": 42, "phone": "+7 999 123-45-67", "email": "EGOR@example.com"}]
        self.assertEqual(resolve_client_match(rows, "79991234567", "egor@example.com", 0), 42)

    def test_one_sided_contact_match_is_a_conflict(self):
        rows = [{"id": 42, "phone": "+7 999 123-45-67", "email": "other@example.com"}]
        with self.assertRaisesRegex(ValueError, "conflict"):
            resolve_client_match(rows, "79991234567", "egor@example.com", 0)

    def test_hint_must_agree_with_exact_contacts(self):
        rows = [{"id": 42, "phone": "+7 999 123-45-67", "email": "egor@example.com"}]
        with self.assertRaisesRegex(ValueError, "hint"):
            resolve_client_match(rows, "79991234567", "egor@example.com", 99)


class FakeAPI:
    def __init__(self, rows, before=None):
        self.rows = rows
        self.before = before or {}
        self.calls = []
        self.client_id = 0

    def all_clients(self):
        return list(self.rows)

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST" and path == "/api/v1/clients/1116137":
            return 201, {"data": {"id": 77}}
        if method == "GET" and path == "/api/v1/client/1116137/77":
            return 200, {"data": {"id": 77, **self.created_body, "last_change_date": "2026-07-21T21:00:00+0400"}}
        if method == "GET" and path == "/api/v1/client/1116137/42":
            return 200, {"data": {"id": 42, **self.before}}
        if method == "PUT" and path == "/api/v1/client/1116137/42":
            self.before = {**self.before, **body, "last_change_date": "2026-07-21T21:01:00+0400"}
            return 200, {"data": {"id": 42, **self.before}}
        raise AssertionError((method, path, body))

    @property
    def created_body(self):
        for method, path, body in self.calls:
            if method == "POST" and path == "/api/v1/clients/1116137":
                return body
        return {}


class EnsureClientTests(unittest.TestCase):
    source = {"name": "Егор @egor_test", "phone": "79991234567", "email": "egor@example.com", "hint_id": 0}

    def test_creates_missing_client_and_verifies_readback(self):
        api = FakeAPI([])
        states = []
        result = ensure_client(api=api, company_id=1116137, source=self.source, execute=True, persist=states.append)
        self.assertEqual(result["client_id"], 77)
        self.assertEqual(result["writes"], 1)
        self.assertEqual(states[0]["stage"], "creating_client")
        self.assertEqual(states[1]["stage"], "client_created")
        self.assertEqual(states[1]["writes"], 1)
        self.assertIsNone(states[1]["original_last_change_date"])
        self.assertEqual(states[-1]["stage"], "client_verified")
        self.assertEqual(api.created_body, {"name": "Егор @egor_test", "phone": "79991234567", "email": "egor@example.com"})

    def test_live_contact_conflict_aborts_before_update(self):
        rows = [{"id": 42, "phone": "79991234567", "email": "egor@example.com"}]
        before = {"name": "Егор", "phone": "79991234567", "email": "changed@example.com", "last_change_date": "2026-01-01T12:00:00+0400"}
        api = FakeAPI(rows, before=before)
        with self.assertRaisesRegex(ValueError, "live client contact conflict"):
            ensure_client(api=api, company_id=1116137, source=self.source, execute=True, persist=lambda state: None)
        self.assertFalse(any(method == "PUT" for method, _, _ in api.calls))

    def test_syncs_existing_exact_client_and_preserves_original_change_date(self):
        rows = [{"id": 42, "phone": "79991234567", "email": "egor@example.com"}]
        before = {"name": "Егор", "phone": "79991234567", "email": "egor@example.com", "last_change_date": "2026-01-01T12:00:00+0400"}
        api = FakeAPI(rows, before=before)
        states = []
        result = ensure_client(api=api, company_id=1116137, source=self.source, execute=True, persist=states.append)
        self.assertEqual(result["client_id"], 42)
        self.assertEqual(result["writes"], 1)
        self.assertEqual(result["original_last_change_date"], "2026-01-01T12:00:00+0400")
        self.assertEqual(states[-1]["stage"], "client_verified")


if __name__ == "__main__":
    unittest.main()
