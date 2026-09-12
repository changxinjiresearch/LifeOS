# NextPlan Agent Stage III — Permission Policy v1

## Principle
No external side effect is allowed merely because an AI plan recommends it.

## Risk levels

| Risk | Examples | Default |
| --- | --- | --- |
| read_only | search calendar, inspect repo status | allowed only when explicitly requested or covered by standing policy |
| reversible_write | create calendar event, create draft, add label | confirmation unless narrowly authorized |
| consequential_write | send email/message, submit form/application, publish change | explicit confirmation unless a narrowly scoped standing authorization explicitly permits that exact class |
| destructive | delete, cancel, irreversible account/data action | explicit per-execution confirmation always |

## Standing authorizations
A standing authorization must define provider, capability, target scope, time/trigger scope, risk ceiling and revocation path. It may not wildcard into broader capabilities.

## Verification rule
An action is not complete when the request is sent. Completion requires provider result evidence and, where practical, a follow-up read/receipt verifying the final state.

## Canonical truth
External execution receipts are evidence. Canonical NextPlan state changes only after verified reconciliation.
