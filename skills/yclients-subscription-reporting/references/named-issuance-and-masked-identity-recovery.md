# Named issuance, masked identity, and timeout recovery

Use this reference for one-client named subscription issuance and read-only consultation counts when YCLIENTS exposes only a masked phone.

## Exact Telegram alias resolution

1. Do not infer a client from the public API `clients/search` response: the configured helper requests only `id`, `phone`, and `email`, and the API may not return Telegram aliases or may ignore guessed search-body fields.
2. Search the authorized local YCLIENTS client snapshot for the exact alias in `name` / `display_name`. Require one exact match and retain the resulting client ID, email, and masked phone as identity evidence.
3. If the alias is absent from both the live fields and the local snapshot, stop and ask for an exact email or phone; never pick a likely Roman/Anna/etc. by name.

## Masked-phone read-only fallback

- Normalize a displayed masked phone only for a read that has already been proven to resolve to the exact client; never reconstruct missing digits.
- A phone-level active-card endpoint can return an empty list for a masked number. Treat that as an incomplete read, not as “no subscriptions”.
- Use known card IDs from an authorized ledger or processed-source artifact, then read each card through the full-network endpoint with `abonements_ids=<exact_id>` and follow `goods_transaction_id` to the goods transaction. Accept the card only when the transaction proves the exact client ID, expected good/title, and document linkage.
- Report the live balance and expiry from the exact-card response. State separately if the evidence proves only a specific family (for example, one group card) rather than a complete all-status inventory.

## One-client issuance gate

- Exact email/Telegram identity, fresh target-family history check, live good/type linkage, narrow ledger, post-write card readback, and an idempotent zero-write rerun are required.
- A successful sale initially creates a standard card balance (often 12) and the requested quantity is then applied with `set_balance`. Verify the final balance is exactly the requested quantity; do not interpret the standard initial balance as the requested result.

## Timeout / interrupted-write recovery

If an issuance command times out after saving `stage=issuing` or after creating the goods transaction:

1. Do not rerun the issuance command.
2. Inspect the ledger and use the saved transaction/card metadata plus full-network exact-card proof to determine whether the card was created.
3. If the exact card belongs to the intended client and good and still has the standard initial balance, run only the missing balance setter on that card.
4. Read the exact card back, verify the requested final balance, unchanged intended validity, and ownership; mark the ledger recovered/completed.
5. Run the recovery executor again and require `writes=0`.
6. If any state differs from the saved before-state or exact target-state, stop as a conflict instead of issuing or correcting blindly.

This pattern prevents duplicate cards after a timeout and preserves a verifiable transaction/document/card chain.
