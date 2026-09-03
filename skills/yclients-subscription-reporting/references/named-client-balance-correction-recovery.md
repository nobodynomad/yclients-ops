# Named-client balance corrections and interrupted issuance recovery

Use this reference for a one-client request that combines a new abonement with a balance reduction on an existing card.

## Command semantics

For this user's YCLIENTS vocabulary:

- `спиши N групп`, `забери N групп`, and `уменьши N групп` mean a **balance decrease**, not an attendance/write-off event.
- Read the exact target card and current balance immediately before the write.
- Set `target_balance = current_balance - N`; fail closed if the current balance differs from the manifest.
- Use the abonement setter:

```text
POST /api/v1/chain/{chain_id}/loyalty/abonements/{card_id}/set_balance
{"united_balance_services_count": target_balance, "services_balance_count": []}
```

- Do not use the loyalty-card manual transaction route for an abonement ID. That route is a different resource:

```text
POST /api/v1/company/{company_id}/loyalty/cards/{card_id}/manual_transaction
```

A 404 there with an abonement ID is a resource/type mismatch, not permission to retry blindly or to reinterpret the request as attendance.

## Pre-write evidence

Persist an immutable manifest containing at least:

- exact client ID and exact email/Telegram/phone evidence;
- exact abonement card ID and title;
- `goods_transaction_id` and its verified `transaction.client_id` / `good_id`;
- balance before, delta, target balance;
- expiration before;
- operation kind: `absolute_balance_correction`, `is_attendance_writeoff: false`.

For new-card issuance, also persist the approved good ID/type linkage and the pre-write card IDs. Scan the full abonement history for the target family and reject any existing client-owned individual card before creating a new one.

## Write and verification gates

1. Re-read identity and the exact card immediately before mutation.
2. Create the new abonement only through its linked inventory good and read back the new card through the full-network abonement list plus goods transaction ownership.
3. Set the final new-card balance explicitly; do not assume the default good quantity equals the requested quantity.
4. Apply a balance correction only to the allowlisted existing card.
5. Re-read each touched card: exact ID, title, balance, status, expiration, and ownership.
6. Verify that protected cards and expiration dates did not change.
7. Rerun the executor and require `writes: 0`.

## Timeout recovery

A side-effecting command can time out after writing its ledger stage but before finishing all writes. Treat the effect as unknown:

1. Read the ledger; an `issuing` stage is not proof that no card was created.
2. Do **not** rerun the issuance command.
3. Scan the full network by exact card family, then follow each candidate's `goods_transaction_id` to the goods transaction and require the exact client ID and approved good ID.
4. If one newly created card exists with the default balance, update only that card to the requested final balance with `set_balance`.
5. If no card exists, resume from the saved manifest only after a fresh preflight; if multiple candidates or an unexpected state exists, stop.
6. Save a separate recovery stage and verify it with a zero-write recovery rerun.

Example recovery state:

```json
{
  "stage": "completed",
  "client_id": 421990077,
  "card_id": 22851651,
  "good_id": 36892736,
  "balance_before": 12,
  "balance_target": 1,
  "transaction_id": 1795845114,
  "writes": 1
}
```

The numeric IDs above are an example of the evidence shape from one recovery, not reusable target values.

## Masked-phone handling

Client-search results may expose a masked phone. Never reconstruct or guess the hidden digits. Prefer exact email → client ID plus card/transaction ownership evidence. A normalized masked value may be used for a read only when a live endpoint has already demonstrated that it resolves to the same exact client; it is not an identity substitute and must not be expanded into a fabricated full phone.