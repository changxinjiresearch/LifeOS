# Jarvis — reviewed NextPlan actions, ChatGPT context, memory and Web Speech (2026-10-09)

## Implementation snapshot
This is an **integrated Web-first incremental release**, not the final production completion of P1/P2/P3/P5 or the original four-stage request.

### Phase 1 — Authoritative NextPlan project actions (behind an extension confirmation gate)
- `chrome_extension/jarvis_bridge_v1.js` validates a known project against a FRESH `/extension/state` snapshot and permits **one** allowlisted `update_project_snapshot` change: `status` or `next_action`.
- `LifeOS-App/jarvis-action-parse.js` can parse certain unambiguous Chinese requests into a **pre-populated form** only, never executable model output.
- On explicit Web form confirmation, the extension creates an action in its persistent `pendingCandidates` review queue. Only a SECOND user action inside the **NextPlan Sync extension popup** invokes the existing authenticated `/extension/action` backend.
- Actions have durable `operation_id`; after request submission, the extension checks the actual `/extension/state` project field. **No verified state → status `verification_pending`, keep queue item and do not re-send the same write.**
- No project deletion or arbitrary tool access is supported through Jarvis.
- **Production risk:** the underlying NextPlan canonical state is still stored in a publicly readable GitHub repository. Do not put private data into `next_action`. Authentication/token configuration and a real extension install are required for live acceptance.

### Phase 2 — ChatGPT context transfer with explicit consent
- The updated MV3 NextPlan Sync v0.6 context menu lets the user select a small piece of ChatGPT text and choose **发送选中文字到 Jarvis 待确认知识**.
- Explicit `Jarvis，记住：...` or `/jarvis-remember ...` messages automatically generate a **candidate only** after appearing as user-authored ChatGPT text.
- Candidate text is stored temporarily in the extension's local queue, in PLAIN local extension storage until reviewed. **It does not become user-confirmed knowledge, nor is it uploaded to GitHub or Cloudflare.** The user opens Jarvis, unlocks their encrypted local knowledge vault, chooses a project/type, reviews the text, confirms, and only then is the knowledge encrypted and saved. The extension candidate is acknowledged/removed after successful storage.
- Full ChatGPT hidden memories / entire previous conversations are not accessible; automatic broad scraping is deliberately not enabled.
- The existing sync extension action classifier still has its own behavior; Jarvis's new approval workflow doesn't replace it.

### Phase 3 — Encrypted browser-local knowledge with backup and corrections
- Adds download of an encrypted JSON backup, explicit replacement/recovery requiring original passphrase, and correction with `superseded_by` provenance. Superseded entries no longer enter current search or Context Bundle.
- Browser-local knowledge remains *single browser profile*; there is **no automatic cross-device replication** or remote private storage configured.
- Users must keep both backup and password separately. Clearing browser data without a backup may permanently lose information.
- Source provenance is a user-supplied pointer; this pilot cannot verify every claim automatically.

### Phase 4 — Opt-in browser voice interaction
- Web Speech Recognition: one explicit mic session to **transcribe** a Chinese or English question; user must inspect and click Submit manually.
- Web Speech Synthesis: read back the most recent Jarvis answer, interrupt/stop on demand.
- SpeechRecognition may involve the browser vendor's cloud processing; do not use for sensitive private data.
- No background/always-on wake word, no continuous full-duplex conversations, no guaranteed voice support on every ChromeOS/macOS browser. Those are later P5 acceptance requirements.

## Install/update the extension (user action needed)

GitHub merging code does **not** update a previously installed unpacked browser extension.

1. Obtain a current checkout/download of [LifeOS](https://github.com/changxinjiresearch/LifeOS).
2. Open `chrome://extensions` on Chrome/ChromeOS. Disable previous duplicate NextPlan Sync copies first to avoid multiple observers and double capture.
3. Enable Developer mode; **Load unpacked** and select the repository's **`chrome_extension/` folder containing `manifest.json`**. Verify version **0.6.0** and permissions for ChatGPT and the NextPlan GitHub Pages origin.
4. Use extension Options to confirm it can access your authorized NextPlan backend. Do not share its token or Cloudflare Worker secret in chat/screenshots.
5. Open [NextPlan Jarvis](https://changxinjiresearch.github.io/LifeOS-App/jarvis.html), reload, check the **正式 NextPlan** panel and context inbox.
6. For a safe non-sensitive action test, propose a non-destructive status change on a **test project**, use extension popup to confirm, and check that its final field truly matches. Do not test with a critical live research project first.
7. In a ChatGPT tab, select a harmless sentence and use the extension's context-menu entry. Back in Jarvis, unlock local memory and confirm the import. Reload and verify.
8. Test microphone only after granting permission, check transcribed text before manual submission, then test TTS and cancellation.
9. Download encrypted backup; verify recovery only in a separate browser profile/test store, unless existing vault is safely backed up.

## Evidence and release gates
- `chrome_extension/tests/jarvis_bridge.test.mjs` and `.github/workflows/jarvis-bridge-v06.yml` cover sender/origin checks, typed canonical proposed updates, explicit capture and no automatic trusted memory.
- `LifeOS-App/tests/jarvis-local.test.cjs`, `jarvis-voice.test.cjs`, `jarvis-action-parse.test.cjs` and Web workflow cover encrypted backup/corrections, strict parsing and explicit speech controls.
- Current feature CI exercises mocks, not user's actual Chrome extension or mic hardware.
- Tests and CI **cannot** establish actual canonical cross-device write consistency, microphone permissions, source-fidelity, cloud private sync or background speech performance.
- Keep [public-state migration #19](https://github.com/changxinjiresearch/LifeOS/issues/19), [device acceptance #20](https://github.com/changxinjiresearch/LifeOS/issues/20), and [full P1–P4 acceptance #22](https://github.com/changxinjiresearch/LifeOS/issues/22) open.

## Operating rule

Do not mark any command "completed" just because the LLM generated text, the extension queued an action, or the cloud builder accepted an event. Completion requires a verified postcondition read from NextPlan's authoritative state.
