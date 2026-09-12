# NextPlan Calendar + Deadline v1

Status: **FROZEN FOR PHASE B6**

Version: `1.0`

Calendar and deadline are distinct canonical concepts.

## Deadline

A deadline is a due boundary that contributes strongly to urgency.

Required: `id`, `title`, `date`.

Optional: `time`, `timezone`, `project_id`, `task_id`, `category`, `prep_days`.

## Calendar Event

A calendar event is a scheduled occurrence. Meetings, appointments, presentations and reminders belong here.

Required: `id`, `title`, `date`, `kind`.

Optional: `time`, `end_time`, `timezone`, `project_id`, `task_id`, `category`, `location`, `notes`, `prep_days`.

Allowed v1 kinds: `event`, `meeting`, `appointment`, `presentation`, `reminder`.

## Natural-language persistence

Relative language is resolved before writing. For example, with an Adelaide client context on 2026-09-12, “下周三下午四点半和导师有一个 meeting” resolves to `2026-09-16`, `16:30`, IANA timezone `Australia/Adelaide`, kind `meeting`.

Words such as `deadline` / `截止` create or update a Deadline. Meeting / appointment / presentation / reminder language creates or updates a Calendar Event. They are not stored in the same collection.

## Canonical events

- `deadline_set`
- `deadline_removed`
- `calendar_event_upserted`
- `calendar_event_removed`

Legacy calendar-like records already present in `deadlines` remain readable during migration, but all new scheduled occurrences use `calendar_events`.

## UI contract

Calendar views merge deadlines and calendar events for display while preserving their type. Upcoming lists show time when present. Deadline items remain urgency inputs; linked presentation/calendar events may provide preparation-window input to the Decision Engine.
