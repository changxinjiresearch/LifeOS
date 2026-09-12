# NextPlan Automation v1

Status: **LOCKED v1**

## Purpose
Automation continuously evaluates canonical NextPlan state and surfaces conditions that deserve attention without silently changing project truth.

## Default rules
1. `overdue-deadline` — surface confirmed deadlines that have passed.
2. `preparation-window` — surface deadlines/presentations whose preparation window is active.
3. `stale-active` — surface active projects with no recorded movement for 7+ days.
4. `waiting-followup` — surface waiting projects with no recorded movement for 7+ days.
5. `blocked-project` — surface blocked projects.
6. `missing-next-action` — surface active projects with no concrete next action.
7. `weekly-review` — surface a weekly-review prompt on Sunday.

Rules are stored in `automation_rules` and can be enabled/disabled or have their supported threshold changed. The latest evaluated findings are stored in `automation_feed`.

## Safety model
Automation v1 is intentionally **observe/recommend first**:
- It may create automation findings and review prompts.
- It does not mark work complete.
- It does not silently create commitments, change project priority, send messages or delete data.
- Any future action that changes project truth must still pass the Sync Command Protocol and confirmation policy.

## Scheduler
GitHub Actions runs the automation evaluator daily and can also be run manually. It writes an append-only `automation_snapshot_refreshed` event, then rebuilds canonical state.

## Cloud API
Authenticated endpoints:
- `POST /extension/automation/preview` — evaluate current state without writing.
- `POST /extension/automation/run` — evaluate and persist a new snapshot.

Cloud actions:
- `upsert_automation_rule`
- `remove_automation_rule`

## State
Top-level canonical state fields:
- `automation_rules: []`
- `automation_feed: []`
- `automation_meta: { last_run_at, finding_count }`

## Completion criteria
Step 12 is complete when the rules, evaluator, scheduled workflow, cloud endpoints, UI surface and contract tests are deployed and the milestone is recorded as completed in canonical state.
