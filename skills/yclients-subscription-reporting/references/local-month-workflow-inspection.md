# Read-only local month workflow inspection

Use this when asked to assess a monthly YCLIENTS workflow from local scripts and checkpoint files without changing local data or Google Sheets.

## 1. Establish source identity coverage

1. Read the month skeleton/build script and every month checkpoint JSON.
2. Reconcile the asserted source count against checkpoint rows and the main/package split.
3. Derive expected checkpoint offsets from `source_count` and batch size; verify every offset, per-file row count, total count, `ok`, and unique `sheet_row`.
4. Report the strongest identity actually persisted. Prefer source sale ID/source row plus purchase date. If only report `sheet_row`, email, date, and course survive, say explicitly that the original source identity was not retained.
5. Check both unique sheet rows and duplicate contact identifiers. An email-keyed apply dictionary remains a structural defect even when the current month happens to have unique emails.

## 2. Separate checkpoint completeness from workflow completion

A complete first-pass checkpoint set does not prove the month is complete. Compare against the last completed month and inventory the full artifact chain:

- first-pass UI audit script and checkpoint batches;
- all-card/duplicate-family audit script and batches;
- consolidated all-card evidence;
- duplicate/internal-transfer decision evidence when applicable;
- regression tests for identity, expiry, duplicate/transfer, and sheet structure;
- final scoped/idempotent apply script;
- final apply audit showing a zero-write rerun;
- reconciliation ledger advanced only after those gates pass.

Report missing analogous files by absolute path. Treat a month left as `current`/`pending` in the sequential ledger as unfinished even if its first-pass checkpoints all say `ok=true`.

## 3. Inspect semantic exceptions and latent apply defects

Summarize separately:

- `ok=false` rows;
- history/visit mismatches and their allowlisted evidence;
- verified no-subscription rows;
- missing-card-family cases;
- manually decreased/increased balances;
- source quantities that differ from verified lifecycle;
- excluded earlier/later cards;
- multiple equally plausible selected cards or empty selected histories.

Then inspect the apply script for reusable regression risks:

- output keyed by email instead of stable sale identity;
- missing uniqueness/count assertions;
- cached audit-time expiry flags used at apply time;
- missing all-card duplicate/internal-transfer handling;
- absent `Клиенты без посещений` analytics/formatting gates;
- no formula/error/full-range formatting verification;
- no idempotent final audit and zero-write rerun.

Do not describe a manually edited `ok=true` no-subscription checkpoint as fully evidenced unless local artifacts preserve the exact email/phone/Telegram/all-status search proof.

## 4. Preserve read-only scope

- Do not run skeleton or apply scripts: both write Google Sheets.
- Do not rerun valid checkpoints merely to inspect them.
- Avoid `py_compile`, imports that emit bytecode, formatters, chmod, or any command that changes local artifacts.
- For syntax-only checks, parse source without bytecode, for example:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast, pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in PATHS]'
```

- For imports needed to call pure loaders/calculators, set `PYTHONDONTWRITEBYTECODE=1` or `python3 -B`.
- Temporary files must live outside the working dataset and be removed immediately.
- Report any accidental cache generation honestly and restore/remove only artifacts known to have been created during the inspection.

## 5. PII permissions

Checkpoint files contain client PII. Inspect modes and compare with the completed workflow. New checkpoint/evidence writers should call `chmod(0o600)` after each atomic write. Report permissive modes such as `664` as a security anomaly, but do not change permissions during a read-only inspection.

## 6. Reusable command sequence

Provide two sequences, clearly distinguished:

1. **Fresh-month sequence**: skeleton once, checkpointed first-pass audit, integrity gate, all-card audit, consolidation, tests, final scoped apply, final scoped zero-write rerun.
2. **Current resume sequence**: start at the first missing artifact; never rerun the skeleton or overwrite already valid checkpoint batches.

If required scripts are absent, say that no complete executable command chain currently exists. Show the exact commands that are available and the expected filenames/offsets for the blocked remainder; never recommend running an older apply script that bypasses the completed-month gates.
