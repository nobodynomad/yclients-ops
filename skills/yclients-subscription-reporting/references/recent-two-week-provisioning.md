# Recent purchase-date provisioning

Use this reference for requests such as «добавь абонементы за последние N недель, только тем, у кого их нет».

## Period semantics

1. Read the actual current system date before choosing the interval.
2. Interpret “last N weeks” as **7×N inclusive calendar dates**: `start = today - (7*N - 1) days`, `end = today` (for three weeks, `today - 20 days` through `today`).
3. Filter by `userCourse.purchaseDate`, not course start date or activation date.
4. Send the FF API upper bound as an exclusive date: `purchaseDateTo = end + 1 day`.
5. Reassert that every returned purchase date lies inside the inclusive interval and that `purchaseID` values are unique.

## Safe bulk sequence

1. Generate a read-only dry-run first. It must report source count, new-client count, existing/completed count, exceptions, planned `issue_new`, and planned `top_up_existing`.
2. For the no-duplicate policy, require `planned_topups == 0`. The executor must reject every action other than `issue_new` for this bulk mode.
3. Existing/completed sale keys are skipped through the cumulative idempotency ledgers. A rerun after previous periods must not issue the same `(purchaseID, target type)` again.
4. Exact user-confirmed Telegram overrides may be passed only as `EMAIL=@USERNAME` entries bound to the exact source email. Use the identical override set for dry-run, apply, and verifier. Do not silently broaden an override to another email or period.
5. Apply only the ready entries; leave missing-contact and ambiguous rows as explicit exceptions. After apply, independently verify client IDs, card IDs, exact titles, balances, expiration, goods transactions, and sale documents. Then rerun the executor and require zero writes.

## Recovering a missing package special good

The executor’s allowlist must contain a live-verified special good for every planned package type. Never guess a missing ID.

If a type such as `Консультации (8 шт.)` is mapped by the dry-run but absent from the executor’s `GOOD_IDS`:

1. Do not start bulk writes. The live configuration preflight must fail closed.
2. Find a known existing card with the exact package title in a read-only audit.
3. Read that card through the full-network endpoint by one exact `abonements_ids` value and capture `goods_transaction_id`.
4. Read the corresponding goods transaction and extract `good_id`.
5. Re-read `/api/v1/goods/{company_id}/{good_id}` and the exact abonement type list; require exact title equality and `good.loyalty_abonement_type_id == abonement_type.id`.
6. Add the verified ID to the executor allowlist and add a regression assertion for it before retrying. The package’s configured balance/period must also be verified; do not call `set_period` for fixed package types.

A failed live-configuration preflight may leave an empty period ledger because ledger initialization can precede type validation. Treat that ledger as a zero-operation checkpoint, fix configuration, and resume; never replay a successful goods transaction merely because the first run stopped before configuration validation.

## Reporting exceptions

After the final dry-run, list each unprocessed email and the concrete missing field or mapping reason. Common reasons are `missing_telegram_username` and `ordinary_course_has_zero_consultations`; do not present them as completed or convert them into a guessed subscription.
