# Cross-Month Aggregate in Monthly Report Structure

Use this reference for the user's `Общее` YCLIENTS workbook tab.

## Source boundary

When the user says to use only the spreadsheet, monthly tabs are the complete source of truth. Do not open YCLIENTS, local audit checkpoints, or sales exports. Discover tabs by exact Russian month/year titles and sort chronologically.

## Extraction

Find data blocks semantically in every month:

- main data: row after the main header through the row before the first `Итого`;
- package data: row after the `пакет конс` header through the row before the package `Итого`.

Do not filter a row only because email is blank. Course, purchase date, and status can establish a valid sale. Exclude source totals, rates, unrealized rows, headings, and separators.

Carry a stable identity `(month, block, source row)` and never deduplicate by email.

## Secondary `Сводка` KPI matrix

When the workbook contains a user-designed `Сводка` tab with month labels down the left and paired group/individual metrics across the top, preserve its headers, merges, month labels, and all non-target formatting. Populate only the requested data rectangle.

Use each monthly tab's semantic main data block (row after the header through row before the first `Итого`). Packages remain separate and do not enter this matrix. For each month calculate:

1. bought group/individual = sums of monthly columns F/G;
2. attended percentages = sums H/F and I/G;
3. attended counts = sums H/I;
4. remaining percentages = sums J/F and K/G;
5. remaining counts = sums J/K;
6. overdue percentages = sums L/F and M/G;
7. overdue counts = sums L/M.

Compute each percentage from that month's summed numerator divided by that month's summed purchased quantity—not as an average of row-level percentages. Store percentages as numeric fractions and apply `0.00%` only to the six percentage columns. Explicitly excluded identities must be normalized case-insensitively and filtered before all sums; keep the exclusion set in the source digest even when the rows have already been deleted from the workbook.

Bind the exact `Сводка` title/sheetId and user header/merge layout before mutation. Write only the data rectangle plus percentage number formats, hash every other sheet before/after, reread all values and rendered percent cells, and require a zero-write second plan.

## Approved aggregate layout

The aggregate is not a flat mixed table.

### Main block

Keep `Месяц` as the first column, followed by the monthly main A:Q columns. Do not add `Тип блока`.

After all main rows, add:

1. `Итого` over every numeric main column;
2. six percentage rows: attended, remaining, overdue, each for group and individual;
3. two `Нереализованные консультации` rows;
4. one `Клиенты без посещений` row;
5. two completely blank rows.

The no-visits row follows the same sale-row semantics as monthly reports: count a main row when both attended quantities are zero, excluding statuses `Абонемента нет` and `Обнулен`. With the aggregate's leading Month column:

```text
No visits = SUMPRODUCT((I2:I_main_end=0)*(J2:J_main_end=0)*(F2:F_main_end<>"Абонемента нет")*(F2:F_main_end<>"Обнулен"))
```

Apply one scoped conditional-format rule to the full main data range A:R using the row-relative formula:

```text
=($I2=0)*($J2=0)*($F2<>"Абонемента нет")*($F2<>"Обнулен")
```

The rule changes font color to red across the entire row. It does not apply to package rows, and it must use the exact same range and exclusions as the no-visits count formula.

With the leading Month column, main numeric columns shift to:

- G/H: Group/Individual totals;
- I/J: attended;
- K/L: remaining;
- M/N: overdue;
- O/P/Q/R: group decrease/increase and individual decrease/increase.

Formulas:

```text
Attended group % = I_total / G_total
Attended ind %   = J_total / H_total
Remaining group % = K_total / G_total
Remaining ind %   = L_total / H_total
Overdue group % = M_total / G_total
Overdue ind %   = N_total / H_total
Unrealized group = G_total - M_total - I_total
Unrealized ind   = H_total - N_total - J_total
```

### Package block

After the two blank rows:

1. a white bold `пакет конс` title row;
2. a green header with `Месяц` plus package A:I;
3. all package rows;
4. package `Итого` over individual purchased/attended/remaining/overdue;
5. three package percentage rows.

Do not add main-only manual-balance columns to the package block.

## Formatting

- Main header: approved blue fill, bold.
- Main/package totals: gray, bold.
- Analytics and separators: white.
- Package title: white, bold.
- Package header: green, bold.
- Ordinary data: white.
- `Обнулен`: yellow whole row.
- `Абонемента нет`: red whole row.
- Dates: true date serials displayed `dd.MM.yyyy`.
- Preserve source notes on the aggregate Status cell.

## Verification gates

Re-read the aggregate through Sheets API and assert:

- source main count equals aggregate main count;
- source package count equals aggregate package count;
- main totals equal the sum of source monthly main `Итого` rows;
- package totals separately equal source monthly package `Итого` rows;
- every formula points to the aggregate's actual semantic rows;
- two separators are completely blank;
- `Тип блока` is absent and `Месяц` is present in both headers;
- dates belong to their labeled month and have no time;
- statuses are allowed;
- notes and exception colors are preserved;
- no formula errors exist.

## Publication sequencing

- Aggregate only month tabs that have passed their own final reconciliation, scoped publication, reread, and zero-write rerun. Do not publish an unfinished month into `Общее` merely because its source audit or manifest exists.
- Discover eligible tabs by exact Russian month/year title and sort chronologically. Bind the ordered title list, per-month main/package counts, stable `(month, block, source row)` identities, source rows, and source notes into one source digest before mutation.
- A stale aggregate can already show the newest month label while still being short a row or using shifted totals/formulas. Never infer freshness from the last visible month; compare exact source identity counts and semantic boundaries.

## Scoped and idempotent aggregate executor

Treat `Общее` as its own publication target rather than running a destructive historical rebuild script directly.

1. Resolve the exact title and assert the live `sheetId` before constructing requests.
2. Build the entire desired two-block matrix calculation-only. Carry formulas as a typed object and allow them only at the exact total/analytics cells; source text beginning with `=` must remain a literal string.
3. Derive every layout coordinate from live source counts: main total, eight analytics rows, two blank separators, package title/header/data/total/rates, and final row.
4. Compare desired values/formulas and notes with a fresh target reread. Clear stale values and notes through a proven tail that covers both old and new used ranges; verify the remaining physical tail is blank/default instead of assuming the old last row.
5. Recursively inspect the final Sheets batch and reject any `sheetId` other than the allowlisted `Общее` target. Prefer one scoped batch containing the value/formula/note update plus semantic formatting requests.
6. Hash every non-target sheet before and after using values/formulas plus rich state: notes, user-entered formats, conditional rules, dimensions, merges, filters, protections, and validations.
7. Persist a dry-run artifact containing the source digest, source counts, semantic layout, request counts, and executable/test hashes. Re-read sources immediately before apply and fail closed on drift.
8. After apply, reread formulas, rendered values, notes, fills, number formats, dimensions, filters, conditional rules, and the cleared tail. Rebuild the plan from fresh state and require zero Google write requests.

## Dynamic notes and independent verification

- Derive the expected aggregate note count from current monthly source rows on every run. Never hard-code a note count from an earlier aggregate revision; monthly reconciliation can add evidence notes without changing row counts.
- Remap each source row's notes to the aggregate Status cell by stable source identity after main/package rows are separated. Multiple source-cell notes may be combined into one evidence note, but no noted source row may disappear.
- Run an independent post-write verifier in addition to executor readback. It should rediscover monthly semantic totals, prove source and aggregate row counts match, compare independently summed main/package totals, validate exact formulas, ensure purchase dates belong to the labeled month, scan formula errors, count exception fills/notes, and confirm `Тип блока` is absent.

## Pitfalls

- A flat table with `Месяц` + `Тип блока` is useful for database-style analysis but is not the approved presentation here. Do not substitute it for the monthly two-block structure, totals, percentages, and unrealized analytics.
- Do not trust an old verifier whose semantic row constants or expected note count were captured before new months/reconciliation notes were added. Derive coordinates and note expectations from the current source model, or update the verifier in the same tested change.
- Do not use a value-only preservation hash or a multi-call clear-then-rewrite sequence as the safety boundary. Enforce target allowlisting before the write and verify rich state afterward.
