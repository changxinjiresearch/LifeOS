# NextPlan Analytics v1

## Purpose

Analytics answers whether the user's work system is moving and where structural friction exists. It is not a productivity score and is not intended to reward activity for its own sake.

## Core metrics

- project status distribution
- progress by area
- active-project next-action coverage
- milestone status distribution
- state changes in the last 7 and 30 days
- completion events in the last 30 days
- overdue deadlines
- scheduled items in the next 14 days
- stale active projects
- waiting-project age
- note and resource counts

## Calculation rules

Metrics are derived from canonical `state.json`. Progress uses completed milestones divided by tracked milestones. Movement uses timestamped audit events. Waiting and blocked work is reported separately from actionable work. Missing timestamps are displayed as unknown rather than fabricated.

## UI

The Analytics view presents health metrics, movement, schedule pressure, area progress, stale work and knowledge-base counts. The goal is to surface useful patterns with minimal chart clutter.

## Cloud endpoint

Authenticated Thin Bridge clients can request `POST /extension/analytics` with optional `client.now`. The endpoint is read-only and returns a machine-readable snapshot.
