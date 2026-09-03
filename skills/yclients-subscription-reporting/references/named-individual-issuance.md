# Named individual abonement issuance

Use this procedure for a direct request such as “issue one individual consultation to `@username`”. It is a scoped write, not a bulk top-up.

## Gates

1. Resolve the Telegram username exactly. A local sales/snapshot row is a candidate only; prove the live YCLIENTS identity by exact normalized email and full normalized phone, requiring one client ID. Persist the username→email override only when the user explicitly supplied it.
2. Read the target family through the fresh all-status loyalty-card source, including expired/exhausted cards. An active-card API list is not a substitute: it can omit historical cards. A historical snapshot can support identity and prior evidence but cannot prove that no target-family card was created after the snapshot. If a fresh all-status read is unavailable, stop before mutation.
3. Classify families by the live card/type title. A group card does not satisfy or block an individual request. Require the target individual family to be absent in all statuses; keep other families unchanged.
4. Validate the special inventory good and abonement type independently: compare `good.title` and `good.loyalty_abonement_type_id` with the unique abonement type’s direct `type.title`/`id`. Do not filter type metadata with a card-title helper that expects a nested `type` object.

## Write and recovery sequence

1. Persist a narrow ledger containing exact client ID, target family, good ID, requested quantity, and before-state.
2. Issue the special good, never a loyalty-card type endpoint. Save `document_id` and `goods_transaction_id` immediately.
3. Find the created card by goods transaction ID, then prove `card.goods_transaction_id → goods transaction.client_id + good_id`. Do not trust a phone-level list alone.
4. Standard individual goods may create with a default balance larger than requested. If the default is not the requested quantity, set the exact absolute target balance only after transaction ownership is proven. Reject any unexpected third balance; never top up an existing target-family card.
5. Re-read the exact card and transaction. Require exact title, target balance, active status, client ownership, good ownership, and the configured default validity unless the user requested another expiry.
6. Rerun the identical executor. It must report `0 writes`; a completed ledger is not sufficient without this idempotent check.

## Common failure modes

- Treating a current group card as evidence that an individual card is absent or present.
- Accepting an empty active-card response as “no subscription” without the all-status toggle/endpoint.
- Assuming a package/good issues with the requested balance; verify and correct the absolute balance after issue.
- Reissuing after a timeout or card-discovery delay; recover from the saved transaction and card history instead.
- Using a generic title helper on abonement-type metadata, where the title is a direct field.
