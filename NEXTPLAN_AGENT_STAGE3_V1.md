# NextPlan Agent Stage III v1

Status: **ACTIVE**

Started: 2026-09-12

## Mission

Move NextPlan from an observe/recommend planning system into a permissioned personal AI agent that can safely take real-world actions, verify outcomes, and reconcile verified results back into canonical state.

Stage III preserves the existing core invariant: **external systems are not canonical truth until an action result is verified and reconciled into NextPlan.**

## Stage III roadmap

### 13. Action Gateway + Permission Model
Status: active

Build one cloud-side execution gateway for all side-effecting external actions. Every action must have an explicit risk class, permission policy, idempotency key, dry-run/preview path where possible, and execution receipt.

Risk classes:
- read-only
- reversible write
- consequential write
- destructive / irreversible

Default policy:
- read-only may run automatically when explicitly requested;
- reversible writes may auto-run only under a user-approved standing rule;
- consequential writes require explicit confirmation unless covered by a narrowly scoped standing authorization;
- destructive/irreversible actions always require explicit confirmation.

### 14. External Connectors
Status: planned

Connect supported external systems through provider/plugin APIs instead of browser scraping whenever possible. Initial targets should be calendar, email, GitHub and selected project/research services.

Connector contract must support:
- capability discovery
- authenticated action execution
- provider-native identifiers
- safe error handling
- normalized receipts

### 15. Trigger + Event Intake
Status: planned

Bring external changes into NextPlan as signals without immediately treating them as truth. Examples include incoming email, calendar change, repository event, application update, editorial status change, or scheduled check.

Signals become verified observations before they can mutate canonical project state.

### 16. Agent Execution Loop
Status: planned

Implement the closed loop:

`Observe -> Interpret -> Plan -> Request/Check Permission -> Act -> Verify -> Reconcile -> Explain`

The loop must be resumable, idempotent and auditable. A failed step must not silently advance later steps.

### 17. Verification + Reconciliation + Rollback
Status: planned

After an external action, verify the provider result using returned IDs/state. Only verified results may update canonical NextPlan state. Reversible writes should expose a compensating-action/rollback path when the provider supports one.

### 18. Proactive Agent Policies
Status: planned

Allow narrowly scoped standing policies such as:
- prepare a draft follow-up when a waiting item exceeds a threshold;
- add a calendar hold when a confirmed deadline enters its preparation window;
- refresh a weekly review automatically;
- monitor an external dependency and surface only meaningful changes.

Proactive policies remain bounded by the permission model and may never silently broaden their own scope.

## Non-goals for Stage III v1

- unrestricted autonomous browsing or messaging;
- silent purchases, payments, account changes or destructive operations;
- treating model inference as external confirmation;
- bypassing provider permissions or user confirmation policies;
- storing credentials or secrets in canonical state.

## Completion definition

Stage III is complete when all six milestones (13-18) are implemented, tested, deployed, and represented in canonical NextPlan state with verified end-to-end execution for at least one read-only connector flow, one reversible write flow, one consequential write requiring confirmation, one external trigger flow, and one verified reconciliation flow.
