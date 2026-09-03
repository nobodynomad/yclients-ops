# Yclients history reconciliation: durable audit rules

Use this reference when reconciling CSV sales with Yclients cards and visit history.

## Source-to-card matching

- The CSV determines the sale month and expected package quantities, but a CSV zero does not suppress a real Yclients card.
- For rows in the lower `Пакет консультаций 3/5/8` block, exports may place the explicit package quantity in the group column even though the report represents it as individual consultations. Resolve quantity in this order: non-zero source individual quantity; otherwise non-zero source group quantity mapped to package `Инди`; otherwise the selected card lifecycle. Do not overwrite an explicit source quantity by parsing `3/5/8` from the course title, and do not infer the title number when both source quantity fields are zero.
- Never fill a CSV zero with a hard-coded “standard” package size (for example, 6 individual consultations).
- Do not attach the nearest available card by date alone. Require semantic compatibility with the course/service and inspect card history when dates are far apart or the quantities disagree.
- Card-title classifiers must have an all-card fallback. A valid individual card can have a custom or malformed title with none of the expected words. When the normal semantic selector finds no date-compatible card, inspect every visible card and its detailed history; a card created/sold at the source-sale date with the right lifecycle can be authoritative even under an unexpected title. Continue to classify only the exact title `Групповая консультация` as group; an accepted custom consultation card belongs to individual usage.
- Old cards are not automatically relevant or irrelevant. Exclude an earlier card when its own sale and consumption belong to a separate purchase and there is no balance/date operation tying it to the requested source sale. Conversely, a pre-existing card may have been deliberately reused: a balance addition or validity-date change near the requested sale can tie that lifecycle to the current row. Record the evidence and exclude unrelated visits from aggregate history.
- If CSV is zero and a relevant card exists, derive the effective quantity from that card’s actual lifecycle: confirmed write-offs plus current or expired remaining units. Positive balance additions that created units later consumed/current affect how many consultations were actually available, but the balance-change operation itself is never attendance or overdue.
- Before writing, verify the quantitative identity:
  `available quantity = actual write-offs + current remaining + expired remaining + explained manual reductions`.
  Any unexplained difference is an exception, not a value to guess.

## History parsing

- Expand “show all subscriptions and certificates” before looking for expired/exhausted cards.
- Count only `Списание` transactions for attendance; ignore `Изменение баланса` and date changes.
- Group cards: sum ₽ amounts in actual write-off transactions. An `(x2)` / `2 ₽` transaction is two consultations.
- Individual and consultation-package cards: sum every actual write-off amount across `Использование абонемента` and `Перерасчет стоимости по абонементу`; 1 ₽ total = 1 consultation. Pair shapes vary (`0.08+0.92`, `0.05+0.95`, `0.2+0.8`, etc.), so never count pairs structurally.
- Classify only the exact card/service name `Групповая консультация` as group. Other consultation cards, including `Консультации (3/5/8 шт.)`, are individual/package usage.
- Visit-row DOM contains variable whitespace. Detect `Абонемент ... 1 визит` with a whitespace-tolerant regex.
- When the detailed selected-card history and aggregate client visit count disagree, do not force them to match arithmetically. The card history is authoritative for consumption when its dated write-offs, service name, and card identity are unambiguous. Preserve the parsed amount (including `(x2)`), add a cell note explaining the aggregate mismatch, and do not count unrelated aggregate visits against the selected card.
- Validate visits in two stages. First, the fresh client-wide audit should reconcile aggregate visits against **all** freshly fetched cards; this catches incomplete card expansion or broken history parsing. Second, after sale-specific card exclusions are applied, recompute selected-card group/individual usage and compare it again with client-wide visits. Every remaining mismatch must have an exact row-specific tuple `(selected_group, client_group, selected_individual, client_individual)` plus card-locator evidence showing that the difference belongs to excluded earlier/later cards. An all-card match does not waive this second selected-sale gate.
- Treat later replacement or follow-up cards explicitly, not through a broad date cutoff. Record each excluded locator and reason, retain a same-family later card only when source-positive family evidence and lifecycle semantics tie it to the requested sale, and attach a note to the report row. A delayed issuance date alone is not enough to exclude the only semantically compatible source-positive family.
- A client can hold multiple individual cards created together (for example, an accidental package-5 card immediately reduced to zero plus the purchased package-3 card that was actually consumed). For a package row, use the exact package title and its lifecycle for acquired/used/remaining values; manual changes on a different card are contextual evidence, not units of the reported package.

## Spreadsheet write safety

1. Collect a dry-run audit artifact with raw selected-card history, parsed write-offs, visit counts, selected card creation date, and reason for card selection.
2. Manually inspect at least one known positive group case, one fractional individual case, one manual-balance case, and one CSV-zero case before bulk writes.
3. Reject invalid/empty card selectors and wait for history content to render before parsing.
4. Update main rows in H/I (`Отходили групп/инди`); package rows use G for `Отходили`.
5. For expired packages, move unused real balance to `Просрочилось`; do not leave `Приобретено > Отходили + Осталось + Просрочилось` unless the difference is explained by a manual balance change.
6. After writing, verify formulas, totals, percentages, allowed statuses/exceptions, and list every residual reconciliation difference with its supporting history operation.
7. Treat implausible aggregate shifts (for example, attendance collapsing nearly to zero) as a failed audit signal. Stop, inspect selectors/parsers, and do not report completion until positive known cases reproduce correctly.
