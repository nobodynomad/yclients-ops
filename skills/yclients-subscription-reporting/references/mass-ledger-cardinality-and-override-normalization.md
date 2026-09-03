# Mass-ledger cardinality and override normalization

Use this reference when a recent-window YCLIENTS issuance wrapper runs a builder and executor, or when a partially failed operation must be recovered.

## Failure pattern 1: success denominator shrinks during recovery

A period can begin with `N` approved `(sale_ref, target type)` operations. If one operation fails before it reaches `completed`, deleting that operation from the ledger and rebuilding from current YCLIENTS state can produce a smaller `expected_operation_total`. The refreshed planner may also reclassify the sale after sibling cards were created. A later verifier can then truthfully validate every remaining ledger row while completely missing the deleted target family.

This is a completeness failure, not a card-readback failure.

### Required invariant

Persist before the first write:

```text
approved_operation_keys = sorted({sale_ref + "::" + target_type})
approved_operation_count = len(approved_operation_keys)
```

Completion requires all of the following:

```text
set(ledger.operations) == set(approved_operation_keys)
completed_keys == set(approved_operation_keys)
independently_verified_card_keys == set(approved_operation_keys)
len(unique_card_ids) == approved_operation_count
```

Also reconcile every source sale’s required families independently. A completed individual card must never satisfy or hide a required group key.

## Recovery rules

For `stage=issuing` with a document but no persisted transaction:

1. Read the saved document ID.
2. Prove whether cleanup succeeded; a confirmed 404 means the empty document is gone.
3. Query the exact client’s target family across active and all statuses.
4. Search transaction/card ownership evidence for the exact client and good.
5. If a transaction/card exists, resume only missing setters/readback on that card.
6. If the document is gone and no transaction/card exists, keep the operation key and mark it retryable. Do not remove it from the approved manifest.
7. If the existing period executor cannot preserve the key, use a separate exact-client/type scoped recovery ledger and then record that recovered card back against the original approved key.
8. Re-run completeness assertions, independent card/transaction/document verification, and an identical zero-write execution.

## Failure pattern 2: builder accepts an override but executor rejects it

The CLI override parser normalizes email keys, while a direct raw dictionary passed to `apply_telegram_overrides()` may still be case-sensitive. An email containing uppercase characters can therefore work in the builder and appear missing in the executor.

### Wrapper recipe

```python
snapshot = fetch_sales(api_key, start, end_exclusive)
source_emails = {norm_email((sale.get("user") or {}).get("email")) for sale in snapshot[1]}
overrides = {
    norm_email(email): username.lstrip("@")
    for email, username in known_overrides.items()
    if norm_email(email) in source_emails
}
```

Within one wrapper invocation:

- give builder and executor the same immutable snapshot;
- give both the same normalized, source-filtered override map;
- preserve username spelling/case exactly;
- reject conflicts with a nonblank source username.

For the actual apply invocation, fetch a fresh snapshot, rebuild the plan before any write, and compare source count plus exact sale identities/digest to the approved input. Sharing a snapshot inside one invocation does not waive the fresh apply-time drift check.

## Reporting

Report separately:

- newly issued cards in the current run;
- pre-existing completed operation keys;
- approved operation count;
- independently verified count;
- unresolved/missing keys;
- top-ups (must remain zero for ordinary recent-window bulk issuance);
- final zero-write result.
