# Google Sheets mutation review gates

Use this checklist before approving a report script that performs structural or full-range Sheets API writes.

## 1. Bind reads and writes to the same sheet

- Resolve the target by title, then assert its returned `sheetId` equals the expected write ID before building requests.
- Validate the template sheet ID separately; a `copyPaste.source.sheetId` is read-only, while every destination/range must be the allowlisted target ID.
- Recursively inspect the final batch request and reject any write destination outside the target sheet.
- Post-write hashes detect damage; they do not prevent it and are not a rollback mechanism.

## 2. Model `insertDimension` exactly

Requests in one `batchUpdate` execute in order. If a row is inserted before row N, every later `updateCells`, note coordinate, conditional-format range, and formatting range must use post-insert coordinates.

Do not model insertion by truncating the old fixed-size window. Inserting into rows 1..R shifts old row R to R+1. Either:

- read, clear, and verify through R+1; or
- prove row R is empty in values, notes, and formatting before insertion.

Verify the sheet tail after the write, not only the intended report rows.

## 3. Keep formulas typed and coordinates explicit

Carry formulas as an explicit typed object until serialization. Never infer a formula from an arbitrary source string beginning with `=`. Imported email/course/contact text must be written as `stringValue`; otherwise a malicious or malformed source field can become a Sheets formula.

Define one coordinate contract at the serializer boundary and test it directly:

- Google `GridRange` indexes are zero-based with an exclusive end;
- A1/report row numbers are one-based;
- if `is_formula_cell(row, col)` is called from `enumerate(target, 1)`, its row allowlist must also be one-based;
- any helper that accepts zero-based matrix coordinates must add 1 **exactly once** before calling the one-based serializer.

Unit tests for formula allowlists are not enough: build the complete `updateCells` request during dry-run before any network write. This catches a row-convention mismatch where the matrix and tests look correct but request serialization rejects the first formula.

## 4. Notes and blank rows

- Structural insertion moves notes even when `updateCells.fields` only contains `userEnteredValue`.
- Preserve expected evidence notes by stable source identity, then map them to final coordinates.
- Scan required blank separator rows for values, formulas, **and notes**.
- Scan the shifted tail for orphaned notes.

## 5. Formatting and conditional rules

- Derive semantic rows dynamically: main total, analytics, blank separators, package title/header/data/total/rates.
- Apply main-only manual-column ordinary formatting before exception-row fills, then apply yellow/red fills last across the full row.
- Verify package J:Q is blank and white, ordinary rows are white, totals are gray, package header is green, and the unused tail has no displaced fills.
- Verify effective red font across every column and reject partially red rows.
- Verify column widths and other dimension properties explicitly; cell-format checks do not cover them.

## 6. Protect other sheets completely

A value-only hash is insufficient. If using preservation hashes, include at least values/formulas, notes, user-entered formats, conditional formats, grid properties, row/column dimensions, merges, protections, filters, and every used/formatted range. Hash before and after. Still perform the pre-write sheet-ID allowlist because hashes are only verification.

## 7. Source and audit provenance

- Require an authoritative source digest, exact stable identity set, and exact source-row set—not only a count and uniqueness within the audit itself.
- For checkpointed audits, require every expected offset, exact per-file row count, parser/audit version, timestamp, and file hash; prove the consolidated artifact exactly equals their union.
- Derive matched/no-subscription/error counts from evidence; do not hard-code summary claims.
- Reject source-positive card families with no selected card unless an approved exception explicitly zeroes only that family and provides a note.

## 8. Date and formula verification

- Google Sheets date serials use epoch `1899-12-30`; store whole numeric serials and verify `dd.MM.yyyy` formatting.
- Re-read formulas and rendered values. Scan for `#ERROR!`, `#REF!`, `#DIV/0!`, `#VALUE!`, and unexpected `#N/A`.
- Compare section totals to independently recomputed sums.
- Require the no-visits formula and conditional-format formula to use the same row scope and exclusions.

## 9. Idempotency proof

After successful verification, rebuild the plan from a fresh API read and require:

- no insertion;
- zero value/formula diffs;
- zero note changes;
- no conditional-format change;
- no formatting/dimension change;
- therefore zero Google write requests.

Persist this second-plan result separately. Merely routing output to an “idempotency” filename does not prove a zero-write rerun.

## 10. Minimum tests

Tests should cover both calculation and executor helpers:

- insertion at the package boundary and the old last-row shift to R+1;
- formula-object versus source-string serialization;
- one-based formula-cell allowlists versus zero-based matrix/GridRange coordinates, plus construction of the full `updateCells` request before apply;
- date serials and date-only formatting;
- note shifts and blank separator rows;
- exact conditional-format range and full-row red font;
- target title/sheet-ID mismatch rejection;
- other-sheet hash completeness;
- source-positive missing-family behavior;
- a real second `build_plan` returning no requests.

## 11. Review a stable snapshot

Report scripts may be edited or regenerated while an independent review is running. Record content hashes for every target before analysis. If any target changes, invalidate findings tied to the old version, re-read the changed file, and rerun affected tests and probes. Confirm the final hashes immediately before the verdict. In a non-git working directory, review explicitly named files directly; lack of a Git diff is not a reason to skip verification.

## 12. Enforce a single writer and a fail-closed auth boundary

A prompt saying “review only” or “do not modify” is not an access-control boundary. For any task that can mutate a Sheet or sequential ledger:

- The parent executor is the **only writer**. Give reviewers immutable file snapshots/diffs and no write-capable Google credentials, shared working directory, executor entrypoint, or ledger path. Reviewers return findings; they never run apply scripts or “helpfully” patch live artifacts.
- Before applying, ensure every sibling agent and background process that can touch the working directory or Sheet has finished or been cancelled. Then re-read the target Sheet, ledger, executable file hashes, checkpoint manifest, and dry-run. Any drift invalidates approval.
- Treat a YCLIENTS all-status HTTP 403 during a checkpointed month as a transaction boundary. Preserve proven batches, but do not consolidate mixed parser generations and do not apply from an earlier consolidated artifact. Stamp each checkpoint with parser/audit version and hash; quarantine superseded consolidated/dry-run/final artifacts.
- If an unexpected concurrent write occurs, stop all writers and fail closed. Restore the captured pre-apply state with one scoped atomic inverse operation when possible; verify target values, formulas, notes, conditional formats, semantic formatting, grid structure, other-sheet hashes, and the sequential ledger. Do not advance the ledger, and retry the same month after authentication is healthy.
- Keep forensic recovery evidence under a non-success filename. A file named `final_apply_audit` must exist only after a complete fresh audit, verified apply, and real zero-write rerun.
