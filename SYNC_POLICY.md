# Life OS Conversation Sync Policy

## Canonical flow

Conversation -> confirmed state transition -> ChatGPT writes `state.json` -> dashboard refreshes.

No project-specific GitHub repository is required for a task to exist in Life OS.

## Allowed transitions

- `planned`: intended but not started
- `active`: currently actionable / being worked on
- `waiting`: no useful action is currently available; awaiting an external result or dependency
- `blocked`: action is desired but cannot proceed because a dependency/problem must be resolved
- `completed`: explicitly confirmed complete

## Evidence rule

Statements such as “I hope”, “probably”, “I plan”, “maybe tonight”, and “it should be done” do not change a milestone to completed.

Examples that can support completion:
- user explicitly confirms an email was sent
- a submitted form shows a successful submission
- a QA result is confirmed PASS
- an editorial decision is received
- the user and assistant complete a concrete artifact in the conversation

## Automatic assistant behavior

When a conversation produces a clear state transition, update Life OS during the same turn when possible. The user should not need to say “update Life OS”.

## External systems

External GitHub repositories, email, journal portals, university systems, and other apps are evidence sources only. Life OS does not require every task to have its own repository.

## Safety and privacy

Store only task-level metadata. Do not store credentials, temporary download URLs, financial account details, identity-document numbers, health records, private message contents, or other sensitive source material.
