# NextPlan Weekly Review v1

## Purpose

Weekly Review is a derived health check over the canonical NextPlan state. It does not invent progress and does not mutate project status. Its job is to expose movement, waiting/blocked work, stale active work, missing next actions, overdue deadlines, and the next 14 days of scheduled commitments.

## Review window

- Primary movement window: last 7 days.
- Schedule horizon: next 14 days.
- Overdue detection: confirmed deadlines strictly before today.
- Stale active project: active project with no recorded project activity for at least 7 days, or no recorded activity timestamp.

## Output contract

`review_version`, `generated_at`, `window_days`, `movement`, `status`, `attention`, `upcoming_14_days`, `suggestions`.

The review is deterministic from canonical state. Waiting and blocked projects remain visible as attention items but are not converted into actionable recommendations.

## UI

The NextPlan web app exposes a dedicated Weekly Review view. It shows recent movement, completion events, waiting/blocked projects, stale active projects, missing next actions, upcoming 14-day commitments and concise review prompts.

## Cloud endpoint

Authenticated Thin Bridge clients can request `POST /extension/weekly-review` with optional `client.now`. The endpoint returns a machine-readable review without changing state.
