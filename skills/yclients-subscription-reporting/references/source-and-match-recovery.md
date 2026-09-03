# Recovering Monthly Sources and YCLIENTS Matches

Use this when building a new monthly report and either the local sales export is gone or an exact YCLIENTS email search does not resolve the client.

## Recover the consolidated sales source

1. Treat local chat/cache copies as disposable. If the expected CSV is absent, search the user-authorized Google Drive for the canonical consolidated-sales filename.
2. Prefer the newest plausible snapshot, but verify it before use:
   - required headers exist (`email`, `Название курса`, `Дата покупки`, group/individual quantities and contacts);
   - the requested month is present;
   - row counts and package counts are plausible;
   - dates are parsed by value, not filename.
3. If the current consolidated snapshot starts after the requested month, search Drive by the canonical filename **and an upper modified-time bound near the month**. Inspect the newest archived snapshots until finding the latest complete full-schema export that actually contains the month; do not create an empty report from the current snapshot.
4. Archives can include converted spreadsheets, raw CSV/XLSX files, or headerless reduced exports. Prefer the full-schema copy with phone and Telegram fields. Use a headerless reduced export only as a cross-check: map its positional columns explicitly, compare month row identities, dates, courses, and quantities, and require the count to agree with the chosen full-schema source.
5. Record the exact source spreadsheet/file ID and tab in the month-building script so the extraction is reproducible.
6. Filter by purchase month, then partition exact `Пакет консультаций 3/5/8` course names before deriving row positions.

## Recover a YCLIENTS client match

Use this order:

1. exact email;
2. normalized full phone;
3. exact Telegram username embedded in the display name;
4. a confirmed corrected email/alias from the local client index.

A recovered alias is only an identity candidate. Accept it only when the phone/Telegram and the selected card family/creation date are semantically compatible with the sale.

## Preserve sales with malformed or repeated identifiers

- Treat the purchase record/ID as the row identity, not the email address. Two distinct purchase IDs for the same person remain two report rows until the source owner explicitly identifies a duplicate.
- Do not silently skip a sale because its email lacks `@`, contains a typo, or repeats another client’s contact data. Keep the row and use its full phone, Telegram username, corrected email, and purchase date as match evidence.
- Do not deduplicate audit results into a single `email → row` map when emails can repeat. Use purchase ID or sheet row as the primary key; an email-keyed lookup is safe only after proving uniqueness for that month.
- When two purchases belong to one client, select cards per purchase using semantic card family plus creation-date proximity. Never reuse one card lifecycle for both rows merely because the contact matches.
- If every identifier search returns no client, preserve each sale as its own verified missing exception with a note; do not collapse multiple purchases into one red row.
- A mutable source can contain several real blank-email rows with the same course and quantities in different months. When re-binding a captured stable sale to the current source, blank email + course + quantities is not unique enough: require the captured exact Telegram username or normalized phone as an additional key, then pin any accepted purchase-date drift explicitly in the source manifest. Never resolve this ambiguity by first-row order.

## Prove that no subscription exists

Do not assign `Абонемента нет` merely because quick search or the loyalty modal produced no cards.

When a candidate client ID and full phone are known, call the authenticated read-only all-status loyalty endpoint with `show_all_statuses_abonements_certificates=1`. Require:

- HTTP 200;
- successfully parsed HTML;
- zero `[data-locator^="abonement_container_"]` elements.

Only then set the verified missing subscription type/row to zero according to the approved report rules and add the explanatory note/red exception marking when required.

If no candidate client ID exists, record the searches performed and require all available source identifiers to fail independently: exact/corrected email, normalized full phone, and exact Telegram username. This is a verified **missing-client exception**, not evidence from an empty loyalty modal.

Manifest and executor gates must distinguish these two evidence classes. Require all-status and visit-history HTTP 200 plus complete dated card histories only for matched clients. For an approved missing-client row, require the captured identifier-search evidence, `no_subscription=true`, zero cards, and no fabricated HTTP status; do not fail the whole month merely because an endpoint requiring a client ID was correctly not called. The approved missing-client row set must still match exactly between audit, reconciliation, dry-run, and final readback.

Distinguish a whole-row absence from a partial absence:

- no client or no consultation cards of either type → `Абонемента нет`, all quantities/manual fields zero, red row and note;
- group card confirmed but no individual card in any status → preserve the group lifecycle, set only the individual fields to zero, keep the ordinary status/color, and note the missing type;
- individual card confirmed but no group card → symmetric treatment for group fields.

## Checkpoint and retry pattern

- Audit in batches of about five and persist each JSON checkpoint.
- Open a fresh authenticated tab after roughly 25–30 clients, before the UI becomes sluggish.
- A fresh tab can fail on its first modal transition; rerun only the failed batch after the tab is warmed.
- Before opening more tabs, close stale YCLIENTS CDP targets that are no longer used. Too many retained tabs can prevent the client-base search UI from finishing initialization even while the page title and read-only loyalty endpoint still respond.
- Verify both prerequisites on a new target before a batch: the known all-status request returns HTTP 200 **and** `[data-locator=search_input]` is present. Endpoint success alone does not prove the client-base UI is ready.
- If a new target does not initialize, keep completed checkpoints, close it, and retry the remaining offsets in a verified-ready target; never reinterpret `search input missing` as a client-level result.
- Never discard completed checkpoints or treat a stopped superseded process as evidence that successful reruns are incomplete.
