# Early-month card-family reconciliation patterns

Use this note when a monthly sale is older than the YCLIENTS card set now visible. The risk is silently attaching an earlier/later purchase or counting an erroneous duplicate card.

## Evidence order

1. Start from the distinct source sale row: purchase date, course, source group quantity, source individual quantity, email, normalized phone, Telegram.
2. Search all subscription statuses and load detailed history for every plausible group/individual card.
3. For each card family, inspect:
   - exact card title and consultation type;
   - card creation and `Продажа` date;
   - write-offs;
   - balance changes;
   - expiry changes near the requested sale;
   - client-level visits only as a reconciliation aid.
4. Keep a card outside a ±45-day date window only when a balance addition, expiry change, or other lifecycle event near the sale proves reuse. Date proximity alone is not proof.
5. Exclude a later/earlier card when its own `Продажа` and usage clearly belong to another purchase. Add a sheet note naming the excluded card date and the retained evidence.

## Repeated edge cases

### Common delayed migration/import batch

For older sales, many clients can receive semantically matching card families on the same later date because subscriptions were imported or migrated in bulk. A card created after the sale is not automatically a separate purchase when:

- the delay pattern repeats across many clients from the same source period;
- the title and group/individual quantities match the source course;
- the card history has no competing later purchase evidence;
- its lifecycle reconciles to the source or documented balance changes.

Treat this as cohort-level evidence and retain the family when the row-level evidence also fits. In contrast, exclude an isolated later card whose own `Продажа` date, course family, or usage clearly identifies a separate purchase. The usual ±45-day heuristic is a triage signal, not a hard cutoff.

### Later individual card with source individual quantity 0

If the source sale is group-only and an individual card was sold months later, exclude the individual family even when client-level visit counts include its visits. Recompute the row from the retained group card and note the exclusion.

### Old card with no reuse event near the sale

An old untouched card is not evidence for the requested-month sale. If no relevant family remains after checking email, phone, Telegram, local index, and all statuses, use the approved whole-row missing-subscription exception: zero all quantities, red row, and an explanatory note.

### Duplicate or replaced group/individual card, one retained

Apply this rule symmetrically to group and individual card families. Exclude a manually zeroed duplicate only after a separate retained working card is proven by positive balance and both cards independently reconstruct the same source quantity as `used + balance + decreases − increases`. The zeroed card may have write-offs before its remaining balance was moved; once the retained card independently reconstructs the source, the zeroed card still contributes zero quantity, attendance, balance, overdue, and manual changes.

Keep the source quantity as the initial base and calculate the report only from the retained card's lifecycle and its own manual changes: effective quantity is `source − retained decreases + retained increases`. This avoids treating duplicate cancellation as a real decrease while preserving a documented transfer/addition on the working card. Require one unambiguous retained card per family. If every plausible card was manually reduced to zero, do **not** restore the source quantity under this rule: no retained card remains. Do not let a cancelled duplicate turn an otherwise active row into `Обнулен` or inflate manual-decrease totals. Add a note naming retained and excluded card IDs.

### Split-card internal transfer, both sides excluded

A different pattern occurs when a source quantity was split between two cards and then one part was transferred into the retained card. Exclude **both** mirrored manual operations only when all gates hold: the retained card's current lifecycle equals the source quantity; retained pre-transfer quantity plus cancelled-card pre-transfer quantity equals the same source; equal opposite balance changes occurred on the same date; and the cancelled card's current lifecycle is zero. Example: source 20, retained card `14 → 20` (`+6`), cancelled split card `6 → 0` (`−6`). Report quantity 20 and manual changes `0/0` because the pair is an internal transfer, not a new entitlement or real reduction. If any amount, date, source, or lifecycle gate fails, preserve the manual changes and escalate the row instead of auto-classifying it.

### Unequal cross-family conversion with evidence-only manual changes

A course conversion can zero an old card in one family and enlarge a retained card in another family by a **different** amount on the sale date—for example, old individual `6 → 0`, retained group `5 → 14`, plus a new individual card on 2. This is not the equal mirrored-transfer case above.

Handle it only when the dated operations, course change, and current source row jointly prove the conversion:

1. Exclude the old card from the current row's lifecycle, attendance, status, and expiry so its obsolete title/date cannot contaminate the new course.
2. Keep the current retained/new cards as the only lifecycle cards and require their current group/individual totals to reconcile to the current source quantities (or an explicitly documented lifecycle floor).
3. Preserve the excluded old card's dated decrease as **evidence-only manual change** in its original family, and preserve the retained card's increase in its current family. Do not let evidence-only changes alter selected-card balances or expiry.
4. Apply the normal anti-double-count rule: if the source already equals the selected current lifecycle, keep that lifecycle even though the manual columns show the historical conversion operations.
5. Require exact card IDs, transition date, old/new amounts, and a sheet note describing why one card is lifecycle-excluded but its manual event is retained. Any drift must fail closed.

### Detailed card history versus aggregate visits

The selected card's detailed `Списание` history is authoritative for attendance. Aggregate client visits can include other cards. Keep the detailed count and add a note when aggregate visits disagree; never force attendance to the aggregate count.

When a prior/later card is explicitly excluded, its visits may still remain in the client-level aggregate. Treat this as a narrowly evidenced mismatch, not a global tolerance:

- store an exact row-specific tuple `(selected group write-offs, aggregate group visits, selected individual write-offs, aggregate individual visits)`;
- accept it only while the exact excluded card locator(s), sale date/course evidence, and explanatory sheet note still match;
- require the mismatch to be in the family whose excluded card explains the extra aggregate visits;
- fail closed if the tuple changes, the excluded card disappears, or no excluded card remains;
- also fail a stale allowlist entry when selected write-offs and aggregate visits become equal again.

This keeps unrelated-card visits from inflating the requested sale while ensuring the exception cannot silently broaden to future data.

### Source quantity exceeds visible lifecycle

If source quantity is positive but the selected card shows fewer attended + remaining + overdue units, preserve the source quantity unless history proves an adjustment or another purchase. Document the gap. The main block may expose it through `Нереализованные`; package rows must still reconcile exactly because they have no unrealized row.

### Intermediate export quantity

The export may already include additions but precede a later decrease. Compare source against current lifecycle, reconstructed original, `source − decreases`, and `source + increases` before applying manual changes. Example pattern: source 8, later decrease 1, current lifecycle 7; effective quantity is 7, not 9.

## Identity and storage gate

Never key audit or apply results only by email. Use a stable per-sale identity such as source row/sale ID plus purchase date. Duplicate emails, corrected emails, malformed emails, or two purchases by one client must remain separate records. Before writing, assert:

- checkpoint offsets cover every source sale exactly once;
- main count + package count equals source count;
- no source identity is duplicated or missing;
- every exception note is attached to the intended sheet row.

## Final verification additions

Alongside formulas, dates, colors, and status checks:

- list rows where effective quantity differs from visible lifecycle;
- require a note for every non-zero unexplained gap;
- verify `Обнулен` uses positive net decrease per available family and row-level quantity reconciliation;
- verify excluded card families contribute zero attendance, balance, overdue, and manual changes;
- verify package quantity equals attended + remaining + overdue exactly.
