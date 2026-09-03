# Dynamic purchase-window source drift

Use this reference for any purchase-date bulk window (`N` days/weeks), especially when the FF sales source can receive new purchases during a long dry-run/apply sequence.

## Window and source invariants

- For `N` inclusive calendar days: `start = today - (N - 1 days)`, `end = today`; send `purchaseDateTo = end + 1 day`.
- Reassert every returned `purchaseDate` is inside the interval, every `purchaseID` is non-empty, and purchase IDs are unique.
- Persist a period artifact with the exact interval, source row count, sorted purchase-reference set, and exact override set used.

## Dry-run/apply drift gate

1. Run the read-only dry-run and save the source count plus sorted purchase-reference set.
2. Before apply, refetch the same interval and compare both count and purchase-reference set.
3. If the source changed, stop before YCLIENTS writes. Do not blindly rerun a stale apply and do not overwrite a completed ledger.
4. Classify the delta:
   - **Safe append:** only new purchase IDs appeared, all prior IDs and their source fields are unchanged, and each new row is inside the exact window. Rebuild the artifact including the append, preserve completed operation keys, and update only the period snapshot metadata after the append is independently verified.
   - **Unsafe mutation:** any prior purchase disappeared, changed email/phone/course/quantity/date, IDs duplicated, or the period/override set changed. Rebuild the whole dry-run and require a fresh review; do not mutate until the new plan is verified.
5. After a safe append, rerun the executor with the same exact override set. The ledger must retain all prior completed operations and add only newly eligible `(purchaseID, target type)` operations.
6. If the executor reports `existing ledger belongs to another period or source snapshot`, treat it as a correct safety stop. Inspect and compare the source snapshot; update the ledger metadata only after proving a safe append. Never edit the ledger to force an arbitrary count.

## Override and final verification rules

- Telegram overrides are exact `EMAIL=@USERNAME` bindings. Use the identical set for dry-run, apply, and zero-write verification; never broaden or infer an alias.
- An override fixes identity only. It does not fix a source row with zero consultation quantity, an existing active subscription, or a missing/ambiguous course mapping.
- After apply, independently verify every new card through exact card ID → card type/balance/expiry → `goods_transaction_id` → goods transaction client/good/document. For mixed sales, `before_card_ids` may contain a card from another family issued earlier in the same sale; verify no before-card has the target type before calling it a duplicate.
- Rerun the identical executor with the same source interval and override set. Require `ready_sales=0`, `planned_issue_new=0`, `planned_topups=0`, `failures=[]`, and `yclients_writes=0` for the completed portion; report unresolved exceptions separately.
