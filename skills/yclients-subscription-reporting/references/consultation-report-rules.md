# Consultation report rule sheet

Complete this with the user before the initial full export reconciliation.

| Decision | Value | Evidence / owner |
|---|---|---|
| Month bucket | Purchase date unless user specifies otherwise | Confirm explicitly |
| Client matching | Email → normalized phone → flag ambiguity | User must decide duplicate policy |
| Group subscription/service names | Exact names only | Maintain an allow-list |
| Individual subscription/service names | Exact names or explicit exclusion rule | Maintain an allow-list/exclusion list |
| Subscription expiry | Yclients “Срок действия” / valid-through date | Do not substitute creation/activation date |
| Attendance | Subscription-history write-off | Confirm partial write-off grouping |
| Group write-off rule | Business-specific | Example: 1 ₽ = one group session |
| Individual write-off rule | Business-specific | Example: 0.95 ₽ + 0.05 ₽ linked events = one individual session |
| Overdue | Remaining balance after expiry | Include expired subscriptions in source query |
| Appointment statuses | Informational only unless user says otherwise | Do not automatically exclude waiting/confirmed/attended |

## First-run acceptance test

Use 10–20 customers covering:
- active group subscription;
- active individual subscription;
- expired subscription with balance;
- multiple subscriptions;
- 0.95 + 0.05 partial write-off pair;
- no email / phone-only match;
- duplicate client match;
- refund or cancelled purchase.

Have the user validate each computed row before writing the full monthly report.
