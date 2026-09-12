# NextPlan Local v0.1 — Architecture

Status: **FROZEN baseline for Stage V**

## Runtime topology

```text
User's ChatGPT (chatgpt.com)
        |
Chrome Thin Bridge
        |
authenticated localhost channel
        |
NextPlan Local Core (127.0.0.1 only)
        |
+------------------------------+
| Conversation Capture         |
| Entity Resolution            |
| Project/State Engine         |
| Decision Engine              |
| Action Gateway               |
| Permission Engine            |
| Verification / Reconcile     |
+------------------------------+
        |
SQLite Canonical Store
```

Desktop UI is another client of Local Core. It does not write the database directly.

## Layer contracts

### 1. Conversation surface
ChatGPT remains the primary conversational intelligence interface. NextPlan does not duplicate a full chatbot in v0.1.

### 2. Thin bridge
The browser extension only captures authorised conversation turns, transmits them to Local Core, receives structured candidates/receipts, and presents lightweight confirmations/notifications.

### 3. Local Core
Local Core is the only authority allowed to turn interpreted intent into canonical actions. It exposes localhost-only state/capture/action APIs and composes the existing NextPlan classifier with a local canonical store.

### 4. Canonical store
SQLite stores append-only event records plus a materialized canonical state snapshot. The event log remains the audit/history layer; the snapshot is the current projection used by classifiers and UI.

### 5. Local execution
Future local actions are structured capabilities, never raw model-generated shell commands. Every action flows through permission, execution, verification and receipt generation.

## Stage I–IV inheritance

The following semantics remain authoritative and must not be silently changed by the Local migration:

- Project / milestone / next-action model.
- Status vocabulary: planned, active, waiting, blocked, completed (legacy done tolerated).
- Event-backed canonical mutations.
- Entity resolution and confirmation on ambiguity.
- Conversational factual capture and assistant provenance guard.
- Decision Engine / Today semantics.
- Action Gateway distinction between recommendation, permission and execution.
- Verification before reconciliation.
- Auditability and rollback/undo by compensating event.

## Storage abstraction

Business logic consumes a `CanonicalStore` contract rather than GitHub directly.

Required operations:

- get_state
- append_event
- list_events
- bootstrap_state
- list_activity
- metadata get/set

`SQLiteCanonicalStore` is the v0.1 local implementation. Existing GitHub-backed production remains a legacy/remote deployment and is not the end-user local runtime.

## Bootstrap / migration rule

The existing `state.json` is the migration authority for the first local instance because the historical repository predates the complete event layer. Migration therefore:

1. imports the current canonical state as the bootstrap snapshot;
2. imports known repository events as already-applied audit history;
3. verifies semantic parity;
4. applies all future local events transactionally in SQLite.

This avoids pretending that pre-event-layer history can be reconstructed from events that never existed.

## Runtime composition rule

The local runtime must not import the cloud production server composition root in order to obtain state/write behaviour. It may reuse pure classifier/projector modules, but state access and event emission are owned by the local store.

## v0.1 API baseline

Read endpoints:
- `GET /healthz`
- `GET /state`
- `GET /projects`
- `GET /activity`

Write/classification endpoints:
- `POST /conversation/capture`
- `POST /actions/execute`
- `POST /actions/undo` (state undo in later v0.1 stage)

Stage 4 will add browser pairing/reconnect semantics without changing the store contract.
