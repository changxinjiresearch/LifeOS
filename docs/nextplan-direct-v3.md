# NextPlan Direct v3 — implementation and rollout gates

## Architecture
ChatGPT Plus -> public GitHub Issue inbox -> HMAC-verifying webhook -> private database.
Jarvis -> authenticated Direct API -> the same private database.
Backend also scans public Issue inbox every 300 seconds to compensate for missed webhooks. Browser DOM listeners are not in this write path.

## Existing production is UNCHANGED
Code on branch feature/nextplan-direct-v3 is a staged pilot only. The current Railway Dockerfile still launches server_v13, and the old NextPlan and Sync have not been disconnected. Do not report the Direct v3 transport as live.

## Required before activating
1. Use the verified *dedicated public* GitHub repository changxinjiresearch/nextplan-command-inbox (GitHub repository ID 1417272601) with Issues enabled. Never use the public LifeOS repo or unrelated private research repositories for command ingestion.
2. Provision and back up a truly persistent, private volume (such as a Railway volume). Inspect real cost beforehand. The existing Railway LifeOS service does not have such a volume.
3. Configure an Issues webhook (application/json; events: opened) to https://lifeos-production-89ce.up.railway.app/direct/v3/github/webhook with independent 32+ character secret.
4. Set a repo-scoped GitHub read token for reconciliation in Railway. Do not expose tokens in GitHub Pages HTML/JS.
5. Set these environment values privately: NEXTPLAN_DIRECT_ENABLED=1; NEXTPLAN_DIRECT_DB=/data/nextplan-direct.sqlite3; NEXTPLAN_DIRECT_ROOT=/data; NEXTPLAN_DIRECT_TOKEN=(secret at least 32 chars); NEXTPLAN_DIRECT_GITHUB_SECRET=(different secret at least 32 chars); NEXTPLAN_DIRECT_GITHUB_REPO_ID=(actual public repo id); NEXTPLAN_DIRECT_GITHUB_REPO=changxinjiresearch/nextplan-command-inbox; NEXTPLAN_DIRECT_GITHUB_AUTHOR=changxinjiresearch; NEXTPLAN_DIRECT_GITHUB_VISIBILITY=public; NEXTPLAN_DIRECT_GITHUB_TOKEN=(read token).
6. Mount /data as a real volume. Never enable NEXTPLAN_DIRECT_TEST_MODE in production; the service rejects ephemeral storage by default.

## Migration, one step at a time
1. Back up complete LifeOS/state.json privately, including all milestones, deadlines, notes and events.
2. Compute SHA-256 of sorted-key compact UTF-8 JSON, ensure_ascii=False.
3. Call authenticated POST /direct/v3/bootstrap once with JSON object containing state (full legacy document), confirmed=true, and sha256. The code refuses unconfirmed bootstraps, mismatched hashes and already initialized stores.
4. Compare GET /direct/v3/state with source backup field by field. New DB remains shadow until the existing Web and desktop clients have secure authorized read/write paths.
5. Test rollback and cut over one canonical authority only. Never let both GitHub state.json and the private DB accept production writes concurrently.

## Command format
GitHub Issue body must be only a JSON object, without fences or explanations. Example:
{"version":3,"operation_id":"request-20261010-0001","action":"update_project","project_id":"project-a","changes":{"status":"completed"}}

The GitHub Issue repository ID + Issue number is the authoritative operation identifier. Only Issues opened in the dedicated public repository by the configured account are accepted. Edits do not automatically become new operations.

Current PILOT scope: public GitHub Issues may update only status, priority, progress (not next_action). Authenticated Jarvis direct API may also update next_action; delete_project requires separate authenticated confirmation. Task CRUD, milestones, deadlines and other full NextPlan functions are not implemented yet, so do not retire Sync for those tasks.

Jarvis native endpoint: POST /direct/v3/command with JSON { "command": <protocol object> } and private bearer authorization. ChatGPT Plus may create an Issue using its existing GitHub tools; this cannot be guaranteed for every ordinary turn.

## Safety and receipts
- GitHub webhook X-Hub-Signature-256 is validated before processing.
- Stored commands and final state modifications are committed via SQLite BEGIN IMMEDIATE transactions with unique operation IDs and a canonical revision check.
- Duplicate delivery produces one change; version conflict refuses silently overwriting concurrent changes; unknown IDs reject.
- GET /direct/v3/receipt/<operation_id> reports authoritative current status. A created Issue proves only submission, never completed mutation.
- Issuing deletion through GitHub does not suffice; a second private authenticated POST /direct/v3/confirm with confirm=true must be performed.
- Reconciliation re-reads private GitHub Issues at five minute intervals; if it cannot scan or reaches its hard capacity, record failure and keep legacy transport available.

## Exit criteria
Only activate server_v14 and retire old Sync after: public inbox and live Plus Issue submission verified; persistent volume and backup/restore exercised; real webhook and lost-webhook scan tested; safe Web/desktop auth migrated; 100-command consistency tests passed; duplicates, conflicts, restart, forbidden writes and deletions tested.

We deliberately keep v3 off until these criteria are met. The implementation branch is NOT a fully deployed production system.

## Public inbox ground rules
The user has explicitly chosen public GitHub visibility. Keep it public. GitHub Issue bodies are world-readable: no user prose, secrets, personal data, patient data, or research content. Only stable project identifiers plus structured status, priority, or progress changes belong here. Ensure webhook repository ID, sender, author and HMAC all match. A private database is still required. GitHub public visibility does not imply the NextPlan project database or API should be public.
