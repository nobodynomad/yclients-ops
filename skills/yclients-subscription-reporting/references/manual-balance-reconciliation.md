# Manual balance reconciliation

## Rule

`Изменение баланса` is an administrative adjustment, not a consultation attended and not an overdue balance. A report must never derive `Отходили` simply as `purchased − current balance` when a card has such history.

## Required classification

| Card history event | Report effect |
|---|---|
| `Списание` / `Использование абонемента` | Count as actual attendance (apply the agreed grouping rule for partial individual write-offs). |
| `Изменение баланса` by administrator | Decrease current balance only; do **not** add to attended or overdue. |
| Expiry with a nonzero balance | Put remaining balance in the overdue column and show current remaining as `-`. |

## Audit procedure

1. Read all subscription cards, including expired and exhausted cards.
2. Inspect the card-history events, not just the visible current balance.
3. Keep separate totals for: originally issued units, actual write-offs, manual balance adjustments, current balance, and overdue balance.
4. Write the approved report columns from those totals:
   - `Отходили` = actual write-offs only;
   - `Осталось` = current balance unless expired;
   - `просрочилось` = balance only for expired cards.
5. If the data source does not expose history events, do not infer attendance from a balance delta; mark it for user-authorized UI/history reconciliation before publishing a final report.

## UI fallback note

The authenticated client-card UI can expose all cards through `get_client_loyalty_cards_json` with `show_all_statuses_abonements_certificates=1`. Verify that the returned history actually contains manual balance events before treating it as the authoritative history source; otherwise inspect the client’s visible visit/history UI.