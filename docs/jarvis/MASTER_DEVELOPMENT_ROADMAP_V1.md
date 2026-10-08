# NextPlan × J.A.R.V.I.S. — Master Development Roadmap v1.0

**Date:** 2026-10-09  
**Status:** DESIGN APPROVED AS ROADMAP DRAFT; PHASE P0 UNDER WAY; NOT AN IMPLEMENTATION OR ACCEPTANCE CLAIM  
**Target platforms:** macOS (Apple Silicon and Intel), ChromeOS (Web/PWA + Chrome Extension)  
**Code owners:** existing LifeOS backend + LifeOS-App single UI authority  
**Core requirement:** ChatGPT continues to be the main work environment; NextPlan supplies consistent factual state; Jarvis supplies voice, intelligence, execution, perception and proactive assistance. There is no independent third NextPlan/Jarvis product.

## Product definition and completion boundary

Deliver a personal intelligent operating environment providing (1) conversation continuity through an authorized ChatGPT bridge, (2) user-controlled long-term memory, (3) local-first model adapters, (4) realtime voice, (5) permissioned OS/browser skills, (6) resumable multi-step agent jobs, (7) opt-in screen/vision, (8) proactive monitoring, (9) unified HUD and (10) macOS/ChromeOS installer and browser experiences. Hardware integrations are optional expansion.

The engineering definition of complete is a shipped, secure, independently verifiable product within the declared scope — **not** literal movie-level AGI or free-space holography.

## Existing foundations: verified limits

- Existing local runtime: Tauri 2 + Local Core v4 + SQLite + local Chrome Bridge.
- Existing remote runtime: cloud endpoint and GitHub-based event/state model, with distinct canonical state topology.
- Existing browser UI: LifeOS-App is the only UI authority; desktop synchronizes this UI.
- Existing planning: project/task/deadline/note/resource state, Today/Decision Engine, AI Planning and rule-based automation.
- Existing limited agent: GitHub-focused external connector, action permission/receipt/reconciliation; local allowlist currently artifact.open, folder.open, file.copy, application.open.
- 2026-10-07 GitHub Actions had successful macOS Intel and Apple Silicon acceptance/build artifacts. No evidence from the user's physical macOS or ChromeOS devices has yet been collected.
- Full ChatGPT memory and hidden context are NOT programmatically available to Jarvis. Any bridging must be authorized and use visible/supported data routes.
- P0 audit: docs/jarvis/P0_CURRENT_CAPABILITY_BOUNDARY_2026-10-09.md and docs/jarvis/P0_IMPLEMENTATION_PLAN.md.

## Architecture invariants

1. NextPlan project/task/deadline truth has exactly one authoritative service and event history; device databases are caches/outboxes after migration.
2. Context Archive, Knowledge, and Jarvis private memory are distinct from the canonical task state.
3. A claim is not an executed operation; an executed operation is not verified completion. Only a trusted receipt plus relevant postcondition may be marked completed.
4. Every operation has a stable operation ID, risk classification, provenance, permissions, timestamp, visible state and recoverable log.
5. User controls authorization, capture, and deletion. Default is minimal capture, not bulk chat exfiltration.
6. Source code may live in a public repository; personal state, history, voice, memory and credentials may not.
7. Keep LifeOS-App as sole presentation source; platform differences go into adapters.
8. ChromeOS browser permissions are not whole-operating-system control. The Manifest V3 extension service worker must tolerate termination.
9. A zero-paid-LLM-API path remains supported on suitable hardware, but compute, hosting and device requirements may still have costs.
10. Never silently change user project status during software planning.

## Stage I — Foundation, continuity, intelligence

### P0 — Audit, architecture and safety prerequisites
**Includes existing P0-A/B/C/D/E/F and new P0-G bridge design.**

Work:
- Freeze code/CI/device evidence capability matrix and record version, branch and current deployed composition.
- Audit GitHub cloud event-state and local SQLite data paths; define a migration and rollback plan.
- Identify public/private data risks, review current repository history and storage boundaries, and define credentials/vault policy.
- Design authenticated canonical service, encrypted data transport and device cache/outbox.
- Specify bridge ingestion, typed knowledge extraction, retrieval, citation and handoff contracts.
- Specify local macOS vs browser-only ChromeOS capabilities.
- Run fresh macOS Intel/Apple Silicon and actual ChromeOS functional acceptance; do not equate CI with real-device completion.
- Set stable test fixtures and CI regression requirements.

Deliverables: architecture decision records; threat model; canonical data protocol; compatibility matrix; test plans; full evidence-backed capability list.  
Exit gate: critical privacy and authority decisions documented; device test evidence available; no unresolved unsafe current-data migration path.

### P1 — Canonical NextPlan state and cross-device sync
Work:
- Design authenticated state API atop existing event model, not direct unsupervised SQLite or state.json overwrites.
- Choose hosting after cost/privacy/failure-mode evaluation; do not assume current GitHub public state is acceptable storage.
- Migrate existing canonical state with backup, semantic parity and reversible cutover.
- macOS: Local SQLite as durable cache plus offline outbox; ChromeOS: PWA cache/IndexedDB plus outbox where supported.
- Use operation_id and event_id to deduplicate actions; preserve target/entity IDs, versions, conflict signals and user-visible receipts.
- Define offline, stale read, concurrent update, delete tombstone and reconnection rules.

Exit gate: confirmed mutation is visible on both devices; offline retry causes zero duplicate mutations; conflict is detected and explainable; integrity verified after restore.

### P2 — ChatGPT ↔ Jarvis Context Bridge
Work:
- Evolve NextPlan Sync into selective structured capture: task-state change, confirmed decision, project knowledge, useful source pointer, handoff record and undecided hypothesis.
- Provenance: chat surface URL/title if permitted, message timestamp, user confirmation, project link, confidence, source checksum and private retention class.
- By default ingest only authorized relevant extracts, not all raw conversations.
- Allow one-time user-directed conversation export/import when available; it is NOT a direct export of hidden ChatGPT model memory.
- Provide NextPlan context bundle export for manual paste and supported read interfaces; a custom ChatGPT MCP app is optional and depends on plan/permissions. Do not make it a mandatory dependency.
- Add Jarvis-to-NextPlan verified execution receipts and indexed summaries for ChatGPT retrieval.
- Retry on Chrome MV3 service-worker restart; maintain durable local pending queue.

Exit gate: one important ChatGPT project decision is available with source to Jarvis; one verified Jarvis execution is readable back in ChatGPT via a supported/explicit route; no conversation discussion accidentally completes a task.

### P3 — Private long-term knowledge and memory
Work:
- Separate semantic, episodic, decision, preference, procedural and project memory.
- Schema contains source/provenance, timestamp, scope, verification status, replacement/correction link, sensitivity and retention.
- SQLite FTS and optionally a local vector index; citations for answers and fact freshness.
- User-controlled read/delete/export policies; prompts cannot overwrite verified facts without confirmation.
- Define retrieval ranking, conflict detection and memory quality regression tests.

Exit gate: long-term retrieval after restart/another day; memory answer links to original evidence; contradictory newer facts supersede older ones; private material does not leak to GitHub.

### P4 — Jarvis Brain (text-first)
Work:
- Add ModelAdapter: local Ollama/llama.cpp on capable macOS, optional remote LLM. No mandatory paid OpenAI API.
- Add conversation manager, intent parsing, structured plan proposal, NextPlan knowledge retrieval, confidence and unknown-state reporting.
- Integrate a read-only tool registry first; the model produces structured requests but has no direct filesystem/system privileges.
- Add policy/authorization gate, rate and cost budgets, diagnostics, portable provider switches.

Exit gate: real NextPlan Q&A, context-aware next action recommendations, consistent tool selection, grounded citations and clear unknowns, with model swap without data loss.

**Milestone V0.1:** ChatGPT work decisions can be handed to a text-based Jarvis that understands real NextPlan context across macOS and ChromeOS. No voice or unrestricted OS control required.

## Stage II — Interaction, execution, perception

### P5 — Realtime natural voice
Work:
- macOS: optional local wake word; streaming mic, STT, TTS, VAD, interruption/barge-in, conversation session manager, headphone feedback/echo handling.
- ChromeOS: browser audio input/output with explicit consent; reliable active-app fallback. Never promise persistent always-on wake word in a suspended PWA.
- Local STT/TTS models as feasible, optional external providers; multilingual recognition.
- Visible microphone state, privacy indicators, cancellation and mute controls.

Exit gate: bilingual continuous short conversations, successful interruptions, test wake-word false positives, measured latency and safe mic shutdown.

### P6 — Browser and permissioned computer skills
Work:
- Define SkillManifest with platform support, arguments schema, risk, effects, undo and verification method.
- Expand local allowlist incrementally: authorized files, application opening, selected automation, GitHub, browser actions and platform adapters.
- macOS: Tauri/sidecar plus OS permissions (Accessibility, Screen Recording, Automation) only as justified and approved.
- ChromeOS: browser extension and PWA skill API; no implicit control over arbitrary host applications. Optional Linux-container agent is separate opt-in.
- All consequential and destructive actions get matching user/standing authorization; high-risk irreversible operations require per-action confirmation.

Exit gate: controlled file/browser/task actions run with receipts; prompt injection cannot authorize a dangerous action; repeated commands do not duplicate effects.

### P7 — General task agent and safe orchestration
Work:
- Job state machine Observe → Interpret → Plan → Permission → Act → Verify → Reconcile → Explain.
- Durable checkpoint, resume, idempotent steps, dependency DAG, failure rollback/compensation and budget caps.
- Multi-tool workflows combine read GitHub, inspect NextPlan, prepare artifacts, request confirmation and verify actual changes.
- Include emergency stop, live progress, user takeover and auditable logs.

Exit gate: 30+ representative multi-step jobs with structured evidence; robust pause/resume, red-team prompt injection, replay-safe recovery, no silent destructive actions.

### P8 — Multimodal visual understanding
Work:
- Opt-in screenshots, browser page state, accessibility tree and local visual model/OCR as appropriate.
- macOS optional screen sharing/capture of selected display or application. ChromeOS explicit active-tab or screen capture permissions.
- Link visual observations to a selected job and expire captures by policy.
- Ground clicks/actions by element metadata where possible; screenshot coordinate controls require verification.

Exit gate: interpret live application errors, inspect a user-selected visual state and act only within granted scope; no background unauthorized screen capture.

**Milestone V0.5:** Jarvis can listen and speak, use several actual tools and complete bounded autonomous jobs; visual reasoning is opt-in.

## Stage III — Proactivity, cinematic experience, full release

### P9 — Proactive intelligence and scheduler
Work:
- Upgrade existing NextPlan automation rules with verified external triggers, event queues, meaningful-change thresholds, quiet hours, deduplication and user-approved policies.
- Only high-confidence relevant events may notify; use bounded standing authorizations.
- Explain why an alert fired; support one-click suppress/disable; prevent noisy loops.

Exit gate: GitHub/test deadlines/tasks can generate grounded alerts at the correct time without duplicates or unsolicited high-risk actions.

### P10 — Cinematic HUD and interaction design
Work:
- Add Jarvis workspace inside LifeOS-App only: radial animation, waveform, conversation view, source panel, live agent plan, step receipts, interrupt/confirm controls.
- Use responsive 2D/3D tech with reduced-motion, keyboard and screen-reader support.
- GPU/load budgets and performance profiling on Intel and Apple Silicon Macs and low-powered Chromebook.

Exit gate: same design system and project state in both platforms, functional Jarvis control, acceptable interaction speed, no duplicate UI maintenance branch.

### P11 — Ecosystem, devices and extensibility
Work:
- Skill SDK with signed/allowlisted manifests and minimum capabilities.
- Add selected external services via native authenticated connectors, revocation and scope.
- Optional Home Assistant connection with device allowlist and physical-action confirmation.
- Handoff between Mac and ChromeOS with shared job receipts; optional mobile/remote monitoring later.

Exit gate: install/configure/revoke a sample skill, complete a cross-device task, and pass one chosen optional hardware integration or emulator test without compromising the core.

### P12 — Security, real-device acceptance and production release
Work:
- Threat modeling, sandboxing, prompt-injection tests, token handling, dependency/license review, E2E encryption choices, backup/restore and erase/export.
- End-user installer (Apple Silicon and Intel) with appropriate signing/notarization/distribution checks; ChromeOS PWA and extension delivery/review.
- Automatic upgrades with rollback, offline behavior, migration from old NextPlan versions, incident logging and user documentation.
- End-to-end regression tests across NextPlan projects, NextPlan Sync and Jarvis actions; no silent behavior changes.
- Beta → RC → stable release, public feature boundary and known limitations.

Exit gate: two physical macOS architectures and at least one ChromeOS target verified (or architecture documented as not available in release matrix), no critical security failures, recovery plan tested, all documented core scenarios pass, end-user install/upgrade flow reproducible.

**Milestone V1.0:** reliable real-world software companion across macOS and ChromeOS with user-authorized voice, memory, vision, agent and proactivity, and a coherent UI.  
**Milestone V2.0:** ecosystem / hardware extensions, personalization, broader portability and refined cinematic experience. This is a sustained version, not a promise of literal cinematic AGI.

## Release acceptance targets (proposed, not measured)

- **Security:** zero unauthorized destructive or consequential side effects; test compromised tool outputs and injected webpage instructions.
- **Sync:** 100 test repeated writes with zero duplicate effects; Mac-to-ChromeOS eventually consistent within defined online synchronization SLA; visible stale/failed status.
- **Context:** 50 provenance test cases; at least 90% answer correctness from authorized known facts; no unsupported fabrication of past ChatGPT context.
- **Execution:** at least 30 multi-step scenarios; at least 90% initial success for V0.5, 95% target for stable on a frozen regression suite; strict receipts.
- **Voice:** 100 command evaluation across Chinese and English; recognize at least 95% in specified quiet test environment; report actual median and p95 response latency.
- **Recoverability:** kill process mid-job, restart, verify no unauthorized double write.
- **Platform:** published support matrix, real installation/upgrade results; distinguish ChromeOS web-only restrictions and macOS-native permissions.
- **Privacy:** user-visible controls for voice/screen/history retention and deletion.

## Suggested schedule and budgets

Assumption: one primary developer with coding assistance, about 10–20 focused hours/week, access to real test devices; stages can overlap selectively.

| Phase | Rough schedule (weeks) |
|---|---|
| P0 | 1–3 |
| P1 | 3–6 |
| P2 | 4–7 |
| P3 | 3–5 |
| P4 | 3–5 |
| P5 | 3–6 |
| P6 | 4–8 |
| P7 | 5–9 |
| P8 | 4–7 |
| P9 | 3–5 |
| P10 | 3–6 |
| P11 | 4–8 |
| P12 | 4–8 |

These are effort-dependent estimates, not guaranteed dates. Scope/quality/hardware and platform integration may extend total delivery substantially (roughly 12–24 months or more for a robust personal release). Do not assert all milestones are done on calendar alone.

No-cost API strategy: retain usable local model route and deterministic automation; optional paid/cloud provider only on explicit user configuration. Hosting, devices, storage and signing may introduce non-API costs.

## Engineering workflow for every phase

1. Freeze scope and baseline; write acceptance criteria before implementation.
2. Create a feature branch and ADR/API contract; avoid changing canonical production state.
3. Implement small increments behind disabled-by-default flags.
4. Add unit, contract, cross-platform and privacy/safety tests.
5. Run CI, capture artifacts and logs; inspect failures, retry only after understanding.
6. For permission or OS features, run physical-device acceptance; record actual tested version.
7. Review regression impact on existing NextPlan behavior and previous Jarvis phases.
8. Merge with reversible migration/rollback plan; update capabilities and known limitations.
9. Mark phase completed only with evidence, not from code presence or discussion.

## Release-blocking risks

1. Public LifeOS repository and state data visibility; never write new private context there.
2. Cloud GitHub event-state and local SQLite authority conflict; no cross-device claims until solved.
3. ChatGPT custom connector/MCP entitlement may depend on plan and availability. Keep NextPlan Chrome Sync and explicit context import/export as first-party fallbacks.
4. ChromeOS MV3 service workers are event-driven and terminate when idle; durable queues are mandatory.
5. ChromeOS Linux container is isolated; native desktop control cannot be assumed.
6. Real-time local AI/STT/TTS model size/latency on weak hardware.
7. Risks from interpreting untrusted web content as commands.
8. Signing/notarization/distribution and privacy policies for public release.

## Immediate next actions

- P0-B: select authoritative sync topology and migration plan.
- P0-C: private data boundary and clean-up strategy for any exposed metadata.
- P0-G: precise ChatGPT extraction, NextPlan Knowledge record schema, export/retrieve/handoff protocol.
- P0-D/E: collect Mac and Chromebook hardware/version and real acceptance results.
- Do not begin voice or auto-control before critical authority and privacy gates have passed.

**Scope:** planning/documentation only. No existing project/task status is modified by this roadmap.
