# Fresh-window override and issuance recovery

Reusable notes from a recent YCLIENTS bulk run.

## Window and override preparation

1. Read the host date, not conversation context. For `N` days use the inclusive interval `today - (N - 1)` through `today`; send `end + 1 day` to the sales API as the exclusive upper bound.
2. Fetch the immutable selected source snapshot and assert `rows_collected == unique purchaseIDs == artifact entries`.
3. Normalize both source emails and override-map keys to the same canonical lowercase form before applying aliases. This is required even when a CLI parser normalizes its own copy: a mass executor may receive the raw Python dict and perform case-sensitive lookup. Filter the known override map to emails present in this snapshot before invoking helpers that reject absent override keys. Keep the filtered, canonical map identical across dry-run, apply, verifier, and ledger. Report absent historical overrides as ignored, not as missing source data.
4. Apply an override to the in-memory sale/user object before source-client construction; otherwise a complete sale with blank source Telegram can be rejected as incomplete.

## Bulk gates

- Allow only `issue_new` in the ordinary recent-window executor.
- Require `planned_topups == 0`.
- Preserve stable `(purchaseID, type title)` operation keys; a new period can overlap an old period, so current cards and prior ledgers must both participate in duplicate checks.
- Keep named existing-client additions in separate scoped ledgers. A current card created by a named workflow must not be mistaken for an unissued bulk sale.
- Before apply compare fresh source count/references with the approved dry-run. Stop on drift.
- Freeze the pre-apply exception set for reporting. After successful issuance, the same source rows will legitimately reclassify from `new`/ready to `existing`/completed in a fresh dry-run; do not report those post-apply `existing_client_has_subscription...` entries as if they were skipped before the run. Keep pre-existing completed operations, newly issued operations, and post-apply idempotency observations as separate counters.

## Partial issuance recovery

When an operation fails after document creation:

1. Read the ledger first. Do not rerun the normal client preflight or call `issue_card` immediately; the newly created client may now resolve as an exact match and a retry can either block or duplicate.
2. Distinguish `document_created` from `transaction_created`. A persisted `goods_transaction_id` is the key side-effect proof. A document ID alone is not a card proof.
3. Query the exact saved document. If cleanup returned success and a subsequent GET returns 404, the empty document is gone. This still requires a target-card/transaction lookup before retrying.
4. Query the exact client’s target family using the source phone and inspect saved transaction/card ownership. If a card or goods transaction exists, recover its missing balance/period/readback only; never reissue.
5. Only when the document is gone and no target card or goods transaction exists may the one failed operation key be removed/reset for a single retry. Leave every completed operation and client checkpoint untouched.
6. After the retry, verify card title, balance, expiry, card ID, `goods_transaction_id`, document ID, exact client ID, good ID, and good→abonement-type linkage.
7. Remove only a resolved failure entry. Keep the operation completed and record recovery metadata if the ledger schema supports it.
8. Run the identical executor again and require `0 writes`, empty failures, and no ready operations.

## Verifier invariants

For each ledger operation:

- read `good_id` and `document_id` from `issue_meta` when the operation does not duplicate them at top level;
- read the card by exact ID and require exactly one match;
- compare exact live type title, target absolute balance, and target expiry;
- read the goods transaction and require exact client ID, good ID, and document ID;
- report newly issued cards in this run separately from pre-existing completed operations discovered in the source artifact.

A verifier that marks every card wrong while balances/titles/transactions match often indicates it looked for `good_id` in the wrong ledger location rather than a YCLIENTS defect.
