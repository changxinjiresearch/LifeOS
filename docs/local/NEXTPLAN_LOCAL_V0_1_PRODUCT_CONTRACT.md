# NextPlan Local v0.1 — Product Contract

Status: **FROZEN for Stage V v0.1**

## Product definition

NextPlan Local is a local-first personal progress and execution layer that works alongside the user's own ChatGPT session. ChatGPT remains the conversational intelligence surface; NextPlan owns persistent project state, progress, provenance, actions, verification and audit.

The v0.1 product must work for a normal Windows user without Git, Python, Node, Docker, Railway, GitHub or an OpenAI API key.

## Non-negotiable constraints

1. No mandatory NextPlan account or central SaaS backend.
2. No mandatory cloud canonical store. Canonical user state is local by default.
3. No GitHub dependency for end users.
4. No OpenAI API-key requirement. The user's existing ChatGPT session is the conversational surface.
5. The browser extension is a thin bridge. Business logic lives in NextPlan Local Core.
6. User statements may provide factual evidence; assistant statements may help resolve context but cannot independently create canonical facts.
7. Canonical mutations are event-backed and auditable.
8. Recommendation is not execution permission.
9. AI output never receives unrestricted shell authority.
10. Destructive or high-consequence actions require explicit confirmation.
11. External/local execution is not considered successful until verification succeeds or the result is explicitly marked unverified.
12. First release target is Windows. macOS/Linux/ChromeOS are out of v0.1 scope.

## v0.1 must-have capabilities

- Projects, milestones, status, priority and next action.
- Conversational project discovery, milestone discovery and state capture.
- AUTO / CONFIRM / IGNORE capture policy.
- Activity history and state undo.
- Local SQLite canonical store.
- ChatGPT browser thin bridge connected to a localhost-only core.
- Local artifact attachment and basic availability verification.
- Structured low-risk local actions: open file/folder, copy file, open application, show notification.
- Local backup/restore and schema migration before public beta.
- Packaged Windows installer and clean-machine acceptance before release.

## Explicitly out of v0.1 scope

- Central user accounts or hosted multi-tenant project storage.
- Team collaboration.
- Mobile apps.
- Large bundled local LLM.
- Arbitrary shell execution.
- Automatic destructive filesystem operations.
- General mouse-coordinate automation or broad desktop UI automation.
- Automatic email sending.
- Gmail/Calendar/Drive connector suite.
- Multi-device sync.

## Release definition

v0.1 is releasable only when a clean Windows machine can install NextPlan, connect the Chrome extension to the local core, use the user's own ChatGPT conversation to discover/update projects, persist state across reboot, and use basic local artifact actions without any developer setup.
