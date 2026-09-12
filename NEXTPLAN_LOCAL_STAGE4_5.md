# NextPlan Local v0.1 — Stage 4-5 Contract

## Stage 4 — ChatGPT ↔ NextPlan Local Bridge

The local extension is a thin bridge only. It observes completed ChatGPT turns, sends structured turn data to `127.0.0.1`, receives a candidate/receipt, and presents confirmations. Business logic remains in Local Core.

### Pairing

1. Trusted local UI calls `LocalCoreAppV2.issue_pairing_code()`.
2. User enters the one-time six-digit code in the extension.
3. Extension POSTs the code to `/pairing/complete`.
4. Local Core consumes the code exactly once and returns a random extension credential.
5. Extension stores that credential in `chrome.storage.local` and uses Bearer auth thereafter.

The pairing code is never exposed by an unauthenticated HTTP endpoint. Local Core remains bound to `127.0.0.1`.

The existing production `chrome_extension/` cloud bridge is unchanged. Local development uses `chrome_extension_local/` so the current Railway-backed user workflow is not replaced during Stage 4-5 development.

## Stage 5 — Conversational Project Intelligence

Local classification order:

1. Proven Stage IV existing-state / explicit-command classifier.
2. New project and project-growth detector only if Stage IV returns no candidate.

Supported v0.1 conversational outcomes:

- `conversation_project_discovery`: clear committed goal not already represented in canonical state.
- `conversation_project_growth`: a later conversation adds a meaningful step to an existing project.
- Existing Stage IV `conversation_fact`: active/waiting/blocked/completed updates.
- Informational/no-op when the proposed structure already exists.

### Safety policy

- New project creation is confirm-first by default.
- New milestone/project growth is confirm-first by default.
- High-confidence existing-state changes may auto-apply under the existing Stage IV policy.
- Speculation, hopes, hypotheticals and assistant-only claims do not create canonical truth.
- Assistant text may remain contextual input, but factual authority remains the user's assertion.

## Acceptance scenario

With an empty local store, the user says in ChatGPT:

> 我准备开始找工作，第一步先把简历做好，然后开始申请职位。

NextPlan proposes, but does not silently create:

- Project: 找工作
- Milestone 1: 做简历 (active)
- Milestone 2: 申请职位 (planned)

After confirmation, the project is created atomically. A later statement:

> 申请之前我还应该准备一份 cover letter。

proposes a new milestone on the existing project rather than a duplicate project. Later:

> 我现在已经把简历做完了。

auto-applies the proven Stage IV completion path and advances the next milestone.
