# NextPlan × Jarvis — P1–P4 Web-first implementation status

**Date:** 2026-10-09 (Australia/Adelaide)  
**Type:** Engineering delivery / capability statement, NOT a claim of completed P1–P4 production rollout  
**Repositories:** LifeOS backend + LifeOS-App single Web UI authority

## User goals and constraints

- ChatGPT remains the primary work surface.
- Jarvis is a capability inside **NextPlan**, not another separate product.
- Initial usage is **web-first**, with macOS and ChromeOS native device tests deferred by explicit user choice.
- No mandatory paid AI API.
- Do not put raw conversations, tokens, personal long-term memories or private user records into public GitHub.
- Do not silently mutate legacy NextPlan canonical `state.json`.

## Delivered vertical slice

### P1 — transactional private sync *pilot*

`mcp_server/jarvis_workspace_v1.py`:
- SQLite-backed isolated private workspace, explicit first-time bootstrap.
- Transactional `operation_id` idempotency, canonical-revision preflight/conflict response.
- Allowlisted `update_project` fields; no unrestricted/destructive operations.
- Durable operation receipts in private database; status clearly marked `shadow_until_migrated`.
- `server_v13.py` adds authenticated opt-in API while delegating all existing NextPlan routes to `server_v12`.

**NOT complete:** cannot call this the unified authoritative NextPlan state. Production still uses existing GitHub event/state. No safe live migration, no Mac/ChromeOS device outbox + cross-device consistency tests.

### P2 — manual, consented context bridge *pilot*

- Web UI allows manual input of verified project decisions, observations, hypotheses, preferences and handoffs with source reference.
- Requires explicit user confirmation before recording.
- Records are associated with project and type; they can be exported as a JSON Context Bundle to paste into ChatGPT.
- Never claims it can automatically read private/hidden ChatGPT account memory.
- New API `POST /jarvis/v1/context/record` uses consent and source validation and must persist only to private server storage when enabled.

**NOT complete:** automatic NextPlan Sync → private Knowledge extraction and ChatGPT tool/MCP reverse retrieval have not been wired end-to-end; manual copy/paste is the working fallback.

### P3 — private browser-local encrypted memory *operational when UI is published*

`LifeOS-App/jarvis-local.js`:
- Uses Web Crypto PBKDF2-SHA256 (240k iterations) + AES-GCM 256-bit.
- Derives key from user-held passphrase (>=12 characters); does not persist passphrase.
- Stores only ciphertext (plus salt and nonce) in browser localStorage.
- Explicit authorization required per knowledge entry. Duplicate suppression, search, deletion, export bundle, lock/unlock, and credential-like input rejection.
- Manual notes are **per browser profile only** and can be lost by clearing browser data; passphrase loss is unrecoverable. Not a cloud backup.
- The private server DB (if provisioned) provides another distinct store, **not automatically synchronized with browser-local encryption**.

**NOT complete:** shared cross-device long-term memory, semantic vector retrieval, edit/reconciliation/retention policies, robust end-to-end authorized migration between local and server stores.

### P4 — text-first grounded read-only assistant *pilot*

- `mcp_server/jarvis_brain_v1.py`: reads state + source-referenced knowledge and returns read-only answers.
- Deterministic free grounding fallback when no model is configured. This is a rule-based assistant, not an equivalent to ChatGPT.
- Optional operator-configured Ollama-compatible model adapter with strict hostname allowlist and HTTPS for remote hosts; user must opt in for each request to send private context to the model.
- No model-generated tool execution, no arbitrary shell, no false claims of having ChatGPT hidden context.
- Web UI can show current public NextPlan project snapshot and answer a small subset of project status questions even without private backend.

**NOT complete:** always-available language model on the actual cloud/browser device, flexible high-quality multi-turn inference, robust tool planning, prompt-injection evaluation.

## Deployment and security

- New backend endpoints are under `/jarvis/v1` and are **disabled by default**.
- The server wrapper is backward compatible with `server_v12`; existing NextPlan endpoints continue to delegate.
- To enable private server workspace, require ALL:
  - `NEXTPLAN_JARVIS_ENABLED=1`
  - `NEXTPLAN_JARVIS_TOKEN=<strong random 32+ char secret>` (never commit)
  - `NEXTPLAN_JARVIS_PERSISTENT_ROOT=/data` (real persistent volume mount)
  - `NEXTPLAN_JARVIS_DB=/data/jarvis.db`
- Without a mounted private persistent volume, attempts to access private database fail closed. **No new Railway volume or paid service was provisioned in this change.**
- Do not set `NEXTPLAN_JARVIS_TEST_MODE=1` in production: it bypasses the mount check for isolated CI only.
- Local browser memory is independent of server infrastructure and can be used at no AI API charge. Local browser storage has no cloud backup.
- New browser page: `LifeOS-App/jarvis.html` within existing NextPlan UI; link from `index.html`.
- GitHub Pages deployment must include `jarvis.html`, `jarvis.css`, `jarvis-client.js`, `jarvis-local.js`.
- Do not replace existing `state.json` with the isolated Jarvis shadow snapshot.

## Validation gates and code evidence

- Backend: `tests/test_jarvis_p0_contracts.py`, `tests/test_jarvis_p1_p4.py`, `tests/test_jarvis_web_api.py`.
- Browser: `tests/jarvis-local.test.cjs` and `.github/workflows/jarvis-web-acceptance.yml`; Web Crypto encryption, wrong password, deduplication, consent, delete, safe packaging.
- Existing NextPlan Phase A contracts must pass alongside new tests.
- [Deferred public state risk #19](https://github.com/changxinjiresearch/LifeOS/issues/19)
- [Deferred device testing #20](https://github.com/changxinjiresearch/LifeOS/issues/20)

## Acceptance matrix

| Phase | Code delivered | Immediately usable in Web without cloud provisioning | Production gate |
|---|---|---|---|
| P1 | Transactional protected shadow store + API | Read current NextPlan project snapshot; shadow writes require private volume | **BLOCKED: authoritative migration and sync** |
| P2 | Manual knowledge entry and Context Bundle exchange | Manual recording possible in encrypted browser mode | **PARTIAL: automated bidirectional bridge missing** |
| P3 | Browser-local encrypted knowledge store; server knowledge schema/API | Yes, once user unlocks with passphrase | **PARTIAL: multi-device and retrieval/retention enhancements** |
| P4 | Grounded deterministic answers and optional model adapter | Yes, basic read-only project/status answers | **PARTIAL: no configured general-purpose model and reasoning tools** |

**Conclusion:** substantial P1–P4 **Web-first pilot** implemented and tested; **the full P1–P4 product requirements from the master roadmap remain open**. Do not mark NextPlan P1–P4 as `Completed` solely because this pilot has passed tests.
