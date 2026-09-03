#!/usr/bin/env python3
"""Build a read-only FF-sales -> YCLIENTS subscription provisioning dry-run.

No write endpoints are implemented in this script. Output is masked and contains no
API secrets, raw sale IDs, full phones, full emails, or Telegram usernames.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(os.environ.get("YCLIENTS_OPS_HOME", Path(__file__).resolve().parents[1]))
SECRETS_DIR = Path(os.environ.get("YCLIENTS_OPS_SECRETS_DIR", ROOT / "secrets"))
FF_SECRET = Path(os.environ.get("FF_SALES_SECRET_FILE", SECRETS_DIR / "ff_sales.env"))
YC_SECRET = Path(os.environ.get("YCLIENTS_SECRET_FILE", SECRETS_DIR / "yclients.env"))
OWNER_SECRET = Path(os.environ.get("YCLIENTS_OWNER_SECRET_FILE", SECRETS_DIR / "yclients_owner.env"))
MAPPING_PATH = Path(os.environ.get("YCLIENTS_MAPPING_FILE", ROOT / "app/course_subscription_mapping.json"))
OUT_JSON = ROOT / "runtime/subscription_dry_run_latest.json"
OUT_MD = ROOT / "runtime/subscription_dry_run_latest.md"
FF_ENDPOINT = "https://ff-bot.com/ffapi/sales/list"
YC_BASE = "https://api.yclients.com"
ALLOWED_TYPES = {
    "Индивидуальная консультация",
    "Групповая консультация",
    "Консультации (3 шт.)",
    "Консультации (5 шт.)",
    "Консультации (8 шт.)",
}


def env_file(path: Path) -> dict[str, str]:
    return {
        k.strip(): v.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
        for k, v in [line.split("=", 1)]
    }


def private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)


def day(value) -> date | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def norm_phone(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def norm_email(value) -> str:
    return str(value or "").strip().lower()


def parse_telegram_overrides(values: list[str] | None) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in values or []:
        if "=" not in str(raw):
            raise ValueError("telegram override must be EMAIL=@USERNAME")
        email_raw, username_raw = str(raw).split("=", 1)
        email = norm_email(email_raw)
        username = username_raw.strip().lstrip("@")
        if "@" not in email or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            raise ValueError("invalid telegram override")
        if email in overrides and overrides[email] != username:
            raise ValueError("conflicting telegram overrides for one email")
        overrides[email] = username
    return overrides


def apply_telegram_overrides(sales: list[dict], overrides: dict[str, str]) -> int:
    applied: set[str] = set()
    for sale in sales:
        user = sale.get("user") if isinstance(sale.get("user"), dict) else None
        if user is None:
            continue
        email = norm_email(user.get("email"))
        username = overrides.get(email)
        if not username:
            continue
        current = str(user.get("tgUsername") or user.get("telegramUsername") or "").strip().lstrip("@")
        if current and current != username:
            raise ValueError(f"confirmed telegram override conflicts with source for {mask_email(email)}")
        user["tgUsername"] = username
        applied.add(email)
    missing = sorted(set(overrides) - applied)
    if missing:
        raise ValueError("telegram override email not found in selected sales: " + ", ".join(mask_email(x) for x in missing))
    return len(applied)


def mask_phone(value) -> str:
    p = norm_phone(value)
    if len(p) < 7:
        return "<missing>" if not p else "***"
    return "+" + p[:2] + "***" + p[-4:]


def mask_email(value) -> str:
    e = norm_email(value)
    if "@" not in e:
        return "<missing>" if not e else "***"
    local, domain = e.split("@", 1)
    left = (local[:1] + "***") if local else "***"
    parts = domain.split(".")
    masked_domain = (parts[0][:1] + "***") if parts and parts[0] else "***"
    suffix = "." + parts[-1] if len(parts) > 1 else ""
    return left + "@" + masked_domain + suffix


def mask_text(value, keep=1) -> str:
    s = str(value or "").strip().lstrip("@")
    if not s:
        return "<missing>"
    return s[:keep] + "***"


def sale_ref(value) -> str:
    return hashlib.sha256(str(value or "<missing>").encode("utf-8")).hexdigest()[:10]


def ff_post(api_key: str, payload: dict) -> dict:
    req = urllib.request.Request(
        FF_ENDPOINT,
        data=json.dumps({"apiKey": api_key, **payload}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"FF API HTTP {response.status}")
        return json.load(response)


def fetch_sales(api_key: str, start: date, end_exclusive: date) -> tuple[int, list[dict], int]:
    filters = {"purchaseDateFrom": start.isoformat(), "purchaseDateTo": end_exclusive.isoformat()}
    first = ff_post(api_key, {**filters, "page": 1, "perPage": 50})
    total = int(first.get("total") or 0)
    per_page = int(first.get("perPage") or 50)
    pages = (total + per_page - 1) // per_page
    rows = list(first.get("sales") or [])
    for page in range(2, pages + 1):
        time.sleep(0.15)
        rows.extend(ff_post(api_key, {**filters, "page": page, "perPage": per_page}).get("sales") or [])
    if len(rows) != total:
        raise RuntimeError("FF API pagination incomplete")
    return total, rows, pages


class YClients:
    def __init__(self, partner: str, user: str, company_id: str):
        self.company_id = company_id
        self.headers = {
            "Authorization": f"Bearer {partner}, User {user}",
            "Accept": "application/vnd.yclients.v2+json",
            "Content-Type": "application/json",
            "User-Agent": "Hermes-YCLIENTS-DryRun/1.0",
        }

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(YC_BASE + path, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read()
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"YCLIENTS HTTP {response.status}")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            # Never propagate raw bodies because they can contain client data.
            raise RuntimeError(f"YCLIENTS HTTP {exc.code} for {method} {path.split('?')[0]}") from None

    def clients(self) -> tuple[list[dict], int, int]:
        rows: list[dict] = []
        seen: set[str] = set()
        total_expected = None
        pages = 0
        for page in range(1, 501):
            payload = self.call(
                "POST",
                f"/api/v1/company/{self.company_id}/clients/search",
                {
                    "page": page,
                    "page_size": 200,
                    "fields": ["id", "name", "phone", "email"],
                    "order_by": "id",
                    "order_by_direction": "ASC",
                },
            )
            batch = payload.get("data") if isinstance(payload.get("data"), list) else []
            pages += 1
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if total_expected is None and meta.get("total_count") is not None:
                total_expected = int(meta["total_count"])
            before = len(seen)
            for item in batch:
                ident = str(item.get("id"))
                if ident not in seen:
                    seen.add(ident)
                    rows.append(item)
            if batch and len(seen) == before:
                raise RuntimeError("YCLIENTS client pagination repeated a page")
            if len(batch) < 200:
                break
        else:
            raise RuntimeError("YCLIENTS client pagination safety limit reached")
        if total_expected is not None and len(rows) != total_expected:
            raise RuntimeError("YCLIENTS client pagination incomplete")
        return rows, total_expected if total_expected is not None else len(rows), pages

    def subscription_types(self) -> list[dict]:
        q = urllib.parse.urlencode({"page": 1, "page_size": 100})
        payload = self.call("GET", f"/api/v1/company/{self.company_id}/loyalty/abonement_types/search?{q}")
        return payload.get("data") if isinstance(payload.get("data"), list) else []

    def active_subscriptions(self, phone: str) -> list[dict]:
        q = urllib.parse.urlencode({"company_id": self.company_id, "phone": phone})
        payload = self.call("GET", f"/api/v1/loyalty/abonements/?{q}")
        return payload.get("data") if isinstance(payload.get("data"), list) else []


def planned_operations(course_name: str, uc: dict, package_rules: dict) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    ops: list[dict] = []
    if not course_name:
        return [], ["missing_course_name"]
    if course_name in package_rules:
        rule = package_rules[course_name]
        ops.append({
            "type": rule["target_subscription_type"],
            "quantity": int(rule["quantity"]),
            "family": "package",
            "expiration_target": None,
        })
        return ops, errors
    try:
        personal = int(uc.get("kolPersonalConsultations") or 0)
        group = int(uc.get("kolGroupConsultations") or 0)
    except (TypeError, ValueError):
        return [], ["invalid_consultation_quantity"]
    expiration = day(uc.get("gracePeriodEndDate"))
    if personal > 0:
        ops.append({"type": "Индивидуальная консультация", "quantity": personal, "family": "ordinary", "expiration_target": expiration.isoformat() if expiration else None})
    if group > 0:
        ops.append({"type": "Групповая консультация", "quantity": group, "family": "ordinary", "expiration_target": expiration.isoformat() if expiration else None})
    if not ops:
        errors.append("ordinary_course_has_zero_consultations")
    if ops and (expiration is None or expiration <= date.today()):
        errors.append("ordinary_course_missing_or_nonfuture_grace_period_end")
    return ops, errors


def existing_client_policy(*, active_card_count: int) -> str:
    if int(active_card_count) > 0:
        return "existing_client_has_subscription_skip_by_policy"
    return "existing_client_requires_full_history_manual_eligibility_review"


def summarize_planned_actions(entries: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    actions: Counter = Counter()
    typed: Counter = Counter()
    for entry in entries:
        operations = entry.get("operations") or []
        if entry.get("exceptions") or not operations:
            continue
        if entry.get("client_state") == "new":
            actions["create_client"] += 1
        for operation in operations:
            action = str(operation.get("action") or "")
            title = str(operation.get("type") or "")
            actions[action] += 1
            actions["set_balance"] += 1
            if action == "issue_new" and operation.get("family") == "ordinary":
                actions["set_period"] += 1
            typed[f"{title}|{action}"] += 1
    return dict(actions), dict(typed)


def completed_operation_keys(ledgers: list[dict]) -> set[tuple[str, str]]:
    completed: set[tuple[str, str]] = set()
    rolled_back: set[tuple[str, str]] = set()
    for ledger in ledgers:
        top_ref = str(ledger.get("sale_ref") or "")
        operations = ledger.get("operations") if isinstance(ledger.get("operations"), dict) else {}
        for key, state in operations.items():
            if not isinstance(state, dict) or state.get("stage") != "completed":
                continue
            operation_ref = str(state.get("sale_ref") or top_ref)
            type_title = str(state.get("type_title") or "")
            if not type_title:
                key_text = str(key)
                type_title = key_text.split("::", 1)[1] if "::" in key_text else key_text
            if not operation_ref and "::" in str(key):
                operation_ref = str(key).split("::", 1)[0]
            if operation_ref and type_title:
                operation_key = (operation_ref, type_title)
                if state.get("source_action") == "top_up_existing":
                    rolled_back.add(operation_key)
                else:
                    completed.add(operation_key)
    return completed - rolled_back


def partition_completed_operations(sale_reference: str, operations: list[dict],
                                   completed: set[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    pending = []
    skipped = []
    for operation in operations:
        title = str(operation.get("type") or "")
        if (sale_reference, title) in completed:
            skipped.append(title)
        else:
            pending.append(operation)
    return pending, skipped


def parse_period(start_text: str | None, end_text: str | None, *, today: date | None = None) -> tuple[date, date, date]:
    current = today or date.today()
    if (start_text is None) != (end_text is None):
        raise ValueError("start and end must be provided together")
    if start_text is None:
        start = current - timedelta(days=13)
        end_inclusive = current
    else:
        start = date.fromisoformat(start_text)
        end_inclusive = date.fromisoformat(end_text)
    if start > end_inclusive:
        raise ValueError("start date must not be after end date")
    if end_inclusive > current:
        raise ValueError("period end must not be in the future")
    return start, end_inclusive, end_inclusive + timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="inclusive purchaseDate start, YYYY-MM-DD")
    parser.add_argument("--end", help="inclusive purchaseDate end, YYYY-MM-DD")
    parser.add_argument(
        "--telegram-override",
        action="append",
        default=[],
        metavar="EMAIL=@USERNAME",
        help="user-confirmed Telegram username for an exact source email",
    )
    args = parser.parse_args()
    ff = env_file(FF_SECRET)
    yc_env = env_file(YC_SECRET)
    owner = env_file(OWNER_SECRET)
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    ledger_paths = [ROOT / "runtime/subscription_pilot_ledger.json"]
    ledger_paths.extend(sorted((ROOT / "runtime/subscription_pilots").glob("*_subscriptions.json")))
    ledger_paths.extend(sorted((ROOT / "runtime/mass_subscription_ledgers").glob("*.json")))
    ledger_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in ledger_paths if path.exists()]
    completed_keys = completed_operation_keys(ledger_payloads)
    api_key = ff.get("FF_SALES_API_KEY")
    partner = yc_env.get("YCLIENTS_PARTNER_TOKEN")
    owner_token = owner.get("YCLIENTS_OWNER_USER_TOKEN")
    company_id = yc_env.get("YCLIENTS_COMPANY_ID")
    if not all((api_key, partner, owner_token, company_id)):
        raise SystemExit("required secrets unavailable")

    today = date.today()
    start, end_inclusive, end_exclusive = parse_period(args.start, args.end, today=today)
    declared_total, sales, sales_pages = fetch_sales(api_key, start, end_exclusive)
    telegram_overrides = parse_telegram_overrides(args.telegram_override)
    telegram_overrides_applied = apply_telegram_overrides(sales, telegram_overrides)

    yc = YClients(partner, owner_token, company_id)
    clients, clients_total, client_pages = yc.clients()
    types = yc.subscription_types()
    type_by_title: dict[str, list[dict]] = {}
    for item in types:
        type_by_title.setdefault(str(item.get("title") or ""), []).append(item)
    type_config_errors = []
    for title in sorted(ALLOWED_TYPES):
        if len(type_by_title.get(title, [])) != 1:
            type_config_errors.append({"type": title, "configured_matches": len(type_by_title.get(title, []))})

    by_id = {str(x.get("id")): x for x in clients if x.get("id") is not None}
    by_phone: dict[str, list[dict]] = {}
    by_email: dict[str, list[dict]] = {}
    for client in clients:
        phone = norm_phone(client.get("phone"))
        email = norm_email(client.get("email"))
        if phone:
            by_phone.setdefault(phone, []).append(client)
        if email:
            by_email.setdefault(email, []).append(client)

    active_cache: dict[str, list[dict]] = {}
    package_rules = mapping.get("consultation_package_rules") or {}
    entries: list[dict] = []
    action_counts = Counter()
    exception_counts = Counter()
    type_action_counts = Counter()
    ready_new = []

    for sale in sales:
        uc = sale.get("userCourse") or {}
        user = sale.get("user") or {}
        course = sale.get("course") or {}
        pid = uc.get("purchaseID")
        current_sale_ref = sale_ref(pid)
        course_name = str(course.get("name") or "").strip()
        phone = norm_phone(user.get("phone"))
        email = norm_email(user.get("email"))
        name = str(user.get("name") or user.get("tgFirstName") or "").strip()
        telegram = str(user.get("tgUsername") or user.get("telegramUsername") or "").strip().lstrip("@")
        errors: list[str] = []
        if not pid:
            errors.append("missing_purchase_id")
        if uc.get("courseID") != course.get("id"):
            errors.append("course_relationship_mismatch")
        if not phone:
            errors.append("missing_phone")
        if not email:
            errors.append("missing_email")
        if not name:
            errors.append("missing_name")
        if not telegram:
            errors.append("missing_telegram_username")

        ops, op_errors = planned_operations(course_name, uc, package_rules)
        errors.extend(op_errors)
        ops, skipped_completed_types = partition_completed_operations(current_sale_ref, ops, completed_keys)
        for op in ops:
            if op["type"] not in ALLOWED_TYPES:
                errors.append("target_type_not_allowlisted")
            if len(type_by_title.get(op["type"], [])) != 1:
                errors.append("target_type_not_uniquely_configured")

        hint = user.get("yclientsClientID")
        hint_present = str(hint or "").strip() not in ("", "0")
        hinted = by_id.get(str(hint)) if hint_present else None
        contact_candidates = {
            str(x.get("id")): x
            for x in (by_phone.get(phone, []) + by_email.get(email, []))
            if x.get("id") is not None
        }
        matched = None
        client_state = "new"
        if hint_present:
            if hinted is None:
                errors.append("source_yclients_client_id_not_found")
                client_state = "conflict"
            else:
                hint_phone = norm_phone(hinted.get("phone"))
                hint_email = norm_email(hinted.get("email"))
                if hint_phone != phone or hint_email != email:
                    errors.append("source_yclients_client_id_contact_conflict")
                    client_state = "conflict"
                else:
                    matched = hinted
                    client_state = "existing"
        elif len(contact_candidates) == 1:
            matched = next(iter(contact_candidates.values()))
            mphone = norm_phone(matched.get("phone"))
            memail = norm_email(matched.get("email"))
            if mphone != phone or memail != email:
                errors.append("single_contact_match_has_other_contact_conflict")
                client_state = "conflict"
            else:
                client_state = "existing"
        elif len(contact_candidates) > 1:
            errors.append("multiple_yclients_client_matches")
            client_state = "ambiguous"

        planned: list[dict] = []
        if not errors and client_state == "new":
            action_counts["create_client"] += 1
            for op in ops:
                plan = {
                    **op,
                    "action": "issue_new",
                    "set_balance_absolute": op["quantity"],
                    "set_period_after_issue": op["family"] == "ordinary",
                }
                planned.append(plan)
                action_counts["issue_new"] += 1
                action_counts["set_balance"] += 1
                if plan["set_period_after_issue"]:
                    action_counts["set_period"] += 1
                type_action_counts[f"{op['type']}|issue_new"] += 1
        elif not errors and client_state == "existing" and matched and ops:
            lookup_phone = norm_phone(matched.get("phone"))
            if lookup_phone not in active_cache:
                active_cache[lookup_phone] = yc.active_subscriptions(lookup_phone)
            cards = active_cache[lookup_phone]
            errors.append(existing_client_policy(active_card_count=len(cards)))

        if errors:
            planned = []
            for reason in sorted(set(errors)):
                exception_counts[reason] += 1

        entry = {
            "sale_ref": current_sale_ref,
            "purchase_date": day(uc.get("purchaseDate")).isoformat() if day(uc.get("purchaseDate")) else None,
            "course": course_name or "<missing>",
            "source": {
                "name_masked": mask_text(name),
                "telegram_masked": mask_text(telegram),
                "phone_masked": mask_phone(phone),
                "email_masked": mask_email(email),
            },
            "client_state": client_state,
            "operation_count": len(planned),
            "operations": planned,
            "skipped_completed_types": skipped_completed_types,
            "exceptions": sorted(set(errors)),
        }
        entries.append(entry)
        if client_state == "new" and planned and not errors:
            ready_new.append(entry)

    # Deterministic pilot preference: one ordinary operation on a new client, then any one-operation new client.
    ordinary_single = [x for x in ready_new if len(x["operations"]) == 1 and x["operations"][0]["family"] == "ordinary"]
    any_single = [x for x in ready_new if len(x["operations"]) == 1]
    candidates = ordinary_single or any_single or ready_new
    pilot = sorted(candidates, key=lambda x: (x.get("purchase_date") or "", x["sale_ref"]))[0] if candidates else None
    action_counts, type_action_counts = summarize_planned_actions(entries)

    summary = {
        "generated_date": today.isoformat(),
        "dry_run_only": True,
        "yclients_write_requests_performed": 0,
        "period": {
            "purchaseDateFrom_inclusive": start.isoformat(),
            "purchaseDateThrough_inclusive": end_inclusive.isoformat(),
            "purchaseDateTo_exclusive_sent": end_exclusive.isoformat(),
        },
        "source": {
            "declared_total": declared_total,
            "rows_collected": len(sales),
            "pages": sales_pages,
            "unique_purchase_ids": len({str((x.get("userCourse") or {}).get("purchaseID")) for x in sales}),
            "user_confirmed_telegram_overrides_applied": telegram_overrides_applied,
        },
        "yclients": {
            "clients_total": clients_total,
            "client_pages": client_pages,
            "configured_subscription_types": len(types),
            "allowlisted_type_configuration_errors": type_config_errors,
            "active_subscription_clients_queried": len(active_cache),
        },
        "planning": {
            "ready_sales": sum(1 for x in entries if x["operations"] and not x["exceptions"]),
            "already_completed_sales": sum(1 for x in entries if x["skipped_completed_types"] and not x["operations"]),
            "already_completed_operations": sum(len(x["skipped_completed_types"]) for x in entries),
            "ready_new_client_sales": len(ready_new),
            "exception_sales": sum(1 for x in entries if x["exceptions"]),
            "client_state_counts": dict(Counter(x["client_state"] for x in entries)),
            "action_counts": dict(action_counts),
            "type_action_counts": dict(type_action_counts),
            "exception_counts": dict(exception_counts),
        },
        "pilot_candidate": pilot,
    }
    artifact = {"summary": summary, "entries": entries}
    private_write(OUT_JSON, json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")

    lines = [
        "# YCLIENTS subscription provisioning dry-run",
        "",
        f"- Period: {start.isoformat()}–{end_inclusive.isoformat()} inclusive",
        f"- Source sales: {len(sales)}",
        f"- YCLIENTS clients scanned: {clients_total}",
        f"- Ready sales: {summary['planning']['ready_sales']}",
        f"- Already completed sales: {summary['planning']['already_completed_sales']}",
        f"- Already completed operations: {summary['planning']['already_completed_operations']}",
        f"- New-client ready sales: {summary['planning']['ready_new_client_sales']}",
        f"- Exception sales: {summary['planning']['exception_sales']}",
        "- YCLIENTS writes performed: 0",
        "",
        "## Planned actions",
        "",
    ]
    for key, value in sorted(action_counts.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Exceptions", ""])
    if exception_counts:
        for key, value in sorted(exception_counts.items()):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    lines.extend(["", "## Pilot candidate", ""])
    if pilot:
        op = pilot["operations"][0]
        lines.extend([
            f"- Sale reference: `{pilot['sale_ref']}`",
            f"- Purchase date: {pilot['purchase_date']}",
            f"- Course: {pilot['course']}",
            f"- Client: {pilot['source']['name_masked']} / @{pilot['source']['telegram_masked']}",
            f"- Contact: {pilot['source']['phone_masked']} / {pilot['source']['email_masked']}",
            f"- Action: create client, issue `{op['type']}`, set exact balance `{op['set_balance_absolute']}`",
            f"- Expiration target: {op.get('expiration_target') or 'configured type default'}",
        ])
    else:
        lines.append("- No safe candidate found.")
    private_write(OUT_MD, "\n".join(lines) + "\n")

    # Terminal output is aggregate-only.
    print(json.dumps({
        "artifact_json": str(OUT_JSON),
        "artifact_md": str(OUT_MD),
        "period": summary["period"],
        "source": summary["source"],
        "yclients": summary["yclients"],
        "planning": summary["planning"],
        "pilot_candidate_found": pilot is not None,
        "pilot_candidate_summary": ({
            "sale_ref": pilot["sale_ref"],
            "purchase_date": pilot["purchase_date"],
            "course": pilot["course"],
            "client_state": pilot["client_state"],
            "operation_count": pilot["operation_count"],
            "operations": pilot["operations"],
            "source_masked": pilot["source"],
        } if pilot else None),
        "yclients_write_requests_performed": 0,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
