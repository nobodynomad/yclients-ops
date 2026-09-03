# Monthly Sheet Cloning and Semantic Format Remapping

Use this when a new monthly YCLIENTS tab has a different number of client or package rows than the template month.

## Why positional cloning fails

Duplicating a prior tab preserves formats at the prior month's absolute row numbers. Rewriting values at new row numbers does **not** move gray totals, green package headers, notes, or fills. This can leave colored empty rows below the report and unformatted semantic rows.

## Safe procedure

1. Partition source sales into main rows and package rows first.
2. Derive all semantic row numbers from the actual counts:
   - main `Итого`;
   - six percentage rows;
   - two unrealized rows;
   - two blank separator rows;
   - `пакет конс` title;
   - package header, data, `Итого`, and three percentage rows.
3. Duplicate an approved month only as a style source.
4. Clear **values and notes** in the new tab while preserving formatting.
5. Write the complete new structure and formulas using the derived row numbers.
6. Copy formats from the approved template sheet by semantic role, not from absolute rows in the new destination:
   - ordinary data row → all new data rows;
   - main total → new main total;
   - percentage row → new percentage rows;
   - unrealized row → new unrealized rows;
   - package title/header/data/total/rate rows → their new equivalents.
7. Important: if format-copy requests run sequentially, do not first overwrite destination rows and then use those same destination rows as style sources. Use the unchanged template sheet as the `source.sheetId`; otherwise the source style may already have been destroyed.
8. Reset the report tail to white, then reapply only approved fills:
   - gray on each `Итого` row;
   - green on the package header row;
   - yellow only for `Обнулен`;
   - red only for an approved missing-subscription exception.
9. Keep ordinary status cells and ordinary data rows white.
10. Apply explicit number formats after copying styles:
    - purchase/expiry dates: `dd.MM.yyyy`;
    - percentage cells: `0.00%`;
    - unrealized counts: integer/number.

## Verification

- Re-read colors from the grid data API, including empty rows below the report.
- Confirm no colored empty rows remain.
- Confirm main total is gray across the full main width.
- Confirm package header is green only across package columns.
- Confirm package total is gray only across package columns.
- Confirm both separator rows are empty and white.
- Confirm no ordinary status colors were introduced.
- Confirm formulas and number formats still render correctly after format copying.
