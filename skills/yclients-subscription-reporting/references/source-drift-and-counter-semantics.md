# Source drift and audit-counter semantics

Use these gates when a monthly report binds a stable captured sale identity to a mutable current sales export and a fresh all-status YCLIENTS audit.

## Purchase-date drift

- Keep the captured sale date as the month-bucketing authority when contact/course/quantities and the exact source row are independently re-proven against the current export.
- Record every differing current purchase date as an explicit row-specific manifest entry: `stable source row → current date`.
- Fail closed if the drift set changes, gains an unapproved row, or the exact current source row is no longer unique.
- Do not silently overwrite the captured date or move the sale to another month merely because the mutable export changed.

## Exact aliases

- Store only aliases actually needed by authoritative source rows, not the audit harness’s whole historical alias dictionary.
- Require exact normalized email or exact approved Telegram username plus matching course, quantities, and one unique current source row.
- Regression-test the exact alias set and reject arbitrary alternate contacts.

## Audit counters

Keep these counters distinct:

- `all_status_clients_audited`: every source identity, including verified no-subscription rows.
- `matched_clients_all_status_200`: source identities with at least one selected subscription/card lifecycle; excludes verified whole-row no-subscription cases.
- `verified_no_subscription_clients`: exact identities with successful search/all-status evidence and zero cards.
- `all_status_http_200` and `visit_history_http_200`: transport/read evidence counts; a verified no-subscription row may still count here because both reads can succeed with HTTP 200.
- `fresh_detailed_card_histories_200`: number of cards with complete detailed histories, not number of clients.

Never force all these counters to the same source count. Assert their relationships explicitly in the executor and final ledger gate.

## Excluded-card visit reconciliation

When a source family is zero and a card is proven to be a separate later/earlier sale:

1. persist the exact excluded card locator and reason;
2. remove it from lifecycle totals and status classification;
3. preserve the client-wide visit history;
4. allowlist only the exact tuple `(selected group write-offs, group visits, selected individual write-offs, individual visits)`;
5. add a row note so the mismatch is visible and evidence-backed.
