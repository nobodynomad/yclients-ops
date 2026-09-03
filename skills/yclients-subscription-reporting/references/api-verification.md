# Verified Yclients API read-only probes

Use this as a troubleshooting sequence for a Marketplace app that has a Partner Token and the app-generated system User Token. Never print client data or tokens in probe output.

## Authentication

The verified request form was:

```text
Authorization: Bearer <partner_token>, User <user_token>
Accept: application/vnd.yclients.v2+json
```

A company-level endpoint can work with partner authentication while a user-protected endpoint still fails. Do not infer full client-data access from a company metadata response alone.

## Correct read-only health checks

| Purpose | Method and endpoint | Expected result |
|---|---|---|
| List clients | `GET /api/v1/clients/{company_id}?count=200&page=N` | 200; page + total count |
| Search clients | `POST /api/v1/company/{company_id}/clients/search` with JSON such as `{"count":1,"page":1}` | 200; matching list |
| Read client subscriptions | `GET /api/v1/loyalty/abonements/?company_id={id}&phone={phone}` | 200; may validly contain zero subscriptions |
| Read services | `GET /api/v1/company/{company_id}/services` | 200 |

### Subscription phone lookup

Send the client's **full digits-only phone number**, including its country prefix when present in Yclients (for example, `79…`). Do not reduce it to the last 10 digits: this can return a successful empty subscription list even when the full number returns the client's subscriptions.

The subscription response exposes the fields needed for a first reconciliation: `created_date`, `activated_date`, `expiration_date`, `status`, `type.title`, and the remaining quantity in `balance_container.links[].count`. Use `expiration_date` for the report's valid-through date; do not substitute creation or activation date.

Use the deprecated client-list endpoint only as a simple low-risk availability probe; use the current client-search API for production reconciliation when supported.

## Important false-negative to avoid

`GET /api/v1/company/{company_id}/users` is **not** a valid general access health check. It requires the separate permission to manage users. A 403 on that endpoint is expected if the app intentionally lacks user-management rights and does not mean it cannot read clients, subscriptions, records, or services.

## Marketplace connection lifecycle

Yclients creates a separate system user for an app. The owner/admin user’s UI permissions do not automatically prove that this system user is connected to the branch.

- App scopes selected under **Доступ к API** are granted to the system user after the integration is connected to the branch.
- Marketplace installation may require a valid HTTPS webhook URL before settings can be saved.
- The connection status can be checked with:
  `GET /marketplace/salon/{salon_id}/application/{application_id}` using `Authorization: Bearer <partner_token>`.
- A successful installation reports `connection_status.status: active`.
- Partner activation endpoint documented by Yclients:
  `POST /marketplace/partner/callback` with bearer partner token and body containing `salon_id`, `application_id`, and `webhook_urls`. If it returns that the application is already installed, query connection status rather than repeatedly retrying.

For privacy, a required webhook endpoint should acknowledge traffic without storing payloads unless event processing is explicitly required.
