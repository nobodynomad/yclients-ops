# Sequential multi-month reconciliation

Use this procedure when the user requests reconciliation of several monthly tabs **one month at a time** and explicitly does not want confirmation between months.

## Durable ledger

Keep a small JSON ledger outside disposable checkpoints:

```json
{
  "spreadsheet_id": "...",
  "completed": ["Ноябрь 2024"],
  "pending": ["Декабрь 2024", "Январь 2025"],
  "current": "Декабрь 2024"
}
```

Rules:

- `current` must equal the first item in `pending`.
- Process exactly one month per execution/report.
- Never remove a month from `pending` before every publication gate passes.
- On authentication, audit, formula, formatting, or readback failure, leave the ledger unchanged so the next execution retries the same month.
- Update the ledger atomically only after a verified zero-write rerun: append `current` to `completed`, remove it from `pending`, and set `current` to the next item or `null`.
- Stage a final reconciliation audit together with the updated ledger. Bind the dry-run, final-apply, idempotency, source-manifest, consolidated-checkpoint, and updated-ledger SHA-256 values; include formula/format/partial-fill counts and hashes of untouched sheets. Make the advancement routine re-entrant: if the ledger already points to the next month, verify the existing final audit and report `already_advanced` without rewriting either file.
- Re-read both the final audit and ledger after replacement and verify the stored ledger digest against the exact bytes on disk; do not infer advancement from a scheduler or delivery status.

## Per-month gate

For the selected month:

1. Inventory source identities and semantic row boundaries.
2. Audit all YCLIENTS card statuses and detailed histories in checkpoints.
3. Reconcile duplicates, split-card transfers, attendance, manual changes, and apply-time expiry.
4. Produce and test a precise dry-run.
5. Apply changes only to the selected monthly sheet.
6. Independently verify source counts, values, totals, formulas, semantic formatting, red-font rows, analytics count, package block, and hashes of every other sheet.
7. Rerun the executor and require zero writes.
8. Advance the ledger and deliver a report for that month. Start the next month automatically **only** when the user has an explicit standing instruction to continue without confirmation; when the user requested one named month, advance the ledger pointer but stop before processing the next month.

## Scheduler and cross-session safety

- The scheduled instruction must be self-contained and must explicitly say **one month per run**.
- Use a stable absolute ledger path and verify that it exists before the first scheduled run.
- A run that reports a blocker consumes time but must not consume a month: the ledger, not run count, is authoritative.
- Allow retry capacity rather than assuming every scheduled run succeeds exactly once.
- When no pending months remain, stop or pause the recurring job instead of repeatedly delivering completion messages.
- Never let overlapping runs process the same ledger concurrently. Every cron, interactive session, audit helper, and apply entrypoint must acquire and hold the same OS-level lock for the **entire** execution; merely creating a marker file in one entrypoint does not serialize entrypoints that never check it.
- The lock owner must cover local checkpoint, manifest, dry-run, script, Sheet, and ledger mutations. A read-only YCLIENTS audit still becomes a writer when it persists checkpoints.
- Before consolidating checkpoints or applying, compare checkpoint mtimes/digests and inspect live processes/sessions. A checkpoint changed by another session is provenance drift: invalidate and rerun its whole offset only after one owner remains.
- Do not kill an unfamiliar audit/apply process merely because it overlaps. First identify its owning session and user intent. If a live interactive session is handling the same month after an explicit user request, the scheduled run yields, removes only its own lock/state, leaves Sheet and ledger unchanged, and reports the concurrency blocker. The interactive run continues.
- If ownership cannot be established, fail closed before any Sheet or ledger write. Resume only when a single owner can rebuild a fresh manifest from stable checkpoints.
