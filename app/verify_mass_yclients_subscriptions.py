#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, timedelta, timezone, datetime
import json
from pathlib import Path
import sys
import urllib.parse

sys.path.insert(0, str(Path(__file__).parent))
import build_subscription_dry_run as dry
import mass_yclients_subscriptions as mass
import pilot_yclients_new_client as client_flow
import pilot_yclients_subscription as core

LEDGER = mass.LEDGER_PATH
OUT = mass.LEDGER_PATH.parent / "2026-07-01_2026-07-21_verification.json"


def assert_exact_ledger_cards(active_cards: list[dict], operations: list[dict]) -> None:
    active_ids = {int(item.get("id") or 0) for item in active_cards}
    expected_ids = {int(item.get("card_id") or 0) for item in operations}
    if 0 in active_ids or 0 in expected_ids or active_ids != expected_ids:
        raise ValueError(f"active card set differs from ledger: active={sorted(active_ids)}, expected={sorted(expected_ids)}")


def validate_card_state(card: dict, state: dict) -> None:
    title = str(state.get("type_title") or "")
    if str((card.get("type") or {}).get("title") or "") != title:
        raise ValueError("active card type mismatch")
    expected_balance = int(
        state.get("verified_balance")
        if state.get("verified_balance") is not None
        else state.get("balance_after")
    )
    if int(card.get("united_balance_services_count") or 0) != expected_balance:
        raise ValueError("active card balance mismatch")
    expiration_value = state.get("verified_expiration") or state.get("expiration_before")
    if core._as_date(card.get("expiration_date")) != core._as_date(expiration_value):
        raise ValueError("active card expiration mismatch")
    if str((card.get("status") or {}).get("slug") or "").lower() != "active":
        raise ValueError("active card status mismatch")
    if state.get("verified_period") is not None:
        expected_period = int(state["verified_period"])
        expected_unit = int(state["verified_period_unit_id"])
        if int(card.get("period") or 0) != expected_period or int(card.get("period_unit_id") or 0) != expected_unit:
            raise ValueError("active package period mismatch")


def fail(errors: list[dict], ref: str, scope: str, message: str) -> None:
    errors.append({"sale_ref": ref, "scope": scope, "message": message})


def main() -> None:
    global LEDGER, OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="inclusive purchaseDate start, YYYY-MM-DD")
    parser.add_argument("--end", help="inclusive purchaseDate end, YYYY-MM-DD")
    parser.add_argument("--telegram-override", action="append", default=[], metavar="EMAIL=@USERNAME")
    args = parser.parse_args()
    if (args.start is None) != (args.end is None):
        raise ValueError("--start and --end must be provided together")
    if args.start is not None:
        config = mass.configure_period(date.fromisoformat(args.start), date.fromisoformat(args.end))
        mass.START = config["start"]
        mass.END = config["end"]
        mass.LEDGER_PATH = config["ledger_path"]
        mass.AUDIT_PATH = config["audit_path"]
        LEDGER = config["ledger_path"]
        OUT = config["ledger_path"].parent / f"{args.start}_{args.end}_verification.json"
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ff = dry.env_file(dry.FF_SECRET)
    yc = dry.env_file(dry.YC_SECRET)
    owner = dry.env_file(dry.OWNER_SECRET)
    company_id = int(yc["YCLIENTS_COMPANY_ID"])
    total, sales, _ = dry.fetch_sales(ff["FF_SALES_API_KEY"], mass.START, mass.END + timedelta(days=1))
    telegram_overrides = dry.parse_telegram_overrides(args.telegram_override)
    overrides_applied = dry.apply_telegram_overrides(sales, telegram_overrides)
    sales_by_ref = {
        dry.sale_ref((sale.get("userCourse") or {}).get("purchaseID")): sale
        for sale in sales
    }
    errors: list[dict] = []
    clients_verified: set[int] = set()
    active_operations_verified = 0
    network_cards_verified = 0
    transactions_verified = 0
    documents_verified = 0

    operations_by_ref: dict[str, list[dict]] = {}
    for state in ledger.get("operations", {}).values():
        operations_by_ref.setdefault(str(state.get("sale_ref") or ""), []).append(state)

    for ref, operations in sorted(operations_by_ref.items()):
        sale = sales_by_ref.get(ref)
        if not sale:
            fail(errors, ref, "source", "sale missing from live source")
            continue
        source = client_flow.build_source_client(sale)
        client_ids = {int(item.get("client_id") or 0) for item in operations}
        if len(client_ids) != 1 or 0 in client_ids:
            fail(errors, ref, "client", "operation client IDs are not unique")
            continue
        client_id = next(iter(client_ids))
        api = core.LiveYClients(
            yc["YCLIENTS_PARTNER_TOKEN"],
            owner["YCLIENTS_OWNER_USER_TOKEN"],
            company_id,
            client_id,
            ref,
        )
        status, payload = api.call("GET", f"/api/v1/client/{company_id}/{client_id}")
        client = payload.get("data") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(client, dict):
            fail(errors, ref, "client", "client GET failed")
            continue
        if (
            str(client.get("name") or "") != source["name"]
            or client_flow.norm_phone(client.get("phone")) != source["phone"]
            or str(client.get("email") or "").strip().lower() != source["email"]
        ):
            fail(errors, ref, "client", "client readback differs from source")
        else:
            clients_verified.add(client_id)

        active = api.active_subscriptions(source["phone"])
        active_by_id = {int(item.get("id") or 0): item for item in active}
        try:
            assert_exact_ledger_cards(active, operations)
        except ValueError as exc:
            fail(errors, ref, "cards", str(exc))
        for state in operations:
            card_id = int(state.get("card_id") or 0)
            title = str(state.get("type_title") or "")
            card = active_by_id.get(card_id)
            if not card:
                fail(errors, ref, title, "completed card is absent from active readback")
                continue
            try:
                validate_card_state(card, state)
            except ValueError as exc:
                fail(errors, ref, title, str(exc))
                continue
            active_operations_verified += 1

            if state.get("action") != "issue_new":
                continue
            meta = state.get("issue_meta") or {}
            transaction_id = int(meta.get("goods_transaction_id") or 0)
            document_id = int(meta.get("document_id") or 0)
            query = urllib.parse.urlencode({
                "created_after": mass.START.isoformat(),
                "created_before": (mass.END + timedelta(days=1)).isoformat(),
                "abonements_ids": card_id,
                "page": 1,
                "count": 10,
            })
            net_status, net_payload = api.call(
                "GET", f"/api/v1/chain/{core.CHAIN_ID}/loyalty/abonements?{query}"
            )
            network_rows = net_payload.get("data") if isinstance(net_payload, dict) else None
            if net_status != 200 or not isinstance(network_rows, list) or len(network_rows) != 1:
                fail(errors, ref, title, "network card readback did not return exactly one row")
                continue
            network_card = network_rows[0]
            if int(network_card.get("id") or 0) != card_id or int(network_card.get("goods_transaction_id") or 0) != transaction_id:
                fail(errors, ref, title, "network card transaction linkage mismatch")
                continue
            network_cards_verified += 1

            tx_status, tx_payload = api.call(
                "GET", f"/api/v1/storage_operations/goods_transactions/{company_id}/{transaction_id}"
            )
            transaction = tx_payload.get("data") if isinstance(tx_payload, dict) else None
            expected_good = int(mass.GOOD_IDS[title])
            if (
                tx_status != 200
                or not isinstance(transaction, dict)
                or int(transaction.get("id") or 0) != transaction_id
                or int(transaction.get("document_id") or 0) != document_id
                or int(transaction.get("good_id") or 0) != expected_good
                or int(transaction.get("client_id") or 0) != client_id
                or int(transaction.get("storage_id") or 0) != core.STORAGE_ID
                or int(transaction.get("type_id") or 0) != 1
                or bool(transaction.get("deleted"))
            ):
                fail(errors, ref, title, "goods transaction readback mismatch")
                continue
            transactions_verified += 1

            doc_status, doc_payload = api.call(
                "GET", f"/api/v1/storage_operations/documents/{company_id}/{document_id}"
            )
            document = doc_payload.get("data") if isinstance(doc_payload, dict) else None
            if (
                doc_status != 200
                or not isinstance(document, dict)
                or int(document.get("id") or 0) != document_id
                or int(document.get("storage_id") or 0) != core.STORAGE_ID
                or int(document.get("type_id") or 0) != 1
            ):
                fail(errors, ref, title, "sale document readback mismatch")
                continue
            documents_verified += 1

    result = {
        "status": "verified" if not errors else "failed",
        "period": ledger.get("period"),
        "source_sales": total,
        "user_confirmed_telegram_overrides_applied": overrides_applied,
        "ledger_operations": len(ledger.get("operations") or {}),
        "clients_verified": len(clients_verified),
        "active_operations_verified": active_operations_verified,
        "network_cards_verified": network_cards_verified,
        "transactions_verified": transactions_verified,
        "documents_verified": documents_verified,
        "errors": errors,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "yclients_write_requests_performed": 0,
    }
    core._private_json(OUT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
