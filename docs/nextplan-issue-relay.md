# NextPlan Issue Relay: production transport

## Active design

User's ChatGPT Plus -> existing GitHub connector creates an Issue in the user-authorized **PUBLIC** `changxinjiresearch/nextplan-command-inbox` -> background relay inside existing Railway LifeOS process checks creator-owned Issues -> deterministic event file in LifeOS `events/inbox` -> existing event builder updates **the same canonical `state.json` already used by NextPlan Web**.

This bridge removes the ChatGPT DOM/Chrome Sync dependency without a dual-canonical-data migration. Existing project IDs, milestones and UI remain intact. In a later separate migration, the prepared private Direct v3 DB can replace the GitHub state authority after the Web and Jarvis clients are prepared and tested; that migration is not activated by the relay.

No GitHub webhook is required for this operating mode. The relay checks every ~90 seconds; the actual end-to-end delay depends on Railway, GitHub and event builder latency. The GitHub Issue is durable but creates **no guarantee** that an ordinary ChatGPT Plus turn invokes the GitHub tool.

## Production flags
- `NEXTPLAN_INBOX_RELAY_ENABLED=1` in Railway (only set after tests).
- Existing `NEXTPLAN_GITHUB_TOKEN` needs repository contents write access to LifeOS and read access to public inbox.
- Dockerfile must use `mcp_server.server_v14:app`, which delegates all existing endpoints to server_v13.
- `NEXTPLAN_DIRECT_ENABLED=0` keeps the separate SQLite v3 shadow backend dormant.

## Public Issue format (strict JSON body)

Issue title must begin with `[NextPlan]`. Author must be `changxinjiresearch`. No keys or private content in the Issue body.

```json
{"version":3,"action":"update_project","project_id":"research-neuri","changes":{"status":"completed"}}
```

The relay supports:
- update_project: status, priority, next_action
- complete_task: project_id and task_id
- update_milestone: project_id, milestone_id and status
- create_task: project_id, name and optional task_id

Deletion, account secrets and unrestricted data imports are intentionally rejected. Existing NextPlan UI can still operate as before; old browser Sync should be disabled by the user only after successful real-world acceptance.

## Verify the result
- `GET /inbox/v1/status` indicates whether the worker ran successfully.
- `GET /inbox/v1/receipt/{issue_number}` reads the canonical event and checks the resulting project status.
- A new GitHub Issue confirms **submitted** only.
- The deterministic event ID `evt-nextplan-inbox-1417272601-{issue_number}` means repeated scans cannot create duplicate event files; edits changing command content are rejected.
- A result is verified only if the canonical event builder has processed the event ID AND the relevant project postcondition matches; otherwise it is submitted/unverified or a mismatch.
- The relay stops and surfaces failures on GitHub/network problems and retries later.

## Limitations
- GitHub status ID history may be truncated after very many events; old processed Issues remain deduplicated by their deterministic event file, but ancient historical receipts may become unavailable. For a long-term exactly-once auditable system, move operation results to a private durable ledger.
- This compatibility relay intentionally keeps GitHub `state.json` as authority. A private SQLite volume is being prepared separately; do not silently switch both authorities.
- Public Issues should contain only non-sensitive task metadata.
- Background checks require Railway instance to be running; idle/sleeping service may delay notification.
- No guarantee of automatic tool invocation for every general conversation in ChatGPT Plus.

## Acceptance sequence
1. GitHub Actions CI passes both NextPlan smoke and Issue relay safety tests.
2. Deploy v14 with opt-in relay.
3. Verify `/healthz` and `/inbox/v1/status` on live service.
4. Create harmless Issue using known existing project current status.
5. Verify event persisted in LifeOS and project result unchanged but event processed exactly once.
6. Confirm NextPlan Web reads the canonical state.
7. Verify duplicate polling, offline retry and malformed commands behave correctly.
