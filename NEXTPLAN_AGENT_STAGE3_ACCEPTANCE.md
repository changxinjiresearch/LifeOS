# NextPlan Agent Stage III — Acceptance Gates

Stage III is not considered complete because code exists. It must pass end-to-end evidence gates.

## Gate A — Permissioned action gateway
- normalized action envelope
- risk classification
- explicit confirmation policy
- standing authorization support
- idempotency key
- normalized execution receipt
- contract tests green

## Gate B — Connector execution
- at least one read-only provider action verified
- at least one reversible write verified
- at least one consequential write blocked until confirmation
- provider-native result ID captured

## Gate C — External trigger intake
- external event enters as a signal/observation
- no canonical mutation before verification
- duplicate trigger handling is idempotent

## Gate D — Closed-loop agent execution
- Observe -> Interpret -> Plan -> Permission -> Act -> Verify -> Reconcile -> Explain
- resumable after a failed step
- audit trail retained

## Gate E — Verification and rollback
- post-action provider state verified
- canonical state updated only after verification
- reversible action exposes compensation when supported

## Gate F — Proactive policy
- at least one narrowly scoped standing policy runs successfully
- policy cannot broaden its own scope
- high-risk action still requires confirmation

Only after Gates A-F pass may all Stage III milestones be marked completed.
