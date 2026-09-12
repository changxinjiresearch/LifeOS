# NextPlan Entity Resolution + Confirmation + Receipt v1

Status: **FROZEN FOR PHASE A3**

Version: `1.0`

This document defines how NextPlan resolves conversational references such as “这个项目”, chooses when confirmation is required, and reports the result of a write.

## 1. Resolution sources

The cloud resolver may use only safe contextual signals already available to NextPlan:

1. exact project/task id or name in the current user turn;
2. exact entity name in the current assistant reply;
3. lexical overlap with project/task name and project `next_action`;
4. conversation title;
5. recent NextPlan audit-event project activity as a weak recency signal.

The resolver must not invent an entity that does not exist in canonical state.

## 2. Referential language

The following kinds of language are treated as references rather than literal entity names when context indicates that usage:

- 这个 / 这个项目 / 该项目
- 那个 / 那个项目
- 当前项目 / 目前这个项目
- 这个任务 / 该任务 / 当前任务
- it / this project / that project / this task

For example, “把这个项目改成 NextPlan开发” must not create or rename a literal project called “这个”.

## 3. Resolution result

A resolver result contains:

```json
{
  "entity_type": "project",
  "entity_id": "project-item-daed6c",
  "entity_name": "NextPlan开发",
  "confidence": 0.91,
  "method": "assistant_exact+recent",
  "requires_confirmation": false,
  "alternatives": []
}
```

Alternatives may be included for audit/debug purposes but should remain compact.

## 4. Confidence and confirmation

General policy:

- exact user name/id match: execute without extra confirmation when operation itself is safe;
- strong contextual match with clear margin: may auto-sync;
- medium-confidence contextual match: create a candidate for the best entity but require confirmation;
- weak or tied match: do not write; return an informational “需要明确目标” result;
- destructive actions always require confirmation even if entity resolution is exact.

Entity confidence and command-intent confidence are distinct concepts. The final candidate confidence must not exceed the weaker critical component.

## 5. Ambiguity margin

The resolver compares the best and second-best candidates. A high score alone is not enough when two entities are nearly tied.

A contextual match may auto-resolve only when both:

- the absolute score is strong; and
- the best candidate has a meaningful margin over the second-best candidate.

Otherwise the best candidate may be proposed for confirmation rather than executed automatically.

## 6. Confirmation behavior

The existing Thin Bridge confirmation queue is the v1 confirmation UI.

A cloud candidate that needs confirmation sets:

```json
{
  "requiresConfirmation": true,
  "confirmation": {
    "required": true,
    "destructive": false,
    "reason": "目标项目由上下文推断，需要确认"
  }
}
```

This preserves the no-local-file-update architecture: confirmation policy can change in Railway without replacing the extension.

## 7. Receipt behavior

All executed actions return the Sync Command Protocol v1 receipt contract.

The receipt must identify, when available:

- operation id;
- operation name;
- entity type;
- entity id;
- resulting event id;
- builder/application status;
- safe summary;
- Git commit sha when available.

The receipt never contains tokens or secret backend configuration.

## 8. Safety rules

- Never resolve sensitive content into a stored NextPlan record.
- Never treat discussion as a confirmed state change.
- Never infer completion solely from intention or planning language.
- Never auto-execute destructive operations.
- When ambiguity is too high, prefer no write over a wrong write.

## 9. Backward compatibility

The Thin Bridge v0.5.0 continues to use `candidate.action`, `requiresConfirmation`, `destructive` and `informational`. All richer resolution metadata is additive and cloud-side only.
