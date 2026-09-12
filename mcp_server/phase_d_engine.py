from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .decision_engine import candidates, recommend
from .phase_c_engine import weekly_review


def _now(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.fromisoformat(str(raw)[:10]).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _project_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(p.get("id")): p for p in state.get("projects", []) if p.get("id")}


def _last_activity(state: dict[str, Any]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for e in state.get("events", []):
        pid = str(e.get("project_id") or "")
        at = _dt(e.get("at"))
        if pid and at and (pid not in out or at > out[pid]):
            out[pid] = at
    return out


def plan_state(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)
    review = weekly_review(state, now)
    focus = recommend(state, now, seed=0)
    projects = _project_map(state)
    interventions: list[dict[str, Any]] = []

    def add(kind: str, severity: str, title: str, reason: str, project_id: str = "", suggested_action: str = ""):
        interventions.append({
            "id": f"plan-{kind}-{project_id or len(interventions)+1}",
            "kind": kind,
            "severity": severity,
            "title": title,
            "reason": reason,
            "project_id": project_id,
            "project_name": projects.get(project_id, {}).get("name", "") if project_id else "",
            "suggested_action": suggested_action,
        })

    for d in review.get("attention", {}).get("overdue_deadlines", []):
        pid = str(d.get("project_id") or "")
        add("resolve_overdue_deadline", "critical", d.get("title") or "Overdue deadline", f"Deadline is {abs(int(d.get('days') or 0))} day(s) overdue.", pid, "Resolve, reschedule, or explicitly close this deadline.")
    for item in review.get("upcoming_14_days", []):
        days = int(item.get("days") or 0)
        if days <= 5:
            pid = str(item.get("project_id") or "")
            add("prepare_upcoming_commitment", "high" if days <= 2 else "medium", item.get("title") or "Upcoming commitment", f"Confirmed event/deadline is in {days} day(s).", pid, "Protect preparation time before the commitment.")
    for row in review.get("attention", {}).get("missing_next_action", []):
        pid = str(row.get("project_id") or "")
        add("define_next_action", "high", row.get("name") or "Active project", "Active work has no concrete next action.", pid, "Define one small, executable next action.")
    for p in state.get("projects", []):
        pid = str(p.get("id") or "")
        if p.get("status") == "blocked":
            add("unstick_blocked_project", "high", p.get("name") or "Blocked project", "Project is blocked and cannot enter the execution queue.", pid, "Define the unblock condition or move it to waiting.")
    for row in review.get("attention", {}).get("stale_active", []):
        pid = str(row.get("project_id") or "")
        age = row.get("days_since_activity")
        add("review_stale_active_project", "medium", row.get("name") or "Stale active project", f"No recorded movement for {age if age is not None else '7+'} day(s).", pid, "Advance it, pause it, or redefine its next action.")
    activity = _last_activity(state)
    for p in state.get("projects", []):
        if p.get("status") != "waiting":
            continue
        pid = str(p.get("id") or "")
        last = activity.get(pid)
        age = (now - last).days if last else None
        if age is None or age >= 7:
            add("follow_up_waiting_project", "medium", p.get("name") or "Waiting project", f"Waiting state has had no recorded movement for {age if age is not None else '7+'} day(s).", pid, "Check whether new information arrived or a follow-up is appropriate.")

    if not interventions and focus:
        add("continue_focus", "normal", focus.get("title") or "Current focus", focus.get("why") or "Highest current decision score.", str(focus.get("project_id") or ""), focus.get("next_action") or focus.get("title") or "Continue current focus.")

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "normal": 3}
    interventions.sort(key=lambda x: (severity_rank.get(x["severity"], 9), x["title"]))
    active = sum(1 for p in state.get("projects", []) if p.get("status") == "active")
    waiting = sum(1 for p in state.get("projects", []) if p.get("status") == "waiting")
    blocked = sum(1 for p in state.get("projects", []) if p.get("status") == "blocked")
    return {
        "planning_version": "1.0",
        "generated_at": now.isoformat(),
        "focus_now": focus,
        "top_candidates": candidates(state, now)[:5],
        "horizon_14_days": review.get("upcoming_14_days", []),
        "capacity": {"active": active, "waiting": waiting, "blocked": blocked, "stale_active": len(review.get("attention", {}).get("stale_active", []))},
        "interventions": interventions[:20],
        "explanation": "Plan is derived from confirmed state, time pressure, actionability and recent movement. Suggestions do not mutate project truth without confirmation.",
    }


DEFAULT_AUTOMATION_RULES = [
    {"id": "overdue-deadline", "name": "Overdue deadlines", "enabled": True, "kind": "overdue_deadline"},
    {"id": "preparation-window", "name": "Preparation windows", "enabled": True, "kind": "preparation_window", "threshold_days": 5},
    {"id": "stale-active", "name": "Stale active projects", "enabled": True, "kind": "stale_active", "threshold_days": 7},
    {"id": "waiting-followup", "name": "Waiting follow-up", "enabled": True, "kind": "waiting_followup", "threshold_days": 7},
    {"id": "blocked-project", "name": "Blocked projects", "enabled": True, "kind": "blocked_project"},
    {"id": "missing-next-action", "name": "Missing next action", "enabled": True, "kind": "missing_next_action"},
    {"id": "weekly-review", "name": "Weekly review prompt", "enabled": True, "kind": "weekly_review", "weekday": 6},
]


def effective_rules(state: dict[str, Any]) -> list[dict[str, Any]]:
    overrides = {str(r.get("id")): r for r in state.get("automation_rules", []) if r.get("id")}
    out = []
    for base in DEFAULT_AUTOMATION_RULES:
        merged = dict(base)
        merged.update(overrides.get(base["id"], {}))
        out.append(merged)
    for rid, r in overrides.items():
        if rid not in {x["id"] for x in DEFAULT_AUTOMATION_RULES}:
            out.append(dict(r))
    return out


def evaluate_automations(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)
    review = weekly_review(state, now)
    rules = effective_rules(state)
    findings: list[dict[str, Any]] = []
    activity = _last_activity(state)

    def rule(rule_id: str) -> dict[str, Any] | None:
        r = next((x for x in rules if x.get("id") == rule_id and x.get("enabled", True)), None)
        return r

    if rule("overdue-deadline"):
        for d in review.get("attention", {}).get("overdue_deadlines", []):
            findings.append({"rule_id": "overdue-deadline", "severity": "critical", "title": d.get("title"), "project_id": d.get("project_id") or "", "reason": f"Deadline overdue by {abs(int(d.get('days') or 0))} day(s)."})
    r = rule("preparation-window")
    if r:
        threshold = max(0, int(r.get("threshold_days", 5)))
        for item in review.get("upcoming_14_days", []):
            days = int(item.get("days") or 0)
            if days <= threshold:
                findings.append({"rule_id": "preparation-window", "severity": "high" if days <= 2 else "medium", "title": item.get("title"), "project_id": item.get("project_id") or "", "reason": f"Confirmed commitment enters preparation window: {days} day(s) remaining."})
    r = rule("stale-active")
    if r:
        threshold = max(1, int(r.get("threshold_days", 7)))
        for p in state.get("projects", []):
            if p.get("status") != "active":
                continue
            pid = str(p.get("id") or "")
            last = activity.get(pid)
            age = (now - last).days if last else None
            if age is None or age >= threshold:
                findings.append({"rule_id": "stale-active", "severity": "medium", "title": p.get("name"), "project_id": pid, "reason": f"No recorded movement for {age if age is not None else threshold} day(s)."})
    r = rule("waiting-followup")
    if r:
        threshold = max(1, int(r.get("threshold_days", 7)))
        for p in state.get("projects", []):
            if p.get("status") != "waiting":
                continue
            pid = str(p.get("id") or "")
            last = activity.get(pid)
            age = (now - last).days if last else None
            if age is None or age >= threshold:
                findings.append({"rule_id": "waiting-followup", "severity": "medium", "title": p.get("name"), "project_id": pid, "reason": f"Waiting project has no recorded movement for {age if age is not None else threshold} day(s)."})
    if rule("blocked-project"):
        for p in state.get("projects", []):
            if p.get("status") == "blocked":
                findings.append({"rule_id": "blocked-project", "severity": "high", "title": p.get("name"), "project_id": p.get("id") or "", "reason": "Project is blocked."})
    if rule("missing-next-action"):
        for p in state.get("projects", []):
            if p.get("status") == "active" and not str(p.get("next_action") or "").strip() and not any(m.get("status") == "active" for m in p.get("milestones", [])):
                findings.append({"rule_id": "missing-next-action", "severity": "high", "title": p.get("name"), "project_id": p.get("id") or "", "reason": "Active project has no next action."})
    r = rule("weekly-review")
    if r and now.weekday() == int(r.get("weekday", 6)):
        findings.append({"rule_id": "weekly-review", "severity": "normal", "title": "Weekly Review", "project_id": "", "reason": "Scheduled weekly review day."})

    seen, deduped = set(), []
    for f in findings:
        key = (f.get("rule_id"), f.get("project_id"), f.get("title"), f.get("reason"))
        if key not in seen:
            seen.add(key)
            f["id"] = f"automation-{f.get('rule_id')}-{len(deduped)+1}"
            deduped.append(f)
    return {"automation_version": "1.0", "generated_at": now.isoformat(), "rules": rules, "finding_count": len(deduped), "findings": deduped}
