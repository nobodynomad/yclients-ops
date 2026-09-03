#!/usr/bin/env python3
"""Idempotent mass YCLIENTS subscription provisioning for an approved purchase-date period."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path

import build_subscription_dry_run as dry
import pilot_yclients_new_client as client_flow
import pilot_yclients_subscription as core


BASE = Path(os.environ.get("YCLIENTS_OPS_HOME", Path(__file__).resolve().parents[1]))
DRY_RUN_PATH = BASE / "runtime/subscription_dry_run_latest.json"
LEDGER_PATH = BASE / "runtime/mass_subscription_ledgers/2026-07-01_2026-07-21.json"
AUDIT_PATH = BASE / "runtime/mass_subscription_ledgers/2026-07-01_2026-07-21_audit.json"
START = date(2026, 7, 1)
END = date(2026, 7, 21)
GOOD_IDS = dict(core.ABONEMENT_GOOD_IDS)
GOOD_IDS.update({
    "Консультации (3 шт.)": 35724188,
    "Консультации (5 шт.)": 35724211,
    "Консультации (8 шт.)": 35724237,
})


def configure_period(start: date, end: date, *, today: date | None = None) -> dict:
    current = today or date.today()
    if start > end:
        raise ValueError("period start is after end")
    if end > current:
        raise ValueError("period end is in the future")
    stem = f"{start.isoformat()}_{end.isoformat()}"
    return {
        "start": start,
        "end": end,
        "ledger_path": BASE / "runtime/mass_subscription_ledgers" / f"{stem}.json",
        "audit_path": BASE / "runtime/mass_subscription_ledgers" / f"{stem}_audit.json",
    }


def validate_new_client_eligibility(client_state: str, resolved_client_id: int | None,
                                    known_ledger_client_id: int | None) -> None:
    if client_state != "new":
        raise ValueError("ready action is not a dry-run new-client action")
    if resolved_client_id is None:
        return
    if known_ledger_client_id and int(resolved_client_id) == int(known_ledger_client_id):
        return
    raise ValueError("an untracked client appeared after the dry-run; subscription issuance stopped")


def merge_client_state(previous: dict, current: dict) -> dict:
    merged = {**(previous or {}), **(current or {})}
    merged["writes"] = max(int((previous or {}).get("writes") or 0), int((current or {}).get("writes") or 0))
    if "original_last_change_date" in (previous or {}):
        merged["original_last_change_date"] = previous.get("original_last_change_date")
    return merged


def clear_resolved_client_failure(ledger: dict, sale_reference: str) -> None:
    failures = ledger.get("failures") if isinstance(ledger.get("failures"), dict) else {}
    failures.pop(f"{sale_reference}::__client_or_sale__", None)


def validate_execution_action(action: str) -> None:
    if action != "issue_new":
        raise ValueError(f"forbidden subscription action under current policy: {action}")


def final_status(*, failures: list[dict], completed: int, planned: int) -> str:
    return "completed" if not failures and int(completed) == int(planned) else "partial"


def operation_key(sale_reference: str, type_title: str) -> str:
    return f"{sale_reference}::{type_title}"


def expected_operation_total(existing_operations: dict, ready_entries: list[dict]) -> int:
    keys = set((existing_operations or {}).keys())
    for entry in ready_entries:
        reference = str(entry.get("sale_ref") or "")
        for operation in entry.get("operations") or []:
            keys.add(operation_key(reference, str(operation.get("type") or "")))
    return len(keys)


def validate_artifact(artifact: dict, *, start: date, end: date, source_count: int) -> None:
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    period = summary.get("period") if isinstance(summary.get("period"), dict) else {}
    expected_period = {
        "purchaseDateFrom_inclusive": start.isoformat(),
        "purchaseDateThrough_inclusive": end.isoformat(),
        "purchaseDateTo_exclusive_sent": (end + timedelta(days=1)).isoformat(),
    }
    if period != expected_period:
        raise ValueError("dry-run period does not match approved period")
    source = summary.get("source") if isinstance(summary.get("source"), dict) else {}
    if int(source.get("rows_collected") or -1) != int(source_count):
        raise ValueError("dry-run source count changed")
    if int(source.get("unique_purchase_ids") or -1) != int(source_count):
        raise ValueError("dry-run purchase IDs are not unique")
    if len(artifact.get("entries") or []) != int(source_count):
        raise ValueError("dry-run entry count changed")


def _contact_ref(source: dict) -> str:
    return hashlib.sha256(f"{source['phone']}|{source['email']}".encode("utf-8")).hexdigest()[:12]


def execute_issue(*, api, phone: str, good_id: int, type_title: str, quantity: int,
                  target_expiration: date | None, previous_state: dict | None, persist,
                  configured_period: tuple[int, int] | None = None) -> dict:
    writes = 0
    if previous_state and previous_state.get("stage") == "completed":
        return {**previous_state, "writes": 0}

    state = dict(previous_state or {})
    if not state:
        before = api.active_subscriptions(phone)
        if any(str((item.get("type") or {}).get("title") or "") == type_title for item in before):
            raise ValueError("untracked active target subscription before issue")
        state = {
            "stage": "issuing",
            "type_title": type_title,
            "quantity": int(quantity),
            "target_expiration": target_expiration.isoformat() if target_expiration else None,
            "before_card_ids": [int(item["id"]) for item in before if item.get("id") is not None],
        }
        persist(dict(state))
        api.issue_card(phone, int(good_id))
        writes += 2
        issued = core.select_issued_card(before, api.active_subscriptions(phone), type_title)
        period_model = core.infer_period_days(issued, target_expiration) if target_expiration else None
        state.update({
            "stage": "issued",
            "card_id": int(issued["id"]),
            "period_model": period_model,
            "issue_meta": dict(getattr(api, "last_issue_meta", {}) or {}),
        })
        persist(dict(state))
    elif state.get("stage") == "issuing":
        if not (state.get("issue_meta") or {}).get("goods_transaction_id"):
            raise ValueError("partially started issue requires manual recovery")
        before = [{"id": identifier} for identifier in state.get("before_card_ids") or []]
        issued = core.select_issued_card(before, api.active_subscriptions(phone), type_title)
        state.update({
            "stage": "issued",
            "card_id": int(issued["id"]),
            "period_model": core.infer_period_days(issued, target_expiration) if target_expiration else None,
        })
        persist(dict(state))
    elif state.get("stage") not in ("issued", "balance_verified"):
        raise ValueError(f"unsupported partial issue stage: {state.get('stage')}")

    card_id = int(state["card_id"])
    if state["stage"] == "issued":
        current = _card_by_id(api.active_subscriptions(phone), card_id)
        balance = int(current.get("united_balance_services_count") or 0)
        if balance != int(quantity):
            api.set_balance(card_id, int(quantity))
            writes += 1
            current = _card_by_id(api.active_subscriptions(phone), card_id)
            balance = int(current.get("united_balance_services_count") or 0)
        if balance != int(quantity):
            raise ValueError("issued subscription balance readback mismatch")
        state.update({"stage": "balance_verified", "verified_balance": balance})
        persist(dict(state))

    current = _card_by_id(api.active_subscriptions(phone), card_id)
    actual_expiration = core._as_date(current.get("expiration_date"))
    if target_expiration is not None and actual_expiration != target_expiration:
        model = state.get("period_model") or core.infer_period_days(current, target_expiration)
        api.set_period(card_id, int(model["period_days"]))
        writes += 1
        current = _card_by_id(api.active_subscriptions(phone), card_id)
        actual_expiration = core._as_date(current.get("expiration_date"))
    if target_expiration is not None and actual_expiration != target_expiration:
        raise ValueError("issued subscription expiration readback mismatch")
    final_balance = int(current.get("united_balance_services_count") or 0)
    if final_balance != int(quantity):
        raise ValueError("issued subscription final balance mismatch")
    verified_period = None
    verified_period_unit_id = None
    if configured_period is not None:
        verified_period = int(current.get("period") or 0)
        verified_period_unit_id = int(current.get("period_unit_id") or 0)
        if (verified_period, verified_period_unit_id) != tuple(map(int, configured_period)):
            raise ValueError("issued package configured period readback mismatch")
    state.update({
        "stage": "completed",
        "verified_balance": final_balance,
        "verified_expiration": actual_expiration.isoformat(),
        "verified_period": verified_period,
        "verified_period_unit_id": verified_period_unit_id,
        "writes": writes,
    })
    persist(dict(state))
    return state


def select_topup_card(cards: list[dict], type_title: str, *, today: date) -> dict:
    matching = []
    for item in cards:
        if str((item.get("type") or {}).get("title") or "") != type_title:
            continue
        expiration = core._as_date(item.get("expiration_date")) if item.get("expiration_date") else None
        slug = str((item.get("status") or {}).get("slug") or "").lower()
        if expiration is not None and expiration < today:
            continue
        if "expired" in slug or "prosrochen" in slug:
            continue
        matching.append(item)
    if not matching:
        raise ValueError("no nonexpired matching subscription")
    if len(matching) == 1:
        return matching[0]
    positives = [item for item in matching if int(item.get("united_balance_services_count") or 0) > 0]
    if positives:
        raise ValueError("multiple nonexpired matching subscriptions include positive balance")
    if all(int(item.get("united_balance_services_count") or 0) == 0 for item in matching):
        return sorted(matching, key=lambda item: int(item.get("id") or 0))[0]
    raise ValueError("multiple nonexpired matching subscriptions have uncovered state")


def recovery_decision(*, current: int, before: int, target: int) -> str:
    if current == target:
        return "complete"
    if current == before:
        return "retry"
    return "conflict"


def _card_by_id(cards: list[dict], card_id: int) -> dict:
    matches = [item for item in cards if int(item.get("id") or 0) == int(card_id)]
    if len(matches) != 1:
        raise ValueError(f"expected one active subscription {card_id}, got {len(matches)}")
    return matches[0]


def execute_topup(*, api, phone: str, type_title: str, quantity: int,
                  previous_state: dict | None, persist, today: date) -> dict:
    writes = 0
    if previous_state and previous_state.get("stage") == "completed":
        return {**previous_state, "writes": 0}

    cards = api.active_subscriptions(phone)
    if previous_state and previous_state.get("stage") == "balance_updating":
        state = dict(previous_state)
        selected = _card_by_id(cards, int(state["card_id"]))
        current = int(selected.get("united_balance_services_count") or 0)
        decision = recovery_decision(
            current=current,
            before=int(state["balance_before"]),
            target=int(state["target_balance"]),
        )
        if decision == "conflict":
            raise ValueError("top-up recovery balance conflict")
        if decision == "complete":
            if core._as_date(selected.get("expiration_date")) != core._as_date(state["expiration_before"]):
                raise ValueError("top-up recovery expiration conflict")
            state.update({"stage": "completed", "balance_after": current, "writes": 0})
            persist(dict(state))
            return state
    elif previous_state:
        raise ValueError(f"unsupported partial top-up stage: {previous_state.get('stage')}")
    else:
        selected = select_topup_card(cards, type_title, today=today)
        before = int(selected.get("united_balance_services_count") or 0)
        state = {
            "stage": "balance_updating",
            "type_title": type_title,
            "quantity": int(quantity),
            "card_id": int(selected["id"]),
            "balance_before": before,
            "target_balance": before + int(quantity),
            "expiration_before": selected.get("expiration_date"),
        }
        persist(dict(state))

    api.set_balance(int(state["card_id"]), int(state["target_balance"]))
    writes += 1
    verified = _card_by_id(api.active_subscriptions(phone), int(state["card_id"]))
    balance_after = int(verified.get("united_balance_services_count") or 0)
    if balance_after != int(state["target_balance"]):
        raise ValueError("top-up balance readback mismatch")
    if core._as_date(verified.get("expiration_date")) != core._as_date(state["expiration_before"]):
        raise ValueError("top-up changed the expiration date")
    state.update({"stage": "completed", "balance_after": balance_after, "writes": writes})
    persist(dict(state))
    return state


def _validate_live_configuration(api, entries: list[dict]) -> dict[str, dict]:
    issue_titles = {
        operation["type"]
        for entry in entries
        for operation in (entry.get("operations") or [])
        if operation.get("action") == "issue_new"
    }
    types_by_title: dict[str, list[dict]] = {}
    for item in api.subscription_types():
        types_by_title.setdefault(str(item.get("title") or ""), []).append(item)
    goods: dict[str, dict] = {}
    for title in sorted(issue_titles):
        matches = types_by_title.get(title, [])
        if len(matches) != 1 or not matches[0].get("is_allow_empty_code"):
            raise ValueError(f"subscription type configuration changed: {title}")
        good_id = GOOD_IDS.get(title)
        if not good_id:
            raise ValueError(f"no approved special good for issue type: {title}")
        good = api.good(good_id)
        if (
            str(good.get("title") or "") != title
            or int(good.get("loyalty_abonement_type_id") or 0) != int(matches[0].get("id") or 0)
            or not bool(good.get("loyalty_allow_empty_code"))
            or not isinstance(good.get("cost"), (int, float))
        ):
            raise ValueError(f"special good linkage changed: {title}")
        goods[title] = {**good, "_abonement_type": matches[0]}
    return goods


def _validate_entry_against_sale(entry: dict, sale: dict, package_rules: dict) -> None:
    uc = sale.get("userCourse") or {}
    course = sale.get("course") or {}
    if uc.get("courseID") != course.get("id"):
        raise ValueError("live course relationship changed")
    source_ops, source_errors = dry.planned_operations(str(course.get("name") or "").strip(), uc, package_rules)
    if source_errors:
        raise ValueError("live source operation became invalid")
    source_by_type = {item["type"]: item for item in source_ops}
    for planned in entry.get("operations") or []:
        source = source_by_type.get(planned.get("type"))
        if not source:
            raise ValueError("dry-run operation is absent from live source")
        if (
            int(source.get("quantity") or 0) != int(planned.get("quantity") or 0)
            or str(source.get("family") or "") != str(planned.get("family") or "")
            or source.get("expiration_target") != planned.get("expiration_target")
        ):
            raise ValueError("dry-run operation changed in live source")


def _persist_ledger(ledger: dict) -> None:
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    core._private_json(LEDGER_PATH, ledger)


def run_mass(*, execute: bool, telegram_overrides: dict[str, str] | None = None) -> dict:
    artifact = json.loads(DRY_RUN_PATH.read_text(encoding="utf-8"))
    ff = dry.env_file(dry.FF_SECRET)
    yc_env = dry.env_file(dry.YC_SECRET)
    owner = dry.env_file(dry.OWNER_SECRET)
    mapping = json.loads(dry.MAPPING_PATH.read_text(encoding="utf-8"))
    total, sales, pages = dry.fetch_sales(ff["FF_SALES_API_KEY"], START, END + timedelta(days=1))
    validate_artifact(artifact, start=START, end=END, source_count=total)
    overrides_applied = dry.apply_telegram_overrides(sales, telegram_overrides or {})
    expected_overrides = int(
        (((artifact.get("summary") or {}).get("source") or {}).get("user_confirmed_telegram_overrides_applied") or 0)
    )
    if overrides_applied != expected_overrides:
        raise ValueError("telegram override set differs from approved dry-run")
    sales_by_ref: dict[str, dict] = {}
    for sale in sales:
        reference = dry.sale_ref((sale.get("userCourse") or {}).get("purchaseID"))
        if reference in sales_by_ref:
            raise ValueError("duplicate live sale reference")
        sales_by_ref[reference] = sale
    artifact_refs = {str(entry.get("sale_ref") or "") for entry in artifact.get("entries") or []}
    if set(sales_by_ref) != artifact_refs:
        raise ValueError("live sale references changed after dry-run")

    entries = sorted(
        artifact.get("entries") or [],
        key=lambda item: (str(item.get("purchase_date") or ""), str(item.get("sale_ref") or "")),
    )
    ready = [entry for entry in entries if entry.get("operations") and not entry.get("exceptions")]
    exceptions = [entry for entry in entries if entry.get("exceptions")]
    already_completed = [entry for entry in entries if entry.get("skipped_completed_types")]
    planned_operations = sum(len(entry.get("operations") or []) for entry in ready)
    for entry in ready:
        for operation in entry.get("operations") or []:
            validate_execution_action(str(operation.get("action") or ""))
    preflight = {
        "status": "preflight_ok",
        "period": {"start": START.isoformat(), "end": END.isoformat()},
        "source_sales": total,
        "source_pages": pages,
        "ready_sales": len(ready),
        "planned_operations": planned_operations,
        "planned_issue_new": sum(
            1 for entry in ready for operation in entry["operations"] if operation.get("action") == "issue_new"
        ),
        "planned_topups": sum(
            1 for entry in ready for operation in entry["operations"] if operation.get("action") == "top_up_existing"
        ),
        "exception_sales": len(exceptions),
        "already_completed_sales": len(already_completed),
        "already_completed_operations": sum(len(entry.get("skipped_completed_types") or []) for entry in entries),
        "user_confirmed_telegram_overrides_applied": overrides_applied,
        "execute_requested": execute,
    }
    if not execute:
        return {**preflight, "yclients_writes": 0}

    if LEDGER_PATH.exists():
        ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        if ledger.get("period") != preflight["period"] or int(ledger.get("source_sales") or 0) != total:
            raise ValueError("existing mass ledger belongs to another period or source snapshot")
    else:
        ledger = {
            "version": 1,
            "period": preflight["period"],
            "source_sales": total,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "clients": {},
            "operations": {},
            "failures": {},
        }
        _persist_ledger(ledger)

    expected_ledger_operations_total = expected_operation_total(ledger.get("operations") or {}, ready)
    preflight["expected_ledger_operations_total"] = expected_ledger_operations_total

    company_id = int(yc_env["YCLIENTS_COMPANY_ID"])
    discovery = core.LiveYClients(
        yc_env["YCLIENTS_PARTNER_TOKEN"], owner["YCLIENTS_OWNER_USER_TOKEN"], company_id, 0, "mass-preflight"
    )
    client_rows = discovery.all_clients()
    goods_by_title = _validate_live_configuration(discovery, ready)
    package_rules = mapping.get("consultation_package_rules") or {}
    writes_this_run = 0
    clients_created = 0
    clients_updated = 0
    operations_completed_this_run = 0
    operations_skipped_completed = 0
    failures_this_run: list[dict] = []

    for entry in ready:
        reference = str(entry["sale_ref"])
        sale = sales_by_ref[reference]
        try:
            _validate_entry_against_sale(entry, sale, package_rules)
            source = client_flow.build_source_client(sale)
            api = core.LiveYClients(
                yc_env["YCLIENTS_PARTNER_TOKEN"],
                owner["YCLIENTS_OWNER_USER_TOKEN"],
                company_id,
                0,
                reference,
            )
            api.all_clients = lambda rows=client_rows: list(rows)
            contact_key = _contact_ref(source)
            known_client = ledger["clients"].get(contact_key) or {}
            resolved_client_id = client_flow.resolve_client_match(
                client_rows,
                source["phone"],
                source["email"],
                int(source.get("hint_id") or 0),
            )
            validate_new_client_eligibility(
                str(entry.get("client_state") or ""),
                resolved_client_id,
                int(known_client.get("client_id") or 0) or None,
            )

            def persist_client(state: dict, key=contact_key):
                ledger["clients"][key] = {
                    **merge_client_state(ledger["clients"].get(key) or {}, state),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                _persist_ledger(ledger)

            client_result = client_flow.ensure_client(
                api=api,
                company_id=company_id,
                source=source,
                execute=True,
                persist=persist_client,
            )
            client_writes = int(client_result.get("writes") or 0)
            writes_this_run += client_writes
            if client_writes and client_result.get("original_last_change_date") is None:
                clients_created += 1
            elif client_writes:
                clients_updated += 1
            client_id = int(client_result["client_id"])
            status, payload = api.call("GET", f"/api/v1/client/{company_id}/{client_id}")
            live_client = payload.get("data") if isinstance(payload, dict) else None
            if status != 200 or not isinstance(live_client, dict):
                raise RuntimeError("client cache refresh failed")
            client_rows[:] = [row for row in client_rows if int(row.get("id") or 0) != client_id]
            client_rows.append({key: live_client.get(key) for key in ("id", "name", "phone", "email")})
            clear_resolved_client_failure(ledger, reference)
            _persist_ledger(ledger)

            for operation in entry["operations"]:
                title = str(operation["type"])
                key = operation_key(reference, title)
                previous = ledger["operations"].get(key)
                if previous and previous.get("stage") == "completed":
                    operations_skipped_completed += 1
                    continue

                def persist_operation(state: dict, op_key=key, op=operation):
                    ledger["operations"][op_key] = {
                        **(ledger["operations"].get(op_key) or {}),
                        **state,
                        "sale_ref": reference,
                        "type_title": str(op["type"]),
                        "action": str(op["action"]),
                        "client_id": client_id,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    _persist_ledger(ledger)

                try:
                    if operation["action"] == "issue_new":
                        expiration_text = operation.get("expiration_target")
                        target = date.fromisoformat(str(expiration_text)) if expiration_text else None
                        type_config = goods_by_title[title]["_abonement_type"]
                        configured_period = None
                        if operation.get("family") == "package":
                            if int(type_config.get("united_balance_services_count") or 0) != int(operation["quantity"]):
                                raise ValueError("package configured default balance changed")
                            configured_period = (
                                int(type_config.get("period") or 0),
                                int(type_config.get("period_unit_id") or 0),
                            )
                        result = execute_issue(
                            api=api,
                            phone=source["phone"],
                            good_id=int(goods_by_title[title]["good_id"]),
                            type_title=title,
                            quantity=int(operation["quantity"]),
                            target_expiration=target,
                            previous_state=previous,
                            persist=persist_operation,
                            configured_period=configured_period,
                        )
                    elif operation["action"] == "top_up_existing":
                        result = execute_topup(
                            api=api,
                            phone=source["phone"],
                            type_title=title,
                            quantity=int(operation["quantity"]),
                            previous_state=previous,
                            persist=persist_operation,
                            today=date.today(),
                        )
                    else:
                        raise ValueError("unsupported dry-run action")
                    writes_this_run += int(result.get("writes") or 0)
                    operations_completed_this_run += 1
                    ledger["failures"].pop(key, None)
                    _persist_ledger(ledger)
                except Exception as exc:
                    current = dict(ledger["operations"].get(key) or {})
                    if current.get("stage") == "issuing" and getattr(api, "last_issue_meta", None):
                        current["issue_meta"] = dict(api.last_issue_meta)
                        persist_operation(current)
                    failure = {
                        "sale_ref": reference,
                        "type_title": title,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:250],
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                    ledger["failures"][key] = failure
                    failures_this_run.append(failure)
                    _persist_ledger(ledger)
        except Exception as exc:
            failure = {
                "sale_ref": reference,
                "type_title": None,
                "error_type": type(exc).__name__,
                "message": str(exc)[:250],
                "at": datetime.now(timezone.utc).isoformat(),
            }
            failures_this_run.append(failure)
            ledger["failures"][f"{reference}::__client_or_sale__"] = failure
            _persist_ledger(ledger)

    completed_total = sum(
        1 for state in ledger["operations"].values() if isinstance(state, dict) and state.get("stage") == "completed"
    )
    partial_total = sum(
        1 for state in ledger["operations"].values() if isinstance(state, dict) and state.get("stage") != "completed"
    )
    audit = {
        **preflight,
        "status": final_status(
            failures=failures_this_run,
            completed=completed_total,
            planned=expected_ledger_operations_total,
        ),
        "clients_created_this_run": clients_created,
        "clients_updated_this_run": clients_updated,
        "operations_completed_this_run": operations_completed_this_run,
        "operations_skipped_completed_this_run": operations_skipped_completed,
        "operations_completed_total": completed_total,
        "operations_partial_total": partial_total,
        "failures_this_run": failures_this_run,
        "yclients_writes": writes_this_run,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    core._private_json(AUDIT_PATH, audit)
    return audit


def main() -> None:
    global START, END, LEDGER_PATH, AUDIT_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="inclusive purchaseDate start, YYYY-MM-DD")
    parser.add_argument("--end", help="inclusive purchaseDate end, YYYY-MM-DD")
    parser.add_argument("--telegram-override", action="append", default=[], metavar="EMAIL=@USERNAME")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if (args.start is None) != (args.end is None):
        raise ValueError("--start and --end must be provided together")
    if args.start is not None:
        config = configure_period(date.fromisoformat(args.start), date.fromisoformat(args.end))
        START = config["start"]
        END = config["end"]
        LEDGER_PATH = config["ledger_path"]
        AUDIT_PATH = config["audit_path"]
    telegram_overrides = dry.parse_telegram_overrides(args.telegram_override)
    result = run_mass(execute=args.execute, telegram_overrides=telegram_overrides)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "partial":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
