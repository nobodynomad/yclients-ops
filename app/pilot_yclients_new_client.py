#!/usr/bin/env python3
"""Safe one-sale pilot for creating/synchronizing a client before subscription issuance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pilot_yclients_subscription as core


ROOT = Path(os.environ.get("YCLIENTS_OPS_HOME", Path(__file__).resolve().parents[1]))
BASE = ROOT / "runtime/subscription_pilots"


def norm_phone(value) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def yclients_safe_name(value: str) -> str:
    # The client API stores non-BMP symbols (for example emoji) as `?`.
    # Normalize before both write and readback comparison so recovery is exact.
    return "".join(char if ord(char) <= 0xFFFF else "?" for char in str(value or ""))


def build_source_client(sale: dict) -> dict:
    user = sale.get("user") or {}
    first_name = str(user.get("name") or user.get("tgFirstName") or "").strip()
    telegram = str(user.get("tgUsername") or "").strip().lstrip("@")
    phone = norm_phone(user.get("phone"))
    email = str(user.get("email") or "").strip().lower()
    if not all((first_name, telegram, phone, email)):
        raise ValueError("source client contacts are incomplete")
    return {
        "name": yclients_safe_name(f"{first_name} @{telegram}"),
        "phone": phone,
        "email": email,
        "hint_id": int(user.get("yclientsClientID") or 0),
    }


def resolve_client_match(rows: list[dict], phone: str, email: str, hint_id: int) -> int | None:
    by_id = {int(row["id"]): row for row in rows if row.get("id") is not None}
    email_ids = {
        identifier for identifier, row in by_id.items()
        if str(row.get("email") or "").strip().lower() == email
    }
    phone_ids = {
        identifier for identifier, row in by_id.items()
        if norm_phone(row.get("phone")) == phone
    }
    if hint_id:
        if hint_id not in by_id or hint_id not in email_ids or hint_id not in phone_ids:
            raise ValueError("source YCLIENTS client hint conflicts with exact contacts")
    candidates = email_ids | phone_ids
    if not candidates:
        if hint_id:
            raise ValueError("source YCLIENTS client hint is not present in the branch")
        return None
    if len(candidates) != 1 or email_ids != phone_ids:
        raise ValueError("phone/email client match conflict")
    client_id = next(iter(candidates))
    if hint_id and client_id != hint_id:
        raise ValueError("source YCLIENTS client hint conflicts with resolved client")
    return client_id


def _client_data(api, company_id: int, client_id: int) -> dict:
    status, payload = api.call("GET", f"/api/v1/client/{company_id}/{client_id}")
    data = payload.get("data") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError("client readback failed")
    return data


def _verify_client(data: dict, source: dict) -> None:
    if (
        str(data.get("name") or "") != source["name"]
        or norm_phone(data.get("phone")) != source["phone"]
        or str(data.get("email") or "").strip().lower() != source["email"]
    ):
        raise RuntimeError("client contact readback mismatch")


def ensure_client(*, api, company_id: int, source: dict, execute: bool, persist) -> dict:
    client_id = resolve_client_match(
        api.all_clients(), source["phone"], source["email"], int(source.get("hint_id") or 0)
    )
    writes = 0
    original_last_change_date = None
    if client_id is None:
        if not execute:
            return {"action": "create", "client_id": None, "writes": 0}
        persist({"stage": "creating_client"})
        body = {key: source[key] for key in ("name", "phone", "email")}
        status, payload = api.call("POST", f"/api/v1/clients/{company_id}", body)
        data = payload.get("data") if isinstance(payload, dict) else None
        client_id = int((data or {}).get("id") or 0)
        if status not in (200, 201) or not client_id:
            raise RuntimeError("client creation did not return an id")
        writes += 1
        api.client_id = client_id
        persist({
            "stage": "client_created",
            "client_id": client_id,
            "writes": writes,
            "original_last_change_date": None,
        })
    else:
        api.client_id = client_id
        before = _client_data(api, company_id, client_id)
        original_last_change_date = before.get("last_change_date")
        if (
            norm_phone(before.get("phone")) != source["phone"]
            or str(before.get("email") or "").strip().lower() != source["email"]
        ):
            raise ValueError("live client contact conflict")
        needs_sync = any((
            str(before.get("name") or "") != source["name"],
            norm_phone(before.get("phone")) != source["phone"],
            str(before.get("email") or "").strip().lower() != source["email"],
        ))
        if needs_sync:
            if not execute:
                return {
                    "action": "sync",
                    "client_id": client_id,
                    "writes": 0,
                    "original_last_change_date": original_last_change_date,
                }
            persist({
                "stage": "updating_client",
                "client_id": client_id,
                "original_last_change_date": original_last_change_date,
            })
            body = {key: source[key] for key in ("name", "phone", "email")}
            status, _ = api.call("PUT", f"/api/v1/client/{company_id}/{client_id}", body)
            if status != 200:
                raise RuntimeError("client update failed")
            writes += 1

    verified = _client_data(api, company_id, client_id)
    _verify_client(verified, source)
    result = {
        "stage": "client_verified",
        "client_id": client_id,
        "writes": writes,
        "original_last_change_date": original_last_change_date,
        "name_verified": True,
        "phone_verified": True,
        "email_verified": True,
    }
    persist(result)
    return result


def _ledger_persist(path: Path, envelope: dict):
    def persist(state: dict) -> None:
        envelope["client"] = {**(envelope.get("client") or {}), **state}
        envelope["updated_at"] = datetime.now(timezone.utc).isoformat()
        core._private_json(path, envelope)
    return persist


def run(*, email: str, expected_ref: str, execute: bool) -> dict:
    sale = core._fetch_approved_sale(email, expected_ref)
    source = build_source_client(sale)
    yc_env = core._env_file(core.YC_SECRET)
    owner = core._env_file(core.OWNER_SECRET)
    company_id = int(yc_env["YCLIENTS_COMPANY_ID"])
    client_ledger_path = BASE / f"{expected_ref}_client.json"
    envelope = (
        json.loads(client_ledger_path.read_text(encoding="utf-8"))
        if client_ledger_path.exists()
        else {"version": 1, "sale_ref": expected_ref, "created_at": datetime.now(timezone.utc).isoformat()}
    )
    if envelope.get("sale_ref") != expected_ref:
        raise ValueError("client ledger belongs to another sale")
    api = core.LiveYClients(
        yc_env["YCLIENTS_PARTNER_TOKEN"],
        owner["YCLIENTS_OWNER_USER_TOKEN"],
        company_id,
        int((envelope.get("client") or {}).get("client_id") or 0),
        expected_ref,
    )
    client_result = ensure_client(
        api=api,
        company_id=company_id,
        source=source,
        execute=execute,
        persist=_ledger_persist(client_ledger_path, envelope),
    )
    if not execute:
        _, _, plans = core._plans_from_sale(sale)
        return {
            "status": "preflight_ok",
            "sale_ref": expected_ref,
            "client_action": client_result["action"],
            "plans": [
                {
                    "type_title": plan["type_title"],
                    "quantity": plan["quantity"],
                    "target_expiration": plan["target"].isoformat(),
                }
                for plan in plans
            ],
            "yclients_writes": 0,
        }

    client_id = int(client_result["client_id"])
    BASE.mkdir(parents=True, exist_ok=True)
    core.LEDGER_PATH = BASE / f"{expected_ref}_subscriptions.json"
    core.AUDIT_PATH = BASE / f"{expected_ref}_subscriptions_audit.json"
    subscription_result = core.run_pilot(
        email=email,
        approved_client_id=client_id,
        expected_ref=expected_ref,
        execute=True,
    )
    audit = {
        "status": "completed",
        "sale_ref": expected_ref,
        "client": client_result,
        "subscriptions": subscription_result,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    core._private_json(BASE / f"{expected_ref}_audit.json", audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--expected-sale-ref", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(email=args.email, expected_ref=args.expected_sale_ref, execute=args.execute), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
