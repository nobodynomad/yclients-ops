#!/usr/bin/env python3
"""Idempotent one-client YCLIENTS subscription pilot executor."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _as_date(value) -> date:
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.fromtimestamp(int(value), timezone.utc).date()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def infer_period_days(card: dict, target: date) -> dict:
    """Infer the card's inclusive/exclusive day convention from its default readback."""
    if int(card.get("period_unit_id") or 0) != 1:
        raise ValueError("card default period is not measured in days")
    period = int(card.get("period") or 0)
    if period <= 0:
        raise ValueError("card default period is invalid")
    expiration = _as_date(card.get("expiration_date"))
    candidates = []
    for base_name in ("activated_date", "created_date"):
        if not card.get(base_name):
            continue
        base = _as_date(card[base_name])
        observed_offset = (expiration - base).days - period
        if observed_offset in (0, -1):
            target_period = (target - base).days - observed_offset
            if target_period > 0:
                candidates.append((base_name, base, observed_offset, target_period))
    if not candidates:
        raise ValueError("cannot infer period convention from default card readback")
    base_name, base, offset, target_period = candidates[0]
    return {
        "base": base_name,
        "base_date": base.isoformat(),
        "observed_offset_days": offset,
        "period_days": target_period,
        "expected_expiration": target.isoformat(),
    }


def select_issued_card(before: list[dict], after: list[dict], type_title: str) -> dict:
    before_ids = {str(card.get("id")) for card in before if card.get("id") is not None}
    matches = [
        card for card in after
        if str(card.get("id")) not in before_ids
        and str((card.get("type") or {}).get("title") or "") == type_title
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one newly issued {type_title!r} card, got {len(matches)}")
    return matches[0]


def validate_preflight(*, approved_client_id: int, exact_contact_match_ids: list[int],
                       active_cards: list[dict], planned_type_titles: list[str]) -> None:
    ids = {int(value) for value in exact_contact_match_ids}
    if ids != {int(approved_client_id)}:
        raise ValueError("exact contact matches do not resolve to the approved client")
    active_planned = [
        card for card in active_cards
        if str((card.get("type") or {}).get("title") or "") in set(planned_type_titles)
    ]
    if active_planned:
        raise ValueError("an approved target subscription is already active")


def pending_type_titles(planned: list[str], ledger: dict) -> list[str]:
    operations = ledger.get("operations") if isinstance(ledger.get("operations"), dict) else {}
    pending = []
    for title in planned:
        operation = operations.get(title)
        if not operation or operation.get("stage") == "pending":
            pending.append(title)
    return pending


def _card_by_id(cards: list[dict], card_id: int) -> dict:
    matches = [card for card in cards if int(card.get("id") or 0) == int(card_id)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one card {card_id}, got {len(matches)}")
    return matches[0]


def execute_planned_card(*, api, before_cards: list[dict], phone: str, type_id: int,
                         type_title: str, quantity: int, target_expiration: date,
                         persist) -> dict:
    state = {"stage": "issuing", "type_title": type_title, "quantity": quantity}
    persist(state)
    api.issue_card(phone, type_id)

    issued = select_issued_card(before_cards, api.active_subscriptions(phone), type_title)
    card_id = int(issued["id"])
    period_model = infer_period_days(issued, target_expiration)
    state.update({
        "stage": "issued",
        "card_id": card_id,
        "period_model": period_model,
        "issue_meta": dict(getattr(api, "last_issue_meta", {}) or {}),
    })
    persist(state)

    api.set_balance(card_id, quantity)
    balanced = _card_by_id(api.active_subscriptions(phone), card_id)
    actual_balance = int(balanced.get("united_balance_services_count") or 0)
    if actual_balance != int(quantity):
        raise ValueError(f"balance readback mismatch: expected {quantity}, got {actual_balance}")
    state.update({"stage": "balance_verified", "verified_balance": actual_balance})
    persist(state)

    api.set_period(card_id, int(period_model["period_days"]))
    final = _card_by_id(api.active_subscriptions(phone), card_id)
    actual_expiration = _as_date(final.get("expiration_date")).isoformat()
    if actual_expiration != target_expiration.isoformat():
        raise ValueError(
            f"expiration readback mismatch: expected {target_expiration.isoformat()}, got {actual_expiration}"
        )
    state.update({
        "stage": "completed",
        "verified_balance": actual_balance,
        "verified_expiration": actual_expiration,
    })
    persist(state)
    return state


def issuance_write_request_count() -> int:
    """Document + goods transaction + balance + period."""
    return 4


def build_document_payload(*, storage_id: int, create_date: str, comment: str) -> dict:
    return {
        "type_id": 1,
        "storage_id": int(storage_id),
        "create_date": create_date,
        "comment": comment,
    }


def build_goods_transaction_payload(*, document_id: int, good_id: int, client_id: int,
                                    cost: float, comment: str) -> dict:
    return {
        "document_id": int(document_id),
        "good_id": int(good_id),
        "amount": 1,
        "cost_per_unit": cost,
        "discount": 0,
        "cost": cost,
        "operation_unit_type": 1,
        "client_id": int(client_id),
        "comment": comment,
    }


ROOT = Path(os.environ.get("YCLIENTS_OPS_HOME", Path(__file__).resolve().parents[1]))
SECRETS_DIR = Path(os.environ.get("YCLIENTS_OPS_SECRETS_DIR", ROOT / "secrets"))
FF_SECRET = Path(os.environ.get("FF_SALES_SECRET_FILE", SECRETS_DIR / "ff_sales.env"))
YC_SECRET = Path(os.environ.get("YCLIENTS_SECRET_FILE", SECRETS_DIR / "yclients.env"))
OWNER_SECRET = Path(os.environ.get("YCLIENTS_OWNER_SECRET_FILE", SECRETS_DIR / "yclients_owner.env"))
LEDGER_PATH = ROOT / "runtime/subscription_pilot_ledger.json"
AUDIT_PATH = ROOT / "runtime/subscription_pilot_latest.json"
FF_ENDPOINT = "https://ff-bot.com/ffapi/sales/list"
YC_API = "https://api.yclients.com"
CHAIN_ID = 1117924
STORAGE_ID = 2255377
ABONEMENT_GOOD_IDS = {
    "Индивидуальная консультация": 36892736,
    "Групповая консультация": 34799717,
}


def _env_file(path: Path) -> dict[str, str]:
    return {
        key.strip(): value.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
        for key, value in [line.split("=", 1)]
    }


def _private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)


def _norm_phone(value) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def _sale_ref(value) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:10]


def _fetch_approved_sale(email: str, expected_ref: str) -> dict:
    api_key = _env_file(FF_SECRET)["FF_SALES_API_KEY"]
    today = date.today()
    payload = {
        "apiKey": api_key,
        "search": email,
        "purchaseDateFrom": (today - timedelta(days=13)).isoformat(),
        "purchaseDateTo": (today + timedelta(days=1)).isoformat(),
        "page": 1,
        "perPage": 50,
    }
    request = urllib.request.Request(
        FF_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    exact = [
        sale for sale in (result.get("sales") or [])
        if str((sale.get("user") or {}).get("email") or "").strip().lower() == email.lower()
    ]
    if len(exact) != 1:
        raise ValueError(f"expected one exact FF sale for approved email, got {len(exact)}")
    sale = exact[0]
    uc = sale.get("userCourse") or {}
    course = sale.get("course") or {}
    if _sale_ref(uc.get("purchaseID")) != expected_ref:
        raise ValueError("FF sale reference changed or does not match the approval")
    if uc.get("courseID") != course.get("id"):
        raise ValueError("FF course relationship mismatch")
    return sale


class LiveYClients:
    def __init__(self, partner: str, user: str, company_id: int, client_id: int, sale_ref: str):
        self.company_id = int(company_id)
        self.client_id = int(client_id)
        self.sale_ref = sale_ref
        self.last_issue_meta = {}
        self.headers = {
            "Authorization": f"Bearer {partner}, User {user}",
            "Accept": "application/vnd.yclients.v2+json",
            "Content-Type": "application/json",
            "User-Agent": "Hermes-YCLIENTS-Approved-Pilot/1.0",
        }

    def call(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(YC_API + path, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                payload = json.loads(raw) if raw else None
                return response.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            meta = payload.get("meta") if isinstance(payload, dict) else {}
            message = meta.get("message") if isinstance(meta, dict) else None
            raise RuntimeError(f"YCLIENTS HTTP {exc.code}: {message or 'request failed'}") from None

    def all_clients(self) -> list[dict]:
        rows = []
        seen = set()
        for page in range(1, 500):
            status, payload = self.call(
                "POST",
                f"/api/v1/company/{self.company_id}/clients/search",
                {
                    "page": page,
                    "page_size": 200,
                    "fields": ["id", "phone", "email"],
                    "order_by": "id",
                    "order_by_direction": "ASC",
                },
            )
            if status != 200:
                raise RuntimeError("client preflight failed")
            batch = payload.get("data") if isinstance(payload, dict) else []
            batch = batch if isinstance(batch, list) else []
            before = len(seen)
            for row in batch:
                identifier = str(row.get("id"))
                if identifier not in seen:
                    seen.add(identifier)
                    rows.append(row)
            if batch and len(seen) == before:
                raise RuntimeError("client pagination repeated")
            if len(batch) < 200:
                return rows
        raise RuntimeError("client pagination safety limit reached")

    def subscription_types(self) -> list[dict]:
        query = urllib.parse.urlencode({"page": 1, "page_size": 100})
        status, payload = self.call(
            "GET", f"/api/v1/company/{self.company_id}/loyalty/abonement_types/search?{query}"
        )
        if status != 200:
            raise RuntimeError("subscription type lookup failed")
        return payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), list) else []

    def active_subscriptions(self, phone: str) -> list[dict]:
        query = urllib.parse.urlencode({"company_id": self.company_id, "phone": phone})
        status, payload = self.call("GET", f"/api/v1/loyalty/abonements/?{query}")
        if status != 200:
            raise RuntimeError("active subscription read failed")
        return payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), list) else []

    def good(self, good_id: int) -> dict:
        status, payload = self.call("GET", f"/api/v1/goods/{self.company_id}/{int(good_id)}")
        if status != 200:
            raise RuntimeError("membership good lookup failed")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise RuntimeError("membership good response is invalid")
        return data

    def issue_card(self, phone: str, good_id: int) -> None:
        # Memberships are issued by selling their linked special goods one at a time.
        good = self.good(good_id)
        cost = good.get("cost")
        if not isinstance(cost, (int, float)):
            raise RuntimeError("membership good cost is invalid")
        comment = f"FF API pilot {self.sale_ref}"
        self.last_issue_meta = {"stage": "creating_document", "good_id": int(good_id)}
        status, payload = self.call(
            "POST",
            f"/api/v1/storage_operations/documents/{self.company_id}",
            build_document_payload(
                storage_id=STORAGE_ID,
                create_date=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                comment=comment,
            ),
        )
        document = payload.get("data") if isinstance(payload, dict) else None
        document_id = int((document or {}).get("id") or 0)
        if not 200 <= status < 300 or not document_id:
            raise RuntimeError("sale document creation did not return an id")
        self.last_issue_meta = {
            "stage": "document_created",
            "good_id": int(good_id),
            "document_id": document_id,
        }
        try:
            status, payload = self.call(
                "POST",
                f"/api/v1/storage_operations/goods_transactions/{self.company_id}",
                build_goods_transaction_payload(
                    document_id=document_id,
                    good_id=good_id,
                    client_id=self.client_id,
                    cost=cost,
                    comment=comment,
                ),
            )
            transaction = payload.get("data") if isinstance(payload, dict) else None
            transaction_id = int((transaction or {}).get("id") or 0)
            if not 200 <= status < 300 or not transaction_id:
                raise RuntimeError("membership sale transaction did not return an id")
        except Exception:
            try:
                cleanup_status, _ = self.call(
                    "DELETE",
                    f"/api/v1/storage_operations/documents/{self.company_id}/{document_id}",
                )
                self.last_issue_meta["empty_document_cleanup_http"] = cleanup_status
            except Exception as cleanup_exc:
                self.last_issue_meta["empty_document_cleanup_error"] = type(cleanup_exc).__name__
            raise
        self.last_issue_meta = {
            "stage": "transaction_created",
            "good_id": int(good_id),
            "document_id": document_id,
            "goods_transaction_id": transaction_id,
        }
        time.sleep(1.0)

    def set_balance(self, card_id: int, quantity: int) -> None:
        status, _ = self.call(
            "POST",
            f"/api/v1/chain/{CHAIN_ID}/loyalty/abonements/{card_id}/set_balance",
            {"united_balance_services_count": int(quantity), "services_balance_count": []},
        )
        if status != 200:
            raise RuntimeError(f"balance update returned HTTP {status}")
        time.sleep(0.8)

    def set_period(self, card_id: int, period_days: int) -> None:
        status, _ = self.call(
            "POST",
            f"/api/v1/chain/{CHAIN_ID}/loyalty/abonements/{card_id}/set_period",
            {"period": int(period_days), "period_unit_id": 1},
        )
        if status != 200:
            raise RuntimeError(f"period update returned HTTP {status}")
        time.sleep(0.8)


def _plans_from_sale(sale: dict) -> tuple[str, str, list[dict]]:
    user = sale.get("user") or {}
    uc = sale.get("userCourse") or {}
    phone = _norm_phone(user.get("phone"))
    email = str(user.get("email") or "").strip().lower()
    target = _as_date(uc.get("gracePeriodEndDate"))
    if not phone or not email or target <= date.today():
        raise ValueError("approved sale no longer has valid phone/email/future grace date")
    plans = []
    personal = int(uc.get("kolPersonalConsultations") or 0)
    group = int(uc.get("kolGroupConsultations") or 0)
    if personal > 0:
        plans.append({"type_title": "Индивидуальная консультация", "quantity": personal, "target": target})
    if group > 0:
        plans.append({"type_title": "Групповая консультация", "quantity": group, "target": target})
    if not plans:
        raise ValueError("approved sale has no consultation quantities")
    return phone, email, plans


def run_pilot(*, email: str, approved_client_id: int, expected_ref: str, execute: bool) -> dict:
    yc_env = _env_file(YC_SECRET)
    owner = _env_file(OWNER_SECRET)
    sale = _fetch_approved_sale(email, expected_ref)
    phone, source_email, plans = _plans_from_sale(sale)
    client = LiveYClients(
        yc_env["YCLIENTS_PARTNER_TOKEN"],
        owner["YCLIENTS_OWNER_USER_TOKEN"],
        int(yc_env["YCLIENTS_COMPANY_ID"]),
        approved_client_id,
        expected_ref,
    )

    exact_ids = {
        int(row["id"])
        for row in client.all_clients()
        if str(row.get("email") or "").strip().lower() == source_email
        or _norm_phone(row.get("phone")) == phone
    }
    before = client.active_subscriptions(phone)
    planned_titles = [plan["type_title"] for plan in plans]

    existing_ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8")) if LEDGER_PATH.exists() else None
    if existing_ledger is None:
        validate_preflight(
            approved_client_id=approved_client_id,
            exact_contact_match_ids=sorted(exact_ids),
            active_cards=before,
            planned_type_titles=planned_titles,
        )
    else:
        if existing_ledger.get("sale_ref") != expected_ref or int(existing_ledger.get("client_id") or 0) != approved_client_id:
            raise ValueError("existing pilot ledger belongs to another sale or client")
        known_ids = {
            int(operation["card_id"])
            for operation in (existing_ledger.get("operations") or {}).values()
            if operation.get("card_id") is not None
        }
        unknown_active = [
            card for card in before
            if (card.get("type") or {}).get("title") in planned_titles
            and int(card.get("id") or 0) not in known_ids
        ]
        if unknown_active:
            raise ValueError("untracked active target subscription appeared after initial preflight")

    types_by_title = {}
    for item in client.subscription_types():
        types_by_title.setdefault(str(item.get("title") or ""), []).append(item)
    goods_by_title = {}
    for title in planned_titles:
        matches = types_by_title.get(title, [])
        if len(matches) != 1 or not matches[0].get("is_allow_empty_code"):
            raise ValueError(f"approved subscription type {title!r} is missing, duplicated, or requires a code")
        good_id = ABONEMENT_GOOD_IDS.get(title)
        if not good_id:
            raise ValueError(f"no approved special good configured for {title!r}")
        good = client.good(good_id)
        if (
            str(good.get("title") or "") != title
            or int(good.get("loyalty_abonement_type_id") or 0) != int(matches[0]["id"])
            or not bool(good.get("loyalty_allow_empty_code"))
            or not isinstance(good.get("cost"), (int, float))
        ):
            raise ValueError(f"special good linkage validation failed for {title!r}")
        goods_by_title[title] = good

    preflight = {
        "sale_ref": expected_ref,
        "client_id": approved_client_id,
        "exact_contact_match_count": len(exact_ids),
        "active_target_cards_before": sum(
            1 for card in before if (card.get("type") or {}).get("title") in planned_titles
        ),
        "plans": [
            {"type_title": plan["type_title"], "quantity": plan["quantity"], "target_expiration": plan["target"].isoformat()}
            for plan in plans
        ],
        "execute_requested": execute,
    }
    if not execute:
        return {"status": "preflight_ok", **preflight, "yclients_writes": 0}

    ledger = existing_ledger or {
        "version": 1,
        "sale_ref": expected_ref,
        "client_id": approved_client_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operations": {
            plan["type_title"]: {
                "stage": "pending",
                "quantity": plan["quantity"],
                "target_expiration": plan["target"].isoformat(),
            }
            for plan in plans
        },
    }
    _private_json(LEDGER_PATH, ledger)
    pending = pending_type_titles(planned_titles, ledger)
    started_nonpending = [
        title for title in planned_titles
        if title not in pending and (ledger["operations"].get(title) or {}).get("stage") != "completed"
    ]
    if started_nonpending:
        raise ValueError(f"pilot has partially started operations requiring manual recovery: {started_nonpending}")

    results = []
    writes_performed = 0
    for plan in plans:
        title = plan["type_title"]
        if title not in pending:
            results.append(dict(ledger["operations"][title]))
            continue

        def persist(state, operation_title=title):
            ledger["operations"][operation_title] = {
                **ledger["operations"].get(operation_title, {}),
                **state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _private_json(LEDGER_PATH, ledger)

        operation_before = client.active_subscriptions(phone)
        try:
            result = execute_planned_card(
                api=client,
                before_cards=operation_before,
                phone=phone,
                type_id=int(goods_by_title[title]["good_id"]),
                type_title=title,
                quantity=int(plan["quantity"]),
                target_expiration=plan["target"],
                persist=persist,
            )
            results.append(result)
            writes_performed += issuance_write_request_count()
        except Exception as exc:
            ledger["last_error"] = {
                "operation": title,
                "error_type": type(exc).__name__,
                "message": str(exc)[:300],
                "issue_meta": dict(getattr(client, "last_issue_meta", {}) or {}),
                "at": datetime.now(timezone.utc).isoformat(),
            }
            _private_json(LEDGER_PATH, ledger)
            raise

    final_cards = client.active_subscriptions(phone)
    verified = []
    for plan in plans:
        operation = ledger["operations"][plan["type_title"]]
        card = _card_by_id(final_cards, int(operation["card_id"]))
        verified.append({
            "type_title": plan["type_title"],
            "card_id": int(card["id"]),
            "balance": int(card.get("united_balance_services_count") or 0),
            "expiration": _as_date(card.get("expiration_date")).isoformat(),
            "status": str((card.get("status") or {}).get("title") or ""),
        })
    audit = {
        "status": "completed",
        **preflight,
        "verified_cards": verified,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "yclients_writes": writes_performed,
    }
    _private_json(AUDIT_PATH, audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--approved-client-id", required=True, type=int)
    parser.add_argument("--expected-sale-ref", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = run_pilot(
        email=args.email,
        approved_client_id=args.approved_client_id,
        expected_ref=args.expected_sale_ref,
        execute=args.execute,
    )
    # This result contains IDs and aggregate operation data, but no contacts or secrets.
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
