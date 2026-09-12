# NextPlan Conversational State Capture v1

## Purpose

NextPlan should maintain itself from ordinary ChatGPT conversation when the user clearly states a real-world fact, without requiring the user to prefix every update with `NextPlan:`.

## Authority model

1. A clear **user factual assertion** may be evidence for a canonical state change.
2. An **assistant statement is never sufficient evidence by itself** to create or complete a canonical item.
3. Assistant text may provide conversational context, but it must not manufacture the fact that authorizes the write.
4. Discussion, hypothetical language, recommendations, plans, hopes, predictions, and questions do not change canonical state.
5. Negated completion such as `还没做完` must never be interpreted as completion.

## Decision pipeline

`Chat turn -> Fact extraction -> Entity resolution -> Confidence / ambiguity gate -> Permission policy -> Canonical action -> Event -> State builder -> Receipt`

## v1 auto-sync policy

A candidate may auto-sync only when all are true:

- source authority is the user's own factual assertion;
- the target is a known milestone/task;
- the change is non-destructive;
- entity matching is sufficiently strong and unique;
- candidate confidence is at or above the bridge auto-sync threshold;
- no confirmation rule applies.

## Confirmation policy

Confirmation is required when:

- entity resolution is weak or ambiguous;
- the inferred change targets the whole project rather than a known milestone;
- the action is destructive;
- existing permission rules require confirmation.

## Examples that may auto-sync

- `我现在已经把宝宝简历做完了。`
- `编辑回复现在还在等待结果。`
- `搭建自动投简历工作流现在被权限卡住了。`

## Examples that must not auto-sync

- `宝宝简历可能快做完了。`
- `宝宝简历还没做完。`
- `我希望今晚把简历做完。`
- `这个项目应该算完成了吧？`
- Assistant-only: `宝宝简历现在已经正式完成。`

## Provenance

Conversational candidates carry provenance fields including source authority, evidence text, matched subject, entity score, entity margin, and whether assistant text was used as evidence. v1 requires `assistantUsedAsEvidence=false` for autonomous factual writes.

## Compatibility

Explicit `NextPlan:` commands continue through the existing deterministic command classifier. Conversational capture is an additional path, not a replacement for the existing command protocol.
