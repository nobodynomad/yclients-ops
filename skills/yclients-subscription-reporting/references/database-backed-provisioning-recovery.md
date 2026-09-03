# Database-backed package issuance and delayed-card recovery

Use this reference when a client is absent from YCLIENTS by exact email but the authorized sales database contains a purchase.

## Source-to-YCLIENTS mapping

- Query the FF sales API by exact normalized email and require exactly one matching sale.
- Preserve `purchaseID` and derive a stable sale reference before any write.
- Package courses map as follows:
  - `Пакет консультаций 3` → `Консультации (3 шт.)`
  - `Пакет консультаций 5` → `Консультации (5 шт.)`
  - `Пакет консультаций 8` → `Консультации (8 шт.)`
- Use the approved live special good IDs and verify `good.title == type.title` plus `good.loyalty_abonement_type_id == type.id`.
- Package cards use the subscription type's configured validity. A same-day or expired source `gracePeriodEndDate` does not require setting package validity.

## New client path

1. Build the client source from non-empty name, exact Telegram username, normalized phone, and exact email.
2. Resolve by the intersection of exact email and normalized phone. If no match exists, create with `POST /api/v1/clients/{company_id}` using only `name`, `phone`, and `email`.
3. Read back `/api/v1/client/{company_id}/{client_id}` and compare all three fields before issuing.
4. A newly created client has no prior YCLIENTS subscription history; still prove the issued card later via its transaction.

## Delayed card discovery

Card listing windows must be computed at runtime. A hard-coded `created_before` can exclude a transaction/card created after the cutoff even though the sale succeeded. On a partial run:

1. Do not issue again.
2. Read the ledger stage and transaction metadata.
3. Fetch `GET /api/v1/storage_operations/goods_transactions/{company_id}/{transaction_id}`.
4. Require exact `transaction.client_id` and `transaction.good_id`.
5. Widen the card-list window and find the card by `goods_transaction_id`.
6. Read the exact card by `abonements_ids`, then set only the missing balance if needed.
7. Verify balance, status, expiry, card→transaction→client/good linkage, and run a zero-write rerun.

If the first execution created a client and transaction but card discovery failed, the recovery may legitimately record the already-performed client/sale writes separately from the balance/readback step. Never re-create the client or sale.

## Masked phone fallback

YCLIENTS client-list and phone-level subscription endpoints can expose only a masked phone or return no card for that masked value. Do not invent the full number. Use exact client IDs, exact card IDs, and goods-transaction ownership proofs. A transaction readback may contain an unmasked contact, but it is verification evidence only; do not overwrite the source contact automatically.

## Verification checklist

- Exact source sale: one match, stable purchase ID/ref.
- Exact client: created/read back or matched by email+phone intersection.
- Package type/good linkage: verified before write.
- Transaction: client ID and good ID exact.
- Card: exact card ID, expected package title, expected balance, status, expiry.
- Rerun: `0 writes`; no duplicate sale or client.
