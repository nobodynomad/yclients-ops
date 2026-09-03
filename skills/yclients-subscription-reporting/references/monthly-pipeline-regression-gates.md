# Monthly pipeline regression gates

Use these gates after checkpointed Yclients UI auditing and before telling the user a monthly sheet is complete.

## 1. Checkpoint integrity

- Before building offsets, derive the target Sheet read range from the last expected semantic source row, including any package rows below analytics and separators. Assert `range_end >= max(expected_source_rows)` and add a month-specific regression test. A copied fixed range that covers only the main block can return HTTP 200 while silently omitting the package block.
- Require the stable source skeleton’s ordered row coordinates to equal the exact expected main-plus-package coordinates before any YCLIENTS client audit starts.
- Derive expected offsets from the source-row count and batch size.
- Confirm every checkpoint file exists and contains its expected number of rows; the final checkpoint may be partial.
- Sum checkpoint rows and require exact equality with source sales rows.
- Reject any row with `ok != true`, UI-loading failures, missing history panels, or unresolved history/visit mismatches.
- A killed or timed-out process proves nothing. Keep already valid checkpoints, rerun only failed offsets in a verified-ready browser target, and ensure the successful rerun overwrites the failed checkpoint before aggregation.
- Validate both the all-status endpoint and `[data-locator=search_input]` before trusting a new target. Close stale targets to avoid resource starvation.

## 2. Exception evidence

- Resolve source columns by semantic aliases before filtering the month. Consolidated sheets may use canonical headers such as `email`, `Номер телефона`, `telegram_username`, `Кол. групповых консультаций`, and `Кол. персональных консультаций`; report templates may instead say `Почта`, `Телефон`, `Телеграм`, `Групп`, and `Инди`. Print/validate the actual header row and fail on an unresolved required field rather than silently producing `None` contacts or zero quantities.
- For a full-row `Абонемента нет`, search exact email, normalized full phone, and Telegram/known alias; confirm all-status absence and attach an explanatory note.
- For a missing card family, preserve the confirmed family and zero only the missing family with a note.
- When detailed card history and aggregate visit history disagree, use detailed write-offs only after inspecting the dated operations; add a note naming the confirmed counts and why detailed history won.
- Compare each selected card’s creation/`Продажа` date with the source purchase. If a source type is zero and the nearest card of that family was sold months later, exclude it as a separate later purchase unless course semantics and lifecycle evidence explicitly tie it to the requested row. Persist the exclusion in the checkpoint and attach a sheet note; do not merely suppress the mismatch in the apply step.

## 3. Quantity and status reconciliation

For each type, compare:

- `current lifecycle = used + remaining + overdue`;
- `reconstructed original = current lifecycle + decreases - increases`;
- source quantity.

Avoid applying a manual change twice when source already equals current lifecycle. Otherwise apply `source - decreases + increases`, floored at current lifecycle.

A true `Обнулен` requires every available card family to have its own manual decrease evidence and all balances to be zero. `all balances == 0 AND any decrease > 0` is insufficient; naturally exhausted families must not be converted to `Обнулен`. After classifying the row, override effective `Групп`/`Инди` with the actual attended values and require equality with `attended + remaining + overdue` for that row. This override must happen after status classification; otherwise source units can survive in a yellow zeroed row.

The effective purchased total for an ordinary (non-`Обнулен`) row can legitimately differ from `used + current remaining + overdue` when source-plus-adjustment rules preserve quantities no longer visible in current balances. Therefore verify the report formula independently:

`Нереализованные = effective purchased - used - overdue`

Do not force it to equal the current remaining column.

## 4. Sheet structure and formatting

- Main data rows + package rows must equal source sales rows.
- Purchase dates must be numeric date-only values formatted `dd.MM.yyyy`.
- Main manual-adjustment columns must be absent from the package block.
- Scan rendered values for `#ERROR!`, `#REF!`, `#DIV/0!`, `#VALUE!`, and `#N/A`.
- Inspect background colors across the full used range: only report headers, actual totals, package header, yellow `Обнулен`, and red `Абонемента нет` may be colored.
- Copy manual-column formatting from one ordinary template row, not a long source range containing an old total row.
- Confirm two blank white rows between analytics and the package section.

## 5. Final summary

Report source/main/package counts, totals by type, status counts, package totals/statuses, documented exceptions, and the direct `gid` link. Base all claims on the final API reread, not apply-script stdout alone.
