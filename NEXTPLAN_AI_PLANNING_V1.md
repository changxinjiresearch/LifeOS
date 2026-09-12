# NextPlan AI Planning v1

Status: **LOCKED v1**

## Purpose
AI Planning converts canonical NextPlan state into a small, explainable planning brief. It does **not** silently rewrite project state. Suggestions remain recommendations until the user confirms a write.

## Inputs
- Projects, milestones/tasks and statuses
- `next_action` and priority
- Deadlines and calendar events
- Recent state-change history
- Waiting / blocked age
- Notes and resources only as contextual pointers; their contents are not treated as completion evidence

## Planning outputs
`plan_state(state, now)` returns:
- `focus_now`: the highest-scoring actionable item from Decision Engine v1
- `horizon_14_days`: confirmed deadline/calendar pressure
- `interventions`: ranked planning suggestions
- `capacity`: counts of active, waiting, blocked and stale work
- `explanation`: human-readable rationale for the plan

## Intervention types
1. `resolve_overdue_deadline`
2. `prepare_upcoming_commitment`
3. `define_next_action`
4. `unstick_blocked_project`
5. `review_stale_active_project`
6. `follow_up_waiting_project`
7. `continue_focus`

Each intervention has an ID, severity, project reference when available, reason and a safe suggested action. Suggestions never imply that a task is complete.

## Guardrails
- Waiting and blocked work are not recommended as immediate execution work.
- Only confirmed dates influence time pressure.
- Planning cannot mark work complete.
- Planning cannot create tasks or change priorities without user confirmation.
- Sensitive contents are not copied into the plan.
- The output is deterministic for the same state and time, except where Decision Engine v1 intentionally uses controlled near-top selection.

## API
Authenticated cloud endpoint:
`POST /extension/ai-plan`

Payload may include `client.now` and `client.timezone`.

## Completion criteria
Step 11 is complete when the planning engine, endpoint, UI surface and contract tests are deployed and the milestone is recorded as completed in canonical state.
