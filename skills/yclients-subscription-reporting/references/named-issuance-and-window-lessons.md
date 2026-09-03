# Named issuance and recent-window lessons

Reusable notes from recent YCLIENTS issuance workflows. Keep these details behind the class-level skill; do not copy them into one-off scripts without adapting the dates, client identity, and good/type mapping.

## Package-course quantity is mapping-authoritative

For the explicit package course names, use the mapping file as the source of truth:

```text
Пакет консультаций 3 -> Консультации (3 шт.), quantity 3
Пакет консультаций 5 -> Консультации (5 шт.), quantity 5
Пакет консультаций 8 -> Консультации (8 шт.), quantity 8
```

Do not let a contradictory technical `userCourse` quantity override the mapping. A real `Пакет консультаций 3` sale can expose `kolPersonalConsultations=1`; it still plans 3 package consultations. Validate the exact course name and group quantity, verify the live good/type linkage, and keep the package type's configured validity. This rule is specific to package course names; ordinary courses continue to use their source group/personal quantities.

## Apply Telegram overrides before source-client construction

When the sales row has a blank `tgUsername` but the user provides an exact email→Telegram override, apply the normalized override to a copied/in-memory source user before calling `build_source_client` or client-provisioning helpers. Applying it only after the helper runs can trigger a false “source contacts incomplete” guard. Preserve the original raw sale separately for provenance, and record the override as user-confirmed identity evidence.

## Scope late named overrides

If a period was already applied and a later exact override unlocks one skipped sale, do not invoke the entire period apply if other newly ready sales are present. Re-read the sale by stable `purchaseID`/sale reference, run a one-sale scoped executor, and leave unrelated ready sales pending. The period's cumulative ledger must still recognize the new operation on the next zero-write run.

## Inclusive recent windows

For `N` calendar days, calculate:

```text
start = today - (N - 1) days
end = today
API purchaseDateTo = end + 1 day  # exclusive
```

For example, a request on 24 August for the last 10 days covers 15–24 August inclusive. Always obtain `today` from the live system clock. Keep the exact period in the ledger filename and assert every returned `purchaseDate` and `purchaseID` falls inside the period.

## Exact overrides are period-scoped

An email→Telegram override is valid only when the normalized email appears in the selected source window. Do not pass a historical override map wholesale to a strict builder that rejects absent emails: first collect/filter the selected sales, then apply only the matching overrides. This prevents a nickname from being attached to an unrelated sale and avoids turning an expected “not in this window” condition into a failed run.

## Source drift between dry-run and apply

If the sales API count or stable sale identities differ between dry-run and apply, treat the apply as unsafe and stop before mutation. Compare the old and new source snapshots, update/rebuild only the period ledger metadata after confirming the changed rows, and rerun the apply from the verified snapshot. Never retry issuance blindly after a source mismatch.

After mutation, verify every ledger operation independently through:

1. exact card ID and type title;
2. target balance and expiry;
3. card `goods_transaction_id`;
4. goods transaction `client_id`, `good_id`, and `document_id`.

Then run the identical executor again and require `0 writes`.

## Explicit “new card” exception

The ordinary bulk policy skips an existing equivalent card and never tops it up. A later explicit command such as “issue a new one” changes only that named request: create a separate scoped executor, preserve all existing card IDs, and never mutate them. Select the new card from the before/after active-card ID difference; do not select it by nearest creation date or by the first card returned.

Classify families by exact live type title. `ПИМ (Индивидуальная)` and standard `Индивидуальная консультация` are distinct types/goods; a user may explicitly request a new standard card while an existing PIM card remains untouched. For a new standard individual card, the special good may issue with a default balance larger than requested (commonly 12); set the requested absolute balance only on the newly created card, then set the requested period using the workflow’s period inference and verify the exact date.

## Preflight and recovery checklist

- exact live identity: email/phone/Telegram resolves to one client ID;
- live target-family history: scan all card pages and prove ownership through each target card’s goods transaction; do not trust a phone/client-filtered list as full history;
- live good title ↔ `loyalty_abonement_type_id` linkage is unique;
- ledger is persisted before each mutation stage;
- if an issuance times out, treat the side effect as unknown, recover by transaction/card ownership, and never reissue;
- final readback and zero-write rerun are mandatory.

A preflight failure caused by a local wrapper’s wrong CLI arguments is not a YCLIENTS result: inspect the actual builder entrypoint and its accepted flags before retrying. In the established mass workflow, the builder uses `--start`, `--end`, and repeated `--telegram-override EMAIL=@USERNAME`; the mass runner is then configured with the same period and filtered overrides.
