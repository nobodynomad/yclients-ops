# Fresh-audit drift and multi-card adjudication

Use this when a previously reconciled monthly row is audited again and current YCLIENTS state differs from historical checkpoints.

## Fresh no-subscription set

- Treat the current all-status/all-card result as authoritative. A row historically marked `Абонемента нет` may now have a card because staff issued or repaired it later.
- Keep the audit harness's *candidate exception* set separate from the manifest's *verified current no-subscription* set.
- Build the manifest set from rows that currently have `no_subscription=true`, zero cards, and exact search evidence. Do not copy the historical exception set into final expectations.
- Conversely, do not remove a historical no-subscription candidate merely because it is stale: the fresh audit still needs permission to accept a current empty result for that exact row.
- Regression-test both sets so a newly appearing card becomes a normal reconciled row rather than a manifest failure or forced zero row.

## Multiple cards in one family

A same-family tie is not automatically a duplicate and should fail closed by default. Permit aggregation only through an exact row-level allowlist after proving one of these patterns:

1. **Operational adjustment card:** a newer card was created with a large initial balance, immediately reduced to a small current balance, and aligned to the sale/course expiry. Aggregate it with the original card and expose the reduction in manual-adjustment columns.
2. **Replacement pair:** active replacements and manually cancelled same-day duplicates coexist. Exclude exact cancelled locators and retain replacements so cancellation decreases are not reported as customer balance changes.
3. **Earlier/later purchase:** exclude exact locators whose sale dates, expiry, title, or lifecycle prove another purchase. Preserve a note and exact visit-mismatch tuple if client-wide visits include that excluded card.
4. **Wrong package family:** for a package sale, exact package semantics outrank nearest-date matching. Exclude a same-day `5` package card from a `3` package sale when the matching `3` card independently explains the lifecycle.

For every permitted aggregate or exclusion, pin source row, card locator(s), rationale, selected-family totals, and any visit mismatch in tests. Never globally relax the multi-card tie gate.

## Late-issued cards

A card created weeks after the source purchase may still be a delayed issuance when it is the only compatible family and its expiry/course lifecycle aligns with the source. Retain it only with row-specific evidence; do not apply a global date-distance cutoff.

## Final gates

- Recalculate statuses and quantities from the fresh selected cards, not historical report values.
- Confirm all no-subscription, missing-family, multi-card, exclusion, and mismatch sets exactly.
- Require full-sheet readback and a zero-write rerun before ledger advancement.
