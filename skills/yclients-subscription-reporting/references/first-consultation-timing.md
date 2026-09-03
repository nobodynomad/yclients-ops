# Time to first consultation

Use this reference when the user asks how long clients wait after purchase before their first consultation.

## Recommended cohort definition

- Source cohort: purchases with `purchaseDate` in the requested inclusive interval.
- Report primarily at **unique-client level**, not raw sale-row level. Group by stable YCLIENTS `client_id`; use normalized email only as a fallback when no client ID is resolved.
- If a client has multiple purchases in the interval, use the earliest included purchase as the baseline and count the client once. Also report raw purchases and repeat-client count so the deduplication is visible.
- Always load standing reporting exclusions from a private deployment configuration before grouping; never hardcode client identifiers in the repository.

## Attendance event and date

- Count a consultation only from a dated subscription-history `Списание` event. Appointment/status-only rows (booked, confirmed, attended labels without a dated write-off) are not sufficient.
- For each client, collect all relevant all-status card histories, parse operation dates, discard events before the baseline purchase, and take the earliest event on or after it.
- Deduplicate multiple write-off fragments on the same card and date (`0.08 + 0.92` is one consultation for timing purposes).
- Preserve card family/title and card locator as evidence for the selected first event.

## Two statistics are needed

Do not silently mix a three-month window with a later follow-up period:

1. **Strict requested-period result:** first write-off date must be no later than the interval end. This answers “what happened during April–June.”
2. **As-of cohort result:** first write-off may occur after the interval, through the latest verified readout date. This answers “how quickly did this purchase cohort eventually start,” subject to right-censoring.

For both, report:

- cohort size;
- observed clients and clients without a first consultation by the cutoff;
- coverage percentage;
- mean and median days;
- minimum/maximum and preferably p25/p75;
- a simple bucket distribution (0, 1–7, 8–14, 15–30, 31–60, 61+ days).

Never put clients with no observed consultation into the mean as a made-up value. State the denominator explicitly.

## Verification gates

- Check monthly source row counts against the finalized monthly audit artifacts.
- Require every source row to have `ok=true`; record unresolved client/card rows separately and include their emails in the user-facing caveat when data is missing.
- Confirm read-only audit artifacts contain zero YCLIENTS write requests.
- Reconcile raw source rows, unique clients, and repeat clients; explain why monthly unique cohorts may not sum to the overall cohort when a client purchased in more than one month.
- Record the audit/readout date and the latest dated history event. A result including July follow-ups must not be presented as an April–June-only result.

## Provenance

Keep a calculation-only JSON audit with methodology, exclusions, source integrity, cohort-level dates/delays, strict and as-of aggregates, and per-purchase-month breakdowns. Keep the executable calculation script and a small regression suite under the working data directory; do not mutate YCLIENTS or Google Sheets for this analysis unless explicitly requested.
