# NextPlan Agent Protocol v1

NextPlan is the user's cross-domain personal control plane. The private repository `changxinjiresearch/LifeOS` is the canonical state store. ChatGPT conversations are allowed to emit confirmed state changes into the append-only event layer.

## Core rule

Do not rewrite `state.json` directly for normal conversation updates. Write one immutable JSON event file to `events/inbox/`. GitHub Actions serializes and merges events into `state.json` using `engine/build_state.py`.

Use a unique filename such as:

`events/inbox/20260911T001600+0930_evt-20260911-example.json`

The event `id` must also be unique and stable. Reusing an event id is idempotent: the builder will not apply it twice.

## When ChatGPT SHOULD write an event

Write an event in the same turn when the conversation confirms one of these:

1. A real new task or project has been explicitly decided.
2. A task, milestone, submission, email, application, or other action has actually been completed.
3. A project changes to waiting, active, blocked, completed, or another confirmed status.
4. A concrete deadline/date is confirmed.
5. The user explicitly asks to save an idea as a Note.
6. The user explicitly asks to add a non-sensitive resource pointer.

## When ChatGPT MUST NOT write an event

Do not record ordinary discussion, brainstorming, hypotheticals, questions, possibilities, emotional conversation, tentative plans, or unconfirmed completion.

Examples:

- "Should I apply to ANU?" -> no event.
- "I might contact ANU." -> no event.
- "I decided to apply to ANU and start contacting supervisors." -> create/update a real PhD task/project.
- "I drafted the email." -> do not mark sent.
- "I sent the email." -> mark the send milestone completed and usually change the relevant line to waiting if the next dependency is external.

If meaning is genuinely ambiguous, ask before creating a state-changing event.

## Status semantics

- `active`: the user can take a concrete action now.
- `waiting`: the next meaningful change depends on an external party/event; do not recommend as an actionable task.
- `planned`: intended but not currently active.
- `blocked`: cannot proceed because a prerequisite/problem prevents action.
- `completed`: milestone completed.
- `done`: project completed.

Planning is not completion. Drafting is not sending. Uploading is not acceptance. Submission is not approval.

## Duplicate prevention

Before emitting a new task/project event, fetch `state.json` and check whether the same project/milestone already exists. Prefer updating an existing milestone instead of creating a duplicate. The builder also protects against duplicate event IDs and same-name milestones inside one project.

## Concurrency model

Each chat writes a separate event file. Chats never compete to replace the same whole state file. The state-builder workflow uses a single concurrency group and applies all unprocessed events before committing the canonical state.

## Privacy

Never store passwords, tokens, API keys, bank details, passport/identity numbers, private medical records, or sensitive document contents. NextPlan records only high-level task/status metadata and safe resource pointers.

## Supported event types

- `project_created`
- `project_updated`
- `project_status_changed`
- `milestone_added`
- `milestone_status_changed`
- `task_created`
- `task_updated`
- `task_completed`
- `deadline_set`
- `deadline_removed`
- `note_added`
- `resource_added`
- `event_only`

See `event.schema.json` for the machine-readable envelope. The builder supports optional `next_action` and `project_status` fields where appropriate.

## Response behavior

When an event is written successfully, ChatGPT may briefly say that NextPlan was synchronized. Do not make the user manually adjust progress bars for changes that ChatGPT can safely infer from confirmed work.
