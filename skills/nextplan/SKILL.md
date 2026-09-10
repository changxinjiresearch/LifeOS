---
name: nextplan
description: Keep the user's NextPlan personal task and project system synchronized from ordinary ChatGPT conversations. Use whenever a conversation may have created a real commitment, completed an existing task or milestone, changed a project status, established a confirmed deadline, or explicitly requested a note/resource to be saved—even when the user does not mention NextPlan. Do not write mere discussion, brainstorming, questions, hypotheticals, tentative plans, or unconfirmed completion.
metadata:
  version: "1.0.0"
  system: "NextPlan"
---

# NextPlan conversation synchronization

NextPlan is the user's canonical cross-domain task/project state. The user should be able to work normally in ChatGPT without manually maintaining progress bars or repeatedly saying “update NextPlan.”

The user's explicit instructions always take precedence over this skill.

## Core behavior

At the end of substantive work, silently evaluate whether the conversation established a **confirmed state change**. If it did, use the connected **NextPlan** app in the same turn before finishing the response.

Do not announce or ask about synchronization when the state change is clear and the app is available, unless ChatGPT's action-permission system itself requires approval.

If there is no qualifying state change, do nothing.

## What counts as a qualifying state change

Record these:

- The user clearly decides to undertake a new task or project.
- The user confirms an existing task or milestone is completed.
- Reliable evidence in the current workflow confirms completion or a project status transition.
- A project/task changes between active, waiting, planned, blocked, completed/done.
- A concrete deadline/date is confirmed.
- The user explicitly asks to preserve a non-sensitive idea as a Note.
- The user explicitly asks to index a safe resource pointer/location.

Do **not** record these:

- Questions such as “Should I apply to ANU?”
- Brainstorming, exploration, comparisons, or possible future options.
- “Maybe,” “I might,” “I’m thinking about,” or other tentative intentions.
- A draft being prepared when the real action is sending/submitting it.
- Claims of completion that are ambiguous or contradicted by the workflow.
- Casual conversation that does not create an obligation or state transition.
- Secrets or sensitive personal data.

If the distinction materially affects the state and is genuinely ambiguous, ask one short clarification before writing.

## State-before-write rule

Before creating a project or task, use `get_state` or `search_state` when needed to match the existing canonical item.

Prefer updating an existing item over creating a duplicate.

When a user refers to an item by natural language rather than an ID:

1. Search the current NextPlan state.
2. Match the existing project/task only when the identity is clear.
3. If multiple plausible matches exist, ask which one.

## Tool mapping

Use the connected NextPlan app tools as follows:

- New committed project → `create_project`
- New committed task → `create_task`
- Confirmed task completion → `complete_task`
- Milestone status change → `update_milestone`
- Project status/next-action/priority change → `update_project`
- Confirmed date/deadline → `set_deadline`
- Explicit idea/note preservation → `add_note`
- Explicit safe resource pointer → `add_resource`
- Read/match existing state → `get_state` or `search_state`

## Completion semantics

Do not collapse intermediate work into final completion.

Examples:

- “The email draft is ready.” → drafting may be complete, but **do not** mark “email sent” complete.
- “I sent the email.” → mark the send task complete; if the only next step is an external reply, set the relevant project/line to Waiting.
- “I submitted the revision.” → submission can be completed; publication/acceptance remains unresolved.
- “The editor accepted the paper.” → record the acceptance only when explicitly confirmed by the user or reliable evidence.

## Waiting semantics

Waiting means there is currently no useful action the user can take because the next transition depends on an external event.

When a confirmed action ends with external dependency, update the relevant project/line to `waiting` and set a clear next action such as “wait for supervisor reply.”

Do not put Waiting items into the actionable-task queue.

## Privacy boundary

NextPlan stores high-level planning metadata, not sensitive records.

Never write:

- passwords, tokens, API keys, secret URLs, recovery codes
- bank account numbers, card details, transaction evidence, unexplained-funds documentation
- passport/identity numbers or copies
- medical diagnoses/records or detailed health data
- private document contents whose text is not necessary for task tracking

A safe entry is high-level, for example “Prepare visa documents — active,” not the underlying financial or identity details.

## Examples

User: “我是不是应该申请 ANU？”
Action: no NextPlan write.

User: “好，我决定申请 ANU，接下来开始联系导师。”
Action: find the PhD application project, then create/update the ANU outreach task.

User: “邮件写完了，但还没发。”
Action: do not mark the send task complete.

User: “邮件已经发出去了。”
Action: complete the matching send task and, if appropriate, move that line to Waiting.

User: “这个想法以后可能有用，先记下来，但别变成任务。”
Action: `add_note`, not `create_task`.

User: “这个 deadline 是 12 月 18 日，确定了。”
Action: `set_deadline` with the confirmed date.

## Failure behavior

If the NextPlan app is temporarily unavailable, do not pretend the state was updated. Finish the user's main task, then state briefly that NextPlan synchronization could not be completed and identify the technical reason if known.

Never claim a write succeeded unless the tool reports success or accepted processing.
