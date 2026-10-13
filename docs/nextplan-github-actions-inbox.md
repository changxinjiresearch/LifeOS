# NextPlan Direct — live GitHub Actions transport

Production mode: **GitHub Actions + existing canonical `state.json`**. No Railway runtime or Chrome Sync browser listening is needed to deliver an explicitly submitted GitHub Issue.

## Live chain

1. ChatGPT Plus GitHub connector submits a structured Issue in the public `changxinjiresearch/nextplan-command-inbox` (repo ID 1417272601).
2. `.github/workflows/nextplan-issue-inbox.yml` runs on a five-minute schedule; also supports manual dispatch and runs after workflow/script changes.
3. `scripts/nextplan_issue_actions.py` verifies repo identity, author `changxinjiresearch`, title prefix, exact IDs, and action schema.
4. Deterministic event files (`events/inbox/evt-nextplan-gh-issue-N.json`) are applied through `engine/build_state_v3.py`.
5. The script confirms the requested final project/task state and writes `events/receipts/issue-N.json` with `verified`, or `rejected` with a reason.
6. Event, receipt, and canonical `state.json` are pushed together; concurrent pushes trigger a clean fetch/rebuild retry.

The GitHub public Pages NextPlan app already reads `LifeOS/main/state.json` and needs no schema migration for this operating mode.

## Verified acceptance test

- Command: [Issue #2](https://github.com/changxinjiresearch/nextplan-command-inbox/issues/2).
- Result: [`events/receipts/issue-2.json`](https://github.com/changxinjiresearch/LifeOS/blob/main/events/receipts/issue-2.json), `status=verified`.
- Event: `evt-nextplan-gh-issue-2` is present exactly once in the canonical event history, and the target project status is `completed`.
- User's previously existing projects and milestones were preserved.
- Relevant isolated parser/build-engine tests passed before merge.

## Constraints

- Railway trial expired; the previous v3 SQLite API deployment is **not running**. The dormant v3 code/volume configuration is not the live authority.
- GitHub's scheduled Actions runs may be delayed; a five-minute Cron schedule is **not a guaranteed five-minute SLA**.
- Model tool use: a normal ChatGPT Plus reply is not proof that the GitHub Issue was created. A tool call must return the actual Issue link. Never claim synced if no Issue link exists.
- Issue creation is not proof of final state: look for a verified receipt. Public Issue text must not contain secrets or sensitive documents.
- Destructive operations (delete project/task) require a separate confirmation flow and are not currently accepted via public Issue.
- Only one canonical state authority exists in this active mode. The private DB would need a separate safe migration plan, including UI authorization, before switching.
- Native offline use and arbitrary changes without ChatGPT tool invocation remain separate future features.

## Operational recovery

- If the Issue exists but receipt does not, check the [GitHub Actions history](https://github.com/changxinjiresearch/LifeOS/actions/workflows/nextplan-issue-inbox.yml). On failure, manually use workflow_dispatch or await the next scheduled run; never recreate an already submitted Issue without confirming its state.
- If an Issue returns rejected, inspect the receipt reason and create a **new Issue** after correction; editing an already processed Issue cannot re-execute it.
- If GitHub Actions is paused, disabled, or quota-limited, the Issue remains persisted; execution resumes once the workflow is restored.
- Verify the authoritative state in `state.json` rather than relying on a generated UI badge.

## Remaining future upgrades

Optional native Jarvis API, private SQLite migration, enhanced command coverage, and proactive monitoring are separate from the now-working command transport.
