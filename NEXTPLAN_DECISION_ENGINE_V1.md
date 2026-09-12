# NextPlan Decision Engine v1

Status: **FROZEN FOR PHASE B5**

Version: `1.0`

The Decision Engine answers one question: **What should I do now?** It does not replace the project dashboard.

## Candidate gate

A candidate is eligible only when its project is `active`. Waiting, blocked, planned and completed projects are excluded. Within an active project, active work items are preferred; if no active work item exists, the project `next_action` may be used as a fallback.

## Now Score

The v1 score is additive and explainable:

`NowScore = Priority + DeadlineUrgency + PreparationWindow + Continuity + Neglect`

Actionability is a hard gate rather than a multiplier.

### Priority

- low / 1: 20
- medium / 2: 35
- high / 3: 50

### Deadline urgency

The nearest applicable deadline for the work item/project is used. Urgency rises non-linearly as the due date approaches. A due/overdue item is dominant; 1–3 day deadlines receive a large boost.

### Preparation window

Optional `prep_days` activates advance preparation before the due date. Default preparation windows are conservative when no explicit value exists. Presentation-like scheduled events can contribute a preparation signal to a linked project.

### Continuity

Optional `last_worked_at` provides a small bonus for continuing recently started work, reducing unnecessary context switching.

### Neglect

An important active item that has not been worked on for a sustained period can receive a bounded neglect bonus. Missing activity history does not invent a penalty or bonus.

## Selection policy

- If the leading candidate is deadline-critical or clearly dominates the runner-up, choose it deterministically.
- If several candidates are close, weighted selection is allowed only within the near-top pool.
- `Pick something else` excludes the current recommendation for that draw and selects from the remaining near-top/actionable candidates.
- The engine always returns an explanation containing the factors that materially contributed to the result.

## Safety / consistency

- Waiting and blocked projects never enter the pool.
- A close score never overrides a hard deadline with <=2 days remaining.
- The same scoring algorithm is available in the Railway backend; the web UI mirrors the frozen v1 formula for immediate client-side recommendations from canonical state.
