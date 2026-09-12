# NextPlan Local v0.1 — Stage 6–8

## Stage 6 — Desktop App

The desktop shell is implemented in `desktop_local/` using Tauri 2. It owns a trusted bootstrap credential, launches the Local Core during development, and exposes five user surfaces: Today, Projects, Activity, Artifacts and Settings. The UI never writes SQLite directly; all reads and mutations go through authenticated Local Core APIs.

The desktop surface can issue a one-time browser pairing code, review confirmation candidates, apply/ignore detected changes, change local permission mode and inspect the local database path.

## Stage 7 — Workspace & Artifact Layer

A project may explicitly bind one authorized local workspace. Binding is an access grant, not a background whole-disk scanner. A task artifact may be explicitly attached to a project/milestone and records path, MIME type, size, modified time, SHA-256, availability and verification state.

Artifact truth is event-projected through `workspace_bound`, `artifact_attached`, `artifact_verified` and related local events. Missing files are reported as missing; NextPlan does not silently invent or relocate them.

## Stage 8 — Local Execution & Verification

Local execution is capability-based. The public v0.1 registry is deliberately narrow:

- `artifact.open` — R1
- `folder.open` — R1
- `file.copy` — R1 and reversible by receipt recipe
- `application.open` — R2 and confirmation-required in Balanced mode

There is no `shell.execute`, arbitrary command string, delete, overwrite-by-default or mouse-coordinate automation capability.

Every execution goes through preview → permission decision → execute → verify → receipt. `file.copy` is verified by SHA-256 equality after copy. Opening an artifact/folder/application records an accepted dispatch receipt because an OS launch request cannot prove that a human-visible window successfully rendered.

Permission modes are `conservative`, `balanced` (default) and `autonomous`; R3 remains reserved for future destructive actions and must always require confirmation.

## Confirmation authority

Pending conversational changes are stored outside canonical truth in SQLite `pending_candidates`. Both the Chrome bridge and Desktop Activity/Today surfaces read the same queue. Applying a candidate produces the canonical event; ignoring it does not mutate canonical project truth.

## Release boundary

Stage 6–8 provides source-level desktop, workspace/artifact and local execution capability. It is not yet the final end-user installer. Bundling the Python Local Core as a sidecar, signing, updater, backup/recovery hardening and clean-machine acceptance remain Stage 9–10 work.
