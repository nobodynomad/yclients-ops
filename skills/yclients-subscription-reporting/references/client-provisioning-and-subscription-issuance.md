# YCLIENTS client provisioning and subscription issuance

Use this reference for commands such as “add subscriptions to new clients from the last two weeks.” This is a **write workflow** and must remain separate from reporting-only reconciliation.

## Safety model

Use a staged transaction:

1. **Read-only discovery** of period sales, client matches, configured subscription types, and existing cards.
2. **Dry-run** containing every planned client creation and subscription issuance plus exceptions.
3. Obtain explicit approval for the dry-run.
4. Run a one-client pilot first when the mapping or API permission has not already been proven.
5. Execute idempotently, then re-read every created object.
6. Return an audit log with created, skipped, ambiguous, failed, and partially completed items.

Never combine discovery and mass writes in one opaque run. Never delete a client/card to repair a provisioning mistake without a separate explicit approval.

## FF sales API source

For this user's current sales feed, use `POST https://ff-bot.com/ffapi/sales/list`. Read the key from `/home/hermes/.hermes/secrets/ff_sales.env` (`FF_SALES_API_KEY`) and send it only as the JSON `apiKey`; never print it or put it in source code.

Request pagination explicitly with `page` and `perPage` (50 is the documented/default safe page size). Optional filters include `search`, `purchaseDateFrom`, `purchaseDateTo`, `potokID`, and `trudoustroilsya`. The current FF response envelope stores rows under **`sales`** (not `data`) and includes `total`, `page`, and `perPage`; assert the envelope keys before treating a zero-length row list as a real empty result. Preserve `userCourse.purchaseID` as the stable per-sale identity and paginate until collected rows equal the response `total`.

The response exposes the downstream fields needed for provisioning:

- `userCourse`: `purchaseID`, `courseID`, `purchaseDate`, `startCourseDate`, group/personal consultation quantities, `ifVozvrat`, and lifecycle fields;
- `user`: name components, full phone, email, Telegram identity, and optional `yclientsClientID`;
- `course`: stable course ID, human-readable `name`, and course metadata;
- `rezhim`: mode ID/name and `potokID`;
- `potok`: flow ID and flow metadata.

Important gates:

- The user requires commands such as “last two weeks” to use **`userCourse.purchaseDate`**. The live `purchaseDateFrom` / `purchaseDateTo` filter has been proven against a historical sale whose purchase and course-start dates differ.
- `purchaseDateTo` is an **exclusive** upper bound. For a user interval ending on date `D` inclusively, send `purchaseDateTo = D + 1 day`, then assert every returned `purchaseDate` lies inside the requested inclusive interval.
- The enriched response returns `course.id` and `course.name`; require `userCourse.courseID == course.id` and map from the human-readable course name plus stable ID to approved YCLIENTS types.
- `rezhim` and `potok` are returned and linked by `userCourse.rezhimID -> rezhim.id` and `rezhim.potokID -> potok.id`. Consultation-package sales may legitimately return both objects as null.
- The server-side `potokID` filter is verified: every returned row must have the requested `potok.id`; an unknown flow should return zero rows. Combine it with purchase-date bounds whenever the user specifies both period and flow.
- For this workflow, process every source row returned for the requested purchase-date/flow selection. Do not require a separate payment-status confirmation and do not skip solely because `ifVozvrat=true`; the user explicitly chose to ignore return/payment filtering for issuance.
- Treat `user.yclientsClientID` only as a matching hint; re-read that client and verify phone/email before trusting it.
- Never print raw sale/user payloads. Probe and dry-run outputs should contain counts, field presence, and masked contacts only.

## Source ingestion

- Apply the user-requested interval to the **purchase date** before querying the full client base. Define the interval explicitly (inclusive bounds and timezone).
- Prefer a durable API-accessible source or automatically refreshed table. A manually exported CSV or dated spreadsheet snapshot is usable only after checking its freshness and maximum purchase date.
- If a dashboard export is protected by an interactive anti-bot challenge, do not treat screen scraping as a production dependency. Use a user-assisted export or arrange a stable upstream table/API.
- Preserve a stable sale identity (sale/order ID when available; otherwise source row + purchase timestamp + normalized contact + course). Do not deduplicate by email alone.
- Require the fields needed downstream: purchase date, course/product, name, full phone, email when available, and any purchased group/individual quantities. Rows without a usable phone cannot be created by the official client endpoint and belong in exceptions.
- Clarify whether the source already excludes failed, cancelled, refunded, test, and duplicate payments.

## Read-only capability probes

Authenticate as documented by YCLIENTS without logging tokens. Probe the actual branch before each pilot:

- `GET /api/v1/user/permissions/{company_id}` — inspect client and loyalty permissions.
- `POST /api/v1/company/{company_id}/clients/search` — current client search.
- `GET /api/v1/company/{company_id}/loyalty/abonement_types/search` — configured subscription types.
- `GET /api/v1/loyalty/abonements/?company_id={id}&phone={full_phone}` — active subscriptions.
- `GET /api/v1/chain/{chain_id}/loyalty/abonements` — historical/full duplicate check when the integration has the separate network permission.

A 200 from client search or subscription-type listing does not prove that write operations are allowed. The public API has no documented dry-run for client/card creation, so prove write access with an approved one-client pilot.

If the active-only endpoint works but the network history endpoint does not, do not claim complete duplicate protection. A recently issued card may already be exhausted and omitted. Either obtain the missing permission, use an authorized all-status source, or flag the limitation in the dry-run.

## Official write operations

### Create a client

`POST /api/v1/clients/{company_id}`

The official schema requires at least:

- `name`
- `phone`

Optional fields include surname, patronymic, email, comment, categories, and custom fields. Normalize phone to full digits including country prefix. Search first by normalized phone, then email; ambiguous duplicate profiles must not be resolved silently.

### Issue a subscription through its linked special good

Do **not** send a subscription-type ID to `POST /api/v1/loyalty/cards/{company_id}`. That endpoint accepts loyalty-card types, not abonement types; a live attempt with an abonement-type ID returned HTTP 400 `Указан недопустимый тип карты` and created no object.

YCLIENTS issues/sells an abonement as a special inventory good. Use the public storage-operation API, one abonement per sale transaction:

1. Read the exact abonement type from `GET /api/v1/company/{company_id}/loyalty/abonement_types/search`.
2. Read its linked special good from `GET /api/v1/goods/{company_id}/{good_id}` and verify `good.loyalty_abonement_type_id == abonement_type.id`, exact title, code policy, and price. Do not trust a stale hard-coded `good_id` without this live linkage check.
3. Create a sale document with `POST /api/v1/storage_operations/documents/{company_id}` using `type_id=1`, the verified branch storage ID, current `create_date`, and an idempotency/audit comment.
4. Create exactly one transaction with `POST /api/v1/storage_operations/goods_transactions/{company_id}`. Required fields are `document_id`, linked `good_id`, `amount=1`, `cost_per_unit`, `discount=0`, resulting `cost`, and `operation_unit_type=1`; include the exact existing/created `client_id`. Omit `good_special_number` only when the live good/type allows an empty code.
5. Re-read active abonements, identify exactly one new ID by before/after difference and exact type, and persist the document, goods-transaction, and abonement IDs immediately. Independently verify each new abonement ID against the full-network endpoint one ID per request; the live API has returned only one row when two comma-separated `abonements_ids` were requested together.

For the local `LiveYClients` helper, the exact issuance signature is `issue_card(phone, good_id)`. Do not pass `(good_id, type_title)` or `(type_title, good_id)`; cover the argument order with a fake-API regression test before adding a new issuance executor. The exact type is verified from the good linkage before the write and from the new-card readback after the write.

Count audit writes accurately: a new abonement with non-default balance and period performs four public write requests—sale document, goods transaction, `set_balance`, and `set_period`. Creating a new client adds one more write. If a default already equals the requested balance/period and its setter is skipped, decrement the count accordingly.

If document creation succeeds but the goods transaction fails, delete only that newly created empty document through the documented DELETE endpoint and record the cleanup. Never delete a successful transaction/abonement as an automatic repair.

For the current Formfactor branch, the live pilot verified storage `2255377` and the linked special goods `36892736` for `Индивидуальная консультация`, `34799717` for `Групповая консультация`, and `35724237` for `Консультации (8 шт.)`. The package-8 good was recovered from a known exact card's `goods_transaction_id` → goods transaction `good_id`, then revalidated against the exact title and `loyalty_abonement_type_id`. Re-read each good and its `loyalty_abonement_type_id` before every future write because configuration can change.

The selected subscription type controls the initial validity period and balance. The documented sale-document and goods-transaction schemas have **no fields for abonement balance, expiration date, or period**, so variable values cannot be supplied atomically at issuance through the public API. If the configured type defaults already equal the requested values (for example fixed 3/5/8 package balances and retained package validity), skip unnecessary edit calls. Otherwise the only documented path is issuance with defaults followed by separately audited `set_balance` and/or `set_period`; these operations appear in abonement history. Do not create dynamic one-off types merely to hide history because that pollutes type catalogs, goods, inventory, and reporting. If history-free variable issuance is required, ask YCLIENTS support whether the account has a private/partner capability; do not guess an undocumented endpoint.

For approved non-default values, use and verify separately:

- `POST /api/v1/chain/{chain_id}/loyalty/abonements/{abonement_id}/set_period`
- `POST /api/v1/chain/{chain_id}/loyalty/abonements/{abonement_id}/set_balance`

Do not call these methods without an approved rule and an immediate read-back check.

## Course-to-subscription mapping

Maintain an explicit allowlist, preferably in a versioned config:

```text
source course -> [subscription type title(s)] + issuance conditions
```

Conditions may depend on purchased group/individual quantities. A course can issue zero, one, or multiple cards. Never infer mappings solely from similar titles or fixed balances. Treat unknown/new course titles, renamed types, duplicate type titles, and placeholder/test types as exceptions.

Before enabling bulk writes, have the user demonstrate at least one manual example for each structurally distinct family:

- course with group + individual cards;
- individual-only course;
- consultation package 3/5/8;
- combination/upgrade course;
- guarantee/support variant.

Record whether validity starts at purchase or issuance, whether balances are ever changed, and what client name/comment/category conventions are used.

### Confirmed allowlist and quantity rules

For this user's provisioning workflow, use **only** these exact YCLIENTS subscription type titles:

- `Индивидуальная консультация`
- `Групповая консультация`
- `Консультации (3 шт.)`
- `Консультации (5 шт.)`
- `Консультации (8 шт.)`

The executable mapping is stored at `/home/hermes/.hermes/yclients-data/course_subscription_mapping.json`.

For every ordinary course:

- if `userCourse.kolPersonalConsultations > 0`, map `Индивидуальная консультация` to that exact issuance quantity;
- if `userCourse.kolGroupConsultations > 0`, map `Групповая консультация` to that exact issuance quantity;
- when both are positive, plan both new-card operations only for an eligible zero-history client;
- never issue a zero-quantity family and never add these quantities to an existing balance.

Exact package exceptions:

- `Пакет консультаций 3` -> `Консультации (3 шт.)`, quantity 3;
- `Пакет консультаций 5` -> `Консультации (5 шт.)`, quantity 5;
- `Пакет консультаций 8` -> `Консультации (8 шт.)`, quantity 8.

**Current user policy:** never top up an existing YCLIENTS subscription. If any card/subscription appears in complete network history, skip the sale without changing the balance, period, or client fields. Issue an approved type only for a new client or an exact existing client whose complete network history proves zero prior subscriptions. If zero history cannot be proven, stop for manual review. A missing matching type is not sufficient when another card exists.

Issuing a type uses its configured default balance (12 individual, 14 group, and 3/5/8 for packages). Exact non-default issuance quantities require `POST /api/v1/chain/{chain_id}/loyalty/abonements/{abonementId}/set_balance`, whose body sets the **absolute resulting balance** through `united_balance_services_count` (with `services_balance_count: []`). Use `set_balance` on an existing card only for an explicitly approved correction/rollback, never as an inferred sale top-up. The Marketplace system user's token lacks network membership, but the ordinary owner's User Token has verified Formfactor network access plus balance-edit, period-edit, history, manual-transaction, and storage-sale rights. Read that token from the separate mode-600 owner secret; never expose or merge it into source code. The approved one-client pilot proved the complete official sequence: sell each linked special good separately, identify the new abonement ID, set exact issuance balance, derive/set duration, read back exact expiration, and rerun idempotently with zero additional writes.

Confirmed client/card handling:

- For a missing client, create `name` as source first name plus ` @telegram_username`, and pass normalized source phone/email. The fixed branch/salon is Formfactor.
- For an existing exact, non-conflicting client match, first prove complete zero subscription history. Only then may validated nonempty sale fields be synchronized before issuing a new card. If any history exists, do not update the client. Never erase a populated YCLIENTS value because the source field is blank; never overwrite conflicting phone/email matches automatically.
- Before updating any existing eligible client, persist the complete original `name`, `phone`, `email`, and `last_change_date` in the rollback ledger. The public `GET /api/v1/client/{company_id}/{id}` has no field-history endpoint, so `last_change_date` alone is insufficient for rollback. For provenance questions, also check comments and `GET /api/v1/records/{company_id}?client_id=...&with_deleted=1`; if no record/comment exists, do not infer provenance from numeric ID.
- If either source name or Telegram username is absent, do not degrade or erase an existing name; report the missing source field. Treat missing phone/email or conflicting client matches as exceptions.
- For a newly issued ordinary individual/group subscription, use `userCourse.gracePeriodEndDate` as the required expiration target. If it is missing or not in the future, do nothing and report. The official `set_period` API accepts duration plus unit, not an absolute date, so derive whole days from the read-back activation date, apply them, and verify the rendered expiration exactly.
- For `Консультации (3 шт.)`, `Консультации (5 шт.)`, and `Консультации (8 шт.)`, never call `set_period`; retain the type-configured validity.
- For a direct ordinary-type command not tied to a source grace date, ask for expiration before any write.
- Existing positive, exhausted, expired, duplicate, or otherwise historical cards are all read-only policy skips unless the user explicitly orders a named correction.
- Maintain a durable local idempotency ledger keyed by `(purchaseID, target subscription type)`, and a separate rollback ledger for any correction. Completed rollback keys must be removed from business-completed counts.

## Idempotency and partial failure

For each sale:

1. Resolve exactly one client candidate or mark ambiguous.
2. Check whether the target card already exists for this sale/type/time window.
3. If the client is absent, create it and persist the returned client ID immediately.
4. Re-search/read back the client before selling an abonement.
5. Sell each mapped linked special good one at a time; persist the sale-document ID, goods-transaction ID, and returned abonement ID.
6. Re-read active/full abonement sources and verify type, phone owner, creation time, balance, period, linked goods transaction, and client ID.

If client creation succeeds but issuance fails, report a **partial completion** and retry only the missing issuance. Never recreate the client. If one of several cards succeeds, retry only the missing card IDs/types.

**Eventual-consistency recovery:** after `goods_transaction` succeeds, the new abonement may exist in the full-network endpoint but remain temporarily absent from `GET /loyalty/abonements/?phone=...`. Persist `api.last_issue_meta` (document and goods-transaction IDs) in the outer exception handler whenever the operation is still `issuing`. Never repeat the sale transaction merely because phone read-back returns zero. Query full-network abonements for the narrow creation interval, identify the one new exact-type card, then verify card `goods_transaction_id` -> transaction `client_id/good_id/document_id` -> document comment/sale-ref. Persist the recovered card ID before applying only missing balance/period setters. Count the already-created document+transaction in cumulative writes.

### Scope contraction and named overrides

- Treat the newest scope as authoritative at once. If “all clients” becomes “only Natalia,” mark every other pending operation cancelled and rebuild the dry-run/ledger from that single identity. Do not execute an earlier approved or “safe” subset after the contraction, even if its preflight already succeeded.
- A named user correction can override the ordinary no-top-up/no-contact-conflict policy only for the exact facts the user resolved. Use a separate executor or override mode allowlisted by stable sale ref, client ID, card ID, exact type, and absolute before/target values. Keep the global planner/executor policy unchanged.
- If the user supplies a missing Telegram username for a specific source sale, bind the override to the exact normalized source email and selected period. Reject an override email absent from the selected source, reject a conflicting nonempty source username, and apply the identical override set to dry-run, executor, and independent verifier. Record only masked identities/counts in general artifacts; do not silently edit the upstream sales feed or broaden the override to another sale.
- If the user confirms a specific client/card while also requesting a contact correction, treat the two writes as separately resumable stages (`contact_updating → contact_verified → balance_updating → completed`). Save full original protected client fields and the selected plus related-card snapshots before the first write.
- Verify exact cards from the full-network endpoint one ID per request and prove `goods_transaction_id → transaction.client_id`; phone-level active-card responses are discovery aids, not sufficient ownership proof for a named correction. Assert exact type titles. Avoid the Python filter bug `str(title == expected)`, because non-empty `"False"` is truthy; use `str(title or "") == expected` and cover classification with tests.
- Idempotent recovery allows only live `before` or live `target`. Any other email/balance/expiration is a divergence requiring review. A completed ledger key must short-circuit before writes, and an independent verifier must prove excluded clients were untouched when the user narrowed scope.

### Named existing-client card issuance

Use this narrower flow when the user names an existing client and asks to add a specific consultation quantity, even if the ordinary bulk policy forbids top-ups:

1. Resolve the client through an exact stable identity set: exact Telegram username from the authorized source/audit plus exact YCLIENTS email and/or full normalized phone. Require the live email/phone search to resolve to exactly the approved client ID; never use a first search result or wildcard alias.
2. Read a fresh client-specific all-status/all-card snapshot before writing. The snapshot must prove whether the requested target family exists in any status. A different active family does not satisfy the requested target: for example, an active `Групповая консультация` card does not justify topping it up when the user asks for `Индивидуальная консультация`.
3. Reconcile the all-status snapshot with the live active-phone read. If the target family is absent from both, an explicit named request may issue a **new** target card for that exact client. Do not generalize this exception to bulk issuance and do not mutate another family.
4. Validate the exact title and linked special good live immediately before the write: `good.title == target_title` and `good.loyalty_abonement_type_id == abonement_type.id`. A stale good ID or a similar title is not enough.
5. If the user specifies only a final quantity and no expiry, issue the standard configured type, set the new card's absolute final balance to that quantity, and leave the configured period/expiration unchanged. If the user specifies an expiry, derive and verify the period separately; never silently invent a target date.
6. Persist a narrow allowlist/ledger before writing: client ID, exact contacts, target title, good ID, final quantity, `period_changed=false` when applicable, and the pre-write card IDs/balances. The issue stage creates the sale document and goods transaction; identify the new card by before/after ID difference and exact type, then set balance and read it back.
7. Re-read the exact new card and verify ID, exact title, active status, final balance, expiration, goods transaction ID, and unchanged protected cards. A successful operation must return auditable IDs; a rerun must return zero writes and verify the same target state.

**Interrupted-write recovery gate:** if a side-effecting tool call is interrupted, emits an orphan-recovery warning, or returns an unknown execution state, do not retry the write immediately. First inspect the narrow ledger (if present) and re-read the exact client/card IDs from YCLIENTS. If the ledger is absent or incomplete, treat live state as authoritative: identify any newly created exact-type card through before/after IDs plus `goods_transaction_id → transaction.client_id/good_id/document_id`, then resume only missing balance/period setters. If the exact target state already exists, record the recovered IDs and perform zero further writes. Never repeat a sale document/transaction merely because the tool response was lost.

**Ambiguous destructive wording gate:** when a command combines an unambiguous new-card request with wording such as “забери/убери N групп” for an existing card, separate the scopes. It is permissible to preflight and execute the exact new-card request, but do not interpret the destructive clause yourself. Ask whether it means attendance/write-off, absolute balance reduction, deletion, or cancellation. After the user selects one, use a separate allowlisted correction with exact client ID, card ID, type, `balance_before`, absolute target, and protected-card snapshots; verify that only the selected balance changed, that expiry and attendance evidence were preserved, and rerun for zero writes.

API ownership pitfall: `GET /api/v1/chain/{chain_id}/loyalty/abonements` with only `client_id` or `phone` query parameters may return an unfiltered network-wide page (often with `client_id: null`). Never use that response alone to prove a client's card history. Use the client-specific all-status UI endpoint for discovery, and for an exact card readback prove `card.goods_transaction_id -> goods transaction.client_id/good_id/document_id` through the full-network endpoint one card ID at a time.

### Bulk execution controls

For an explicitly approved bulk period:

1. Parameterize the dry-run with inclusive `start`/`end` dates and derive the FF exclusive upper bound as `end + 1 day`; reject future or reversed ranges.
2. Build action totals only from final entries that have operations **and no exceptions**. Quantities describe new-card entitlements, never additions to existing balances.
3. Load all completed pilot, bulk, and rollback ledgers before planning. Partition by `(sale_ref, exact target type)` and subtract completed rollback keys from business-completed counts.
4. Enforce eligibility before any client sync: a new client is eligible; an exact existing client is eligible only after complete network history proves zero subscriptions. Any card/history or missing proof means read-only skip/manual review.
5. Snapshot the exact source sale-ref set and require it to match immediately before writes. Verify period, row count, unique purchase IDs, course, quantity, family, and expiration target.
6. Add two independent code barriers: the planner must never emit `top_up_existing`, and the executor must reject every action except `issue_new` before client synchronization or YCLIENTS writes.
7. Persist one mode-600 operation per `sale_ref::type` before every issuance stage. Persist complete original client fields before any eligible existing-client update.
8. For new issuance, persist stages `issuing -> issued -> balance_verified -> completed`, including before-card IDs, document ID, goods-transaction ID, abonement ID, period model, and target expiration. Resume from persisted linkage after network errors; never repeat document/transaction creation.
9. Independently verify exact client fields, every new active abonement balance/type/expiration, each new card via the full-network endpoint one ID per request, and linked transaction/document GETs. Verification performs zero YCLIENTS writes.
10. Re-run the executor. Clean idempotency is all completed issue keys skipped, zero client creates/updates, zero subscription writes, and zero failures. Rebuild dry-run: zero ready actions; issued cards are completed; existing-history sales are policy skips.
11. For a correction, first require every current balance to equal the persisted post-write value and every expiration to equal its pre-write value. Globally preflight all candidates before writes. Restore the exact persisted `balance_before` with a separate idempotent rollback ledger; unexpected current values are conflicts. Independently verify, then rerun rollback for zero writes.
12. Keep a cumulative final audit. If an API error happens after a write but before read-back, account for it from persisted linkage plus recovery evidence. Resume-state merges must preserve cumulative counters: never overwrite an earlier `writes=1` client-create result with a later read-only `writes=0` verification result. Use an explicit cumulative field or `max(previous_writes, current_stage_writes)` for a one-time stage, and cover this with a regression test.
13. Normalize source display names to the exact YCLIENTS storage model before client creation and readback comparison. Live evidence shows that the client API replaces non-BMP symbols (for example emoji) with `?`; apply that deterministic transformation before the write so recovery does not misclassify a successfully created client as a contact mismatch.
14. Package courses must resolve through an exact live `type title -> linked good -> abonement type` mapping. Do not overwrite package period/expiration after issuance: retain the configured type values, verify the issued balance plus configured `period`/`period_unit_id`, and require each new client's active card-ID set to equal the ledger's issued card-ID set exactly so extra duplicates cannot pass verification.

## Dry-run report

The approval artifact should show, without exposing unnecessary PII:

- requested interval and source freshness;
- sales count and distinct sale identities;
- existing clients / clients to create / ambiguous clients;
- planned cards grouped by source course and target type;
- already-issued cards to skip;
- missing phone/name, unknown course, duplicate sale, and permission exceptions;
- exact number of intended client creations and card issuances.

No write occurs until the user approves this artifact.

## Session-specific probe snapshot (2026-07-21)

Re-probe before relying on this snapshot; permissions and type settings may change.

- After the Marketplace app was disconnected/reconnected, branch permission flags changed successfully: `loyalty_cards_manual_transactions_access=true` and `loyalty_certificate_and_abonement_manual_transactions_access=true`. Client search, client contacts, active client subscriptions, and subscription types remained available.
- The company's `main_group_id` was confirmed as the expected Formfactor network ID, so the request was not using a stale/wrong chain identifier.
- `GET /api/v1/groups` returned 200 but zero accessible networks for the token's system user. A correctly formed full-network subscription request with a required creation-date range still returned 403 `Недостаточно прав`.
- Therefore branch scopes are now correct, but the Marketplace application's system user has no Formfactor **network** membership. Branch and network users/rights are separate in YCLIENTS.
- Important correction from the live UI: Marketplace system users are immutable and may have blank/disabled email and phone fields. The standard network action `Пригласить существующего пользователя` requires an ordinary YCLIENTS user email or phone, so an app system user with blank contacts cannot be invited that way. Partner-account contact details and Application ID belong to different entities and must not be treated as the system user's login.
- The public OpenAPI exposes no endpoint to add a system user to a network by internal user ID. Supported practical paths are: (a) authenticate with the User Token of an ordinary dedicated/owner YCLIENTS user who is present in the branch and Formfactor network and has network client/loyalty/manual-transaction rights, while retaining the application's Partner Token; or (b) ask YCLIENTS support to attach/enable the application's system user for the network. Official YCLIENTS API-access documentation explicitly supports calls through the User Token of an added user according to that user's rights.
- Prefer a dedicated least-privilege automation user over the owner's broad token. If the user explicitly chooses the owner, obtain its User Token through official `POST /api/v1/auth` (login/password and possible 2FA) using a single-use secure interactive flow; never request, paste, log, or retain the password in chat. Store the token in a separate mode-600 secret.
- Live owner-token verification on 2026-07-21: `GET /api/v1/groups` returned the Formfactor network, and network access flags for clients, loyalty, abonement balance edit, period edit, history, and manual transactions were all enabled. The full chain-abonement endpoint requires `created_after` and `created_before` in calendar format `Y-m-d`; numeric Unix timestamps are rejected as a missing interval. Pagination with `count=100` read 21 pages / 2,001 rows / 2,001 unique abonement IDs with no duplicate IDs or repeated pages. Re-probe before any later pilot because permissions and data may change.

## Historical probe snapshot (2026-07-20)

Re-probe before relying on this snapshot; permissions and type settings may change.

- Client search, client contact access, active-subscription reads, and subscription-type listing returned 200.
- Permission flags observed: client access enabled, loyalty access enabled, delete disabled, manual loyalty transactions disabled.
- Twenty subscription types were visible; all reported `is_allow_empty_code=true` at that time.
- The full network endpoint `GET /api/v1/chain/{chain_id}/loyalty/abonements` returned 403, so historical duplicate protection was not API-complete.
- The supplied DataLens public dashboard presented SmartCaptcha to the server browser. A dated Google Sheets export was available for schema inspection but was a snapshot, not an established live feed. Do not use it for a future period without a freshness check.
