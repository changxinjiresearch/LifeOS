# Changxin Life OS

Private central state repository for Changxin Life OS.

## Architecture

- ChatGPT conversation = control plane.
- This repository = canonical progress/state store.
- The Life OS browser app = read-only dashboard.
- External systems (GitHub research repositories, email, journal portals, university portals, etc.) are evidence sources only.
- After a task is explicitly confirmed as completed, started, blocked, or waiting in conversation, ChatGPT updates `state.json`.

## State policy

1. Discussion does not change status.
2. Planning does not equal completion.
3. Completion requires explicit evidence or confirmation.
4. Waiting items are excluded from “What should I do now?”
5. Every meaningful state change should add an event.
6. Never store passwords, tokens, passport numbers, bank records, medical records, private correspondence, or other sensitive documents here.
7. For sensitive/admin topics, store only high-level task status and next action.

## Files

- `state.json` — canonical project, milestone and event state.
- `SYNC_POLICY.md` — update rules used by ChatGPT and the dashboard.

This repository should remain private.
