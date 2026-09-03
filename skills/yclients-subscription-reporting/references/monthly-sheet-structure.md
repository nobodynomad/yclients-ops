# Approved Monthly YCLIENTS Sheet Structure

Use this reference when creating or fully reconciling a monthly report.

## Source and audit scope

- Select sales by the month of `Дата покупки` from the consolidated sales export.
- Separate ordinary course sales from `Пакет консультаций 3/5/8` before building the sheet.
- Audit every selected client in YCLIENTS, including active, expired, and exhausted cards.
- Count attendance only from detailed write-off operations. For individual consultations, sum fractional monetary write-offs until they form whole consultations (`1 ₽ = 1 consultation`).
- If card write-offs and the general visit list disagree, resolve the card manually and leave a note in the affected attendance cell.
- If one consultation type is absent although the export claims it exists, set only that unverified type to zero and leave a note; do not invalidate another verified card on the same row.

## Main block

Columns:

1. Почта
2. Курс
3. Дата покупки
4. Дата окончания абонемента
5. Статус
6. Групп
7. Инди
8. Отходили Групп
9. Отходили Инди
10. Осталось Групп
11. Осталось Инди
12. Просрочилось групп
13. Просрочилось инди
14. Уменьшили групп
15. Прибавили групп
16. Уменьшили инди
17. Прибавили инди

After the client rows, add:

- `Итого` with formulas over every numeric column.
- Six percentage rows: attended, remaining, and overdue, separately for groups and individual consultations.
- Two rows named `Нереализованные консультации`, separately for groups and individual consultations.
- One row named `Клиенты без посещений` with a dynamic count of main-block clients whose group and individual attended values are both zero; exclude statuses `Абонемента нет` and `Обнулен`. This count must equal the rows receiving the approved red-font conditional formatting.
- Two completely blank rows.

Formula for unrealized consultations:

```text
Total − Attended − Overdue
```

## Package block

- Start after the two blank separator rows.
- Columns: Почта, Курс, Дата покупки, Дата окончания абонемента, Статус, Инди, Отходили, Осталось, Просрочилось.
- Do not add the four manual-balance columns to this block.
- Add total and percentage rows for attended, remaining, and overdue.

## Business rules

- `Изменение баланса` is neither attendance nor overdue.
- Record increases and decreases independently, not only their net.
- Before applying a manual change, determine whether the export already contains the post-adjustment quantity; never apply the same change twice.
- `Обнулен`: preserve actual historical attendance by setting `Групп = Отходили групп` and `Инди = Отходили инди`; use zero only for a type with no attendance. Highlight the entire row yellow.
- `Абонемента нет`: set every quantitative consultation field to zero and retain the explanatory note/red exception marking when requested.

## Formatting preferences

- Store purchase dates as true date-only values and display them as `dd.MM.yyyy`; remove the time component from the stored value.
- Do not color ordinary statuses. Only apply colors explicitly approved by the user, currently yellow fill for `Обнулен` and red fill for a specifically identified missing-client exception.
- In the main client block, render the entire row's **font red** when both `Отходили Групп` and `Отходили Инди` are zero. Exclude rows whose status is `Абонемента нет` or `Обнулен`; their existing exception formatting remains authoritative. Prefer one dynamic conditional-format rule over static per-row edits so the red font disappears automatically after attendance changes. Scope the rule only to actual client rows and preserve all fills. For locale-sensitive Sheets API formulas, use a separator-free arithmetic custom formula such as `=($A2<>"")*($H2=0)*($I2=0)*($E2<>"Абонемента нет")*($E2<>"Обнулен")` rather than comma-separated `AND(...)`.
- Preserve the approved template's headers, totals, column widths, and spacing.
- When duplicating a month with a different client-row count, do not assume the copied row fills will move with the rewritten values. Clear displaced gray/green fills from now-empty rows, then reapply them by semantic position: gray on each `Итого` row and green on the package header row. Verify no colored empty rows remain below the report.

## Final verification

- Re-read the completed range through the Sheets API.
- Confirm every source sale appears exactly once and source count equals main rows plus package rows.
- Confirm all purchase-date serials are whole numbers and display without time.
- Confirm formulas reference the current month's actual total row.
- Confirm two blank separator rows exist.
- Confirm package rows have no values in the four manual columns.
- Confirm there are no `#ERROR!`, `#REF!`, `#DIV/0!`, `#VALUE!`, or unexpected `#N/A` cells.
- Confirm status colors are absent except for explicitly approved exceptions.
