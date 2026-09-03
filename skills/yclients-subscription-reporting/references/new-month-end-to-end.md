# End-to-End New-Month Automation

Use this runbook when creating a new monthly YCLIENTS report tab from the consolidated sales export.

## 1. Discover source and partition rows

1. Prefer the current consolidated sales Google Sheet when a temporary uploaded CSV/cache file has disappeared; select rows by the month of `Дата покупки`.
2. Record the source row count before writing anything.
3. Split exact course names `Пакет консультаций 3`, `Пакет консультаций 5`, and `Пакет консультаций 8` into the lower package block. All other sales go to the main block.
4. Derive every structural row dynamically from `main_count` and `package_count`:
   - main total;
   - six percentage rows;
   - two unrealized rows;
   - two blank separator rows;
   - package title/header/data/total/percentage rows.
5. Store purchase dates as whole date serials and format them `dd.MM.yyyy`.

## 2. Build a reversible skeleton

1. Duplicate a stable approved month as the layout source.
2. Clear values and notes while preserving column widths and base styles.
3. Write source identity fields and initial quantities only; do not publish attendance from balances.
4. Use formulas for totals, percentages, and unrealized consultations.
5. Keep the four manual-balance columns only in the main block.

## 3. Audit every sale through YCLIENTS UI

1. Verify a known all-status loyalty-card request returns HTTP 200 before starting.
2. Process five clients per checkpoint JSON. After roughly 25–30 clients, open a fresh authenticated tab instead of waiting for the old tab to degrade.
3. A fresh tab can fail on its first modal transition. Continue the batch, then rerun only the failed checkpoint after the tab is warm; never discard already valid checkpoint files.
4. Match by exact email first. If absent, use source Telegram, then a confirmed alternate YCLIENTS email or normalized phone from the client index.
5. For a suspected missing subscription, query the all-status loyalty-card endpoint directly and confirm both HTTP 200 and zero `[data-locator^=abonement_container_]` elements. Only then assign `Абонемента нет`, zero quantities, red fill, and a note.
6. Count group attendance from write-off events. For individual/package cards, sum all fractional write-off amounts and round the card total (`1 ₽ = 1 consultation`).
7. Compare selected-card attendance with visit history. If unrelated group visits make a package row look mismatched, use the selected package card plus matching individual visits and leave a note.
8. Persist every alias and manually resolved exception in the month audit/apply script so reruns are deterministic.

## 4. Reconcile quantities and statuses

1. Parse manual decreases and increases independently; they are neither attendance nor overdue.
2. Detect whether the export contains the original or already-adjusted quantity before applying a balance change, preventing double application.
3. Use `Отходили + Осталось + Просрочилось` as the lifecycle floor.
4. Apply `Обнулен` only when every balance was manually zeroed and no active card remains; set purchased quantities to actual attendance by type and color the row yellow.
5. For expired cards, put balance in overdue and display current remaining as `-`.

## 5. Remap formatting semantically

Do not reuse absolute row positions from the source month.

1. Copy ordinary data-row format to all actual client rows.
2. Clear displaced fills from the report tail.
3. Copy gray total-row format to the actual main and package total rows.
4. Copy green package-header format to the actual package header only.
5. Keep percentage/unrealized rows and separator rows white.
6. Apply yellow/red only to approved exception rows.
7. Verify no gray or green empty rows remain below the report.
8. Before building `copyPaste` requests, inspect the template cells' actual fills/number formats and label each source row by semantic role (ordinary package data, package total, rates). Do not infer those roles from absolute row numbers or request order. In particular, map the white package-data source to every package data row and the gray source only to the package `Итого`; the executor must fail its reread if either mapping is reversed.

## 6. Final gate

Before reporting completion, re-read the sheet and verify:

- source count equals main rows plus package rows;
- every audit checkpoint is loaded or explicitly resolved;
- date serials are whole numbers;
- package manual columns are blank;
- two separator rows are completely blank;
- gray/green fills are on semantic rows only;
- formulas contain no `#ERROR!`, `#REF!`, `#DIV/0!`, `#VALUE!`, or unexpected `#N/A`;
- reported totals exactly equal rendered sheet totals.
