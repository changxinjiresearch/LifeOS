# NextPlan Project / Task Workflow v1

Status: **FROZEN FOR PHASE B4**

Version: `1.0`

This contract defines the actionable lifecycle used by NextPlan projects and work items.

## Lifecycle

Persisted statuses remain: `planned`, `active`, `waiting`, `blocked`, `completed` (`done` is legacy terminal compatibility).

- `planned`: intended, not current work.
- `active`: executable now.
- `waiting`: depends on an external response/event and is excluded from actionable work.
- `blocked`: cannot proceed because a prerequisite is missing and is excluded from actionable work.
- `completed`: finished.

## Project/work-item invariants

1. A waiting or blocked project is never eligible for Today / Next Action.
2. Current work is derived from active work items; a separate authoritative `current_step` field is not required.
3. A completed work item remains immutable unless the user explicitly reopens it.
4. Completing a work item may automatically advance the next planned work item when there is no other active work item.
5. If all work items are completed, the project becomes `completed` and its `next_action` becomes a terminal message.
6. If another active work item already exists, completion does not activate an additional planned item.
7. Explicit user status changes override automatic progression.

## Auto-advance rule

For a sequential project, when a `task_completed` or completed milestone event is applied with `auto_advance != false`:

- mark the target work item completed;
- if another active work item exists, keep the project active and do not activate another item;
- otherwise activate the first planned work item after the completed item (falling back to the first planned item);
- set the project `next_action` to the newly active work-item name;
- if no planned work remains and every work item is completed, mark the project completed.

This rule is deterministic in the canonical state builder so every writer observes the same lifecycle.

## Actionability

An actionable candidate requires both:

- project status = `active`; and
- either an active work item or a non-empty project-level `next_action` fallback.

Waiting and blocked work items are not actionable.
