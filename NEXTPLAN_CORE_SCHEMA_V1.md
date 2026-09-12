# NextPlan Core Schema v1

Status: **FROZEN**

Frozen on: 2026-09-12

This document defines the canonical data model for NextPlan Phase A. It is the authority for all later sync, entity-resolution, workflow, calendar, decision-engine, analytics and automation work.

## 1. Canonical architecture

- Canonical state: `state.json`
- Machine-readable state contract: `state.schema.json`
- Append-only mutation log: `events/inbox/*.json`
- Event merger: `engine/build_state.py`
- Conversation writes must enter through an event or an authenticated backend action that emits an event.
- Normal conversation updates must not rewrite `state.json` directly.

`state.events` is the audit/history stream of state changes. It is **not** a user calendar. User calendar records belong in `calendar_events`.

## 2. Global invariants

1. Every durable entity has a stable string `id`.
2. User-visible progress is derived from canonical state; progress percentages are not authoritative stored facts.
3. Planning is not completion.
4. Waiting items are not actionable.
5. Destructive actions require explicit confirmation unless the exact destructive intent is already unambiguous and the confirmation policy explicitly permits it.
6. Reusing the same immutable event `id` must be idempotent.
7. Sensitive secrets or document contents must never be stored in NextPlan.
8. Dates use ISO `YYYY-MM-DD`.
9. Times use local `HH:MM` 24-hour format. When a time is stored, an IANA timezone should also be stored when known.
10. Relative dates such as “next Wednesday” must be resolved before persistence; relative language itself is not canonical state.

## 3. Status vocabulary

Allowed persisted statuses:

- `planned` — intended, but not currently being worked on.
- `active` — actionable now.
- `waiting` — the next meaningful change depends on an external party/event.
- `blocked` — cannot proceed because a prerequisite/problem prevents action.
- `completed` — finished.
- `done` — legacy terminal project status retained for backward compatibility; new work should prefer `completed`.

For tasks/milestones, `completed` is the preferred terminal status.

## 4. Priority vocabulary

Priority is an integer:

- `1` = low
- `2` = medium
- `3` = high

Priority is one input to future planning logic, not a complete decision by itself.

## 5. Project

Canonical shape:

```json
{
  "id": "project-id",
  "name": "Human readable project name",
  "category": "科研",
  "status": "active",
  "priority": 2,
  "next_action": "Concrete next action",
  "milestones": []
}
```

Required fields:

- `id`
- `name`
- `category`
- `status`
- `priority`
- `next_action`
- `milestones`

Rules:

- `next_action` is the canonical project-level next-action text.
- A project may have more than one active milestone, but the UI should make the current active work obvious.
- `waiting` and `blocked` projects must not enter the actionable-task pool.

## 6. Task / Milestone

NextPlan v1 uses one canonical stored work-item structure for both tasks and milestones. It remains stored inside `project.milestones` for backward compatibility.

Canonical shape:

```json
{
  "id": "task-id",
  "name": "Do the thing",
  "status": "active"
}
```

Optional fields may include:

- `deadline` — ISO date attached directly to the work item.
- `kind` — optional UI/semantic hint such as `task` or `milestone`.

Rules:

- Task/milestone completion is represented by `status = completed`.
- “Current step” is derived from active work items; it is not a separate authoritative top-level field.
- A task and a milestone are semantically different labels but share the same v1 persisted work-item contract.

## 7. Deadline

A deadline is a due date or commitment boundary. It contributes directly to urgency calculations.

Canonical shape:

```json
{
  "id": "deadline-id",
  "title": "Submit assignment",
  "date": "2026-09-16",
  "project_id": "project-id",
  "category": "课程"
}
```

Required fields:

- `id`
- `title`
- `date`

Optional fields:

- `project_id`
- `task_id`
- `category`
- `time`
- `timezone`

A deadline is not the same thing as a meeting or appointment.

## 8. Calendar Event

A calendar event is a scheduled occurrence. Meetings, appointments and presentations belong here even when they are not themselves deadlines.

Canonical v1 shape:

```json
{
  "id": "calendar-event-id",
  "title": "与导师 Meeting",
  "date": "2026-09-16",
  "time": "16:30",
  "timezone": "Australia/Adelaide",
  "kind": "meeting",
  "project_id": "project-id",
  "category": "课程"
}
```

Required fields:

- `id`
- `title`
- `date`
- `kind`

Optional fields:

- `time`
- `timezone`
- `end_time`
- `project_id`
- `task_id`
- `category`
- `location`
- `notes`

Allowed `kind` values for v1:

- `event`
- `meeting`
- `appointment`
- `presentation`
- `reminder`

Timed events should store `timezone` whenever it is known. All-day events omit `time`.

During migration, legacy records with `kind = event` may still exist in `deadlines`; consumers must remain backward compatible until Calendar + Deadline migration is completed.

## 9. Note

Canonical shape:

```json
{
  "id": "note-id",
  "title": "Idea",
  "body": "Non-sensitive note text",
  "category": "Note",
  "at": "2026-09-12T05:00:00Z"
}
```

Notes are not tasks unless the user explicitly turns them into actionable work.

## 10. Resource

Canonical shape:

```json
{
  "id": "resource-id",
  "title": "Paper draft",
  "location": "safe pointer or URL",
  "type": "link",
  "description": "Optional high-level description"
}
```

Resources are pointers. Sensitive document contents, tokens or credentials must never be stored.

## 11. Audit Event

`state.events` stores compact history records created from append-only mutation events.

Canonical history shape:

```json
{
  "id": "evt-...",
  "at": "2026-09-12T05:00:00Z",
  "project_id": "project-id",
  "type": "project_updated",
  "summary": "Updated project",
  "source": {
    "kind": "chatgpt",
    "via": "nextplan-cloud-classifier"
  }
}
```

The immutable source event in `events/inbox/` remains the mutation authority.

## 12. Receipt

A receipt is an execution response, not a canonical planning entity and does not need to live in `state.json`.

Canonical receipt contract:

```json
{
  "status": "applied",
  "operation": "update_project",
  "entity_type": "project",
  "entity_id": "project-id",
  "event_id": "evt-...",
  "summary": "What changed",
  "commit_sha": "optional git commit sha"
}
```

Allowed high-level receipt states:

- `applied`
- `accepted_pending_builder`
- `no_change`
- `already_exists`
- `already_absent`
- `needs_confirmation`
- `rejected`
- `error`

Phase A3 will standardize the full confirmation and receipt behavior.

## 13. Top-level state contract

Canonical `state.json` top-level fields:

```json
{
  "schema_version": 2,
  "system": {},
  "projects": [],
  "deadlines": [],
  "calendar_events": [],
  "notes": [],
  "resources": [],
  "events": []
}
```

`calendar_events` is optional during the migration period. Existing installations that do not yet contain the key remain valid.

## 14. Derived values

The following are derived and must not be treated as independent canonical facts:

- project completion percentage
- overall completion percentage
- current-action card text
- actionable-task list
- Today recommendations
- Now Score / Decision Engine ranking
- analytics summaries

The source of truth for those values is the canonical entities above.

## 15. Freeze rule

Changes to this contract after Phase A1 require an explicit schema-version decision. New features should extend the model without silently redefining existing field meaning.
