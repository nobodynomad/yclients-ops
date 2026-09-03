# Yclients subscription API notes

## Tested authentication

Use:

```text
Authorization: Bearer <partner_token>, User <user_token>
Accept: application/vnd.yclients.v2+json
```

The Marketplace app must be active for the target salon before relying on its system user. Verify the actual report data routes, not a company-user route.

## Read-only probes that worked

- Clients: `GET /api/v1/clients/{company_id}?count=...&page=...`
- Client search: `POST /api/v1/company/{company_id}/clients/search` with a JSON body such as `{"count": 1, "page": 1}`.
- Current client subscriptions: `GET /api/v1/loyalty/abonements/?company_id={id}&phone={full_digits_phone}`.

Use the full digit phone including the Russian country prefix if returned by Yclients; stripping it to ten digits gave false empty subscription lists.

## Subscription values

The current-subscriptions response can return a misleading `balance_container.links[].count == 0` while its user-visible `balance_string` holds the actual remaining count, e.g. `Групповая консультация (x7)`. Parse `xN` from `balance_string` first; use the container only as a fallback.

For matching a sales export to subscriptions, match client by normalized email, then by normalized phone. Match subscriptions to a purchase by the nearest `created_date` within a conservative time window; preserve ambiguous or absent matches for reconciliation rather than inventing values.

## Important limitation to verify before bulk writing

The phone-based `/loyalty/abonements/` route returned active subscriptions but did not return a known expired subscription. The network endpoint `GET /api/v1/chain/{chain_id}/loyalty/abonements` may be required for historical/expired subscriptions and can require separate permission. Do not write `Нет абонемента` merely because the active-only route returns nothing. First obtain and test a source that includes expired subscriptions (or use an authorized browser reconciliation path).

## Authenticated UI fallback for expired and depleted cards

When the API card list is active-only or the chain route has insufficient permission, use an already-authorized Yclients browser session **read-only**. Opening the card's «Лояльность» tab and ticking «Показать все абонементы и сертификаты, включая просроченные и исчерпанные» triggers:

```text
GET /loyalty_cards/get_client_loyalty_cards_json/{salon_group_id}/{salon_id}/{client_id}/{full_digits_phone}
  ?show_all_statuses_abonements_certificates=1
  &show_redesign_view=false
```

The response is JSON `{success, html}`. Parse each `div.abonement-container[id^="abonement-container-"]` and its stable locators:

| Field | HTML locator |
|---|---|
| subscription type | `abonement_type_name` |
| state | `abonement_status` |
| creation date | `abonement_creation_date` |
| expiry | `abonement_expiration_date` |
| unified balance | `abonement_united_balance_service_count_*` |
| per-service balance | `abonement_balance_service_count_*` |

This fallback exposed the exact historical values needed for an expired card: its `Просрочен` state, `Срок действия`, and remaining group/individual balance. Only issue GET/fetch requests; never click edit or save controls. A browser tunnel used for one-time login must be temporary and closed as soon as data collection is complete.

## Match duplicate/incomplete client identities

The same email can map to multiple Yclients client IDs. Do not overwrite duplicates in an `email → client` map. Build a candidate set from:

1. exact lowercased email;
2. full normalized phone (including the country prefix); and
3. exact Telegram username when it is present in the sales export and embedded as `@username` in the Yclients client display name.

For each candidate, load cards and score: first by whether required group and individual card types are present; then by nearest subscription `created_date` to the sale. This selected the card-bearing duplicate rather than an empty duplicate profile. Individual cards can be issued materially later than the course payment, so do not blindly reject the only matching type via a short creation-date window; audit multiple plausible cards.

## Report rules established for this workflow

- Valid status cells are only `Активирован`, `Просрочен`, `Исчерпан`.
- `Просрочен`: expiry date has passed; move its balance to the overdue columns and display current remaining as `-`.
- `Исчерпан`: balance is zero.
- Group only: subscription type exactly `Групповая консультация`; other consultation subscription types are individual, including `Консультации (3 шт.)`, `(5 шт.)`, and `(8 шт.)`.
- Do not infer attended counts from record status. Use the reconciled subscription balance/write-off history: normally `sold - remaining`, validating known partial-write-off patterns when history is available.
