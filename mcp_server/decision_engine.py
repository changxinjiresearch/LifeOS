from __future__ import annotations

import math
import random
from datetime import date, datetime, timezone
from typing import Any


PRIORITY_POINTS = {1: 20.0, 2: 35.0, 3: 50.0}


def _date_value(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _now_date(now: datetime | None) -> date:
    return (now or datetime.now(timezone.utc)).date()


def _days_until(raw: Any, now: datetime | None) -> int | None:
    d = _date_value(raw)
    return None if d is None else (d - _now_date(now)).days


def _deadline_urgency(days: int | None) -> float:
    if days is None:
        return 0.0
    if days <= 0:
        return 55.0
    if days == 1:
        return 50.0
    if days == 2:
        return 44.0
    if days == 3:
        return 36.0
    if days <= 7:
        return max(12.0, 30.0 - (days - 4) * 4.5)
    if days <= 14:
        return max(2.0, 10.0 - (days - 8) * 1.2)
    return 0.0


def _preparation_bonus(days: int | None, prep_days: int) -> float:
    if days is None or prep_days <= 0 or days < 0 or days > prep_days:
        return 0.0
    if prep_days == 0:
        return 0.0
    progress = (prep_days - days) / max(1, prep_days)
    return 10.0 + 16.0 * progress


def _activity_bonus(raw: Any, now: datetime | None) -> tuple[float, float]:
    if not raw:
        return 0.0, 0.0
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0, 0.0
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    age = max(0.0, (ref - dt.astimezone(ref.tzinfo)).total_seconds() / 86400.0)
    continuity = 8.0 if age <= 1 else 4.0 if age <= 3 else 0.0
    neglect = 0.0 if age < 7 else min(12.0, 2.0 + (age - 7) * 0.8)
    return continuity, neglect


def _applicable_deadlines(state: dict[str, Any], project: dict[str, Any], task: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if task:
        raw = task.get("deadline") or task.get("due")
        if raw:
            out.append({"date": raw, "title": task.get("name", "Task deadline"), "prep_days": task.get("prep_days")})
    raw = project.get("deadline") or project.get("due")
    if raw:
        out.append({"date": raw, "title": project.get("name", "Project deadline"), "prep_days": project.get("prep_days")})
    for d in state.get("deadlines", []) or []:
        if d.get("task_id") and task and str(d.get("task_id")) == str(task.get("id")):
            out.append(d)
        elif d.get("project_id") and str(d.get("project_id")) == str(project.get("id")):
            out.append(d)
    for e in state.get("calendar_events", []) or []:
        if str(e.get("project_id", "")) != str(project.get("id")):
            continue
        if e.get("kind") not in {"presentation", "meeting"}:
            continue
        item = dict(e)
        item["_calendar"] = True
        out.append(item)
    return out


def candidates(state: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for project in state.get("projects", []) or []:
        if project.get("status") != "active":
            continue
        active = [m for m in (project.get("milestones") or []) if m.get("status") == "active"]
        work_items: list[dict[str, Any] | None] = active or ([None] if str(project.get("next_action") or "").strip() else [])
        for task in work_items:
            priority = int(project.get("priority") or 1)
            p_points = PRIORITY_POINTS.get(priority, 20.0)
            applicable = _applicable_deadlines(state, project, task)
            nearest = None
            nearest_days = None
            for item in applicable:
                d = _days_until(item.get("date") or item.get("due"), now)
                if d is None:
                    continue
                if nearest_days is None or d < nearest_days:
                    nearest, nearest_days = item, d
            urgency = _deadline_urgency(nearest_days)
            explicit_prep = None
            if task and task.get("prep_days") is not None:
                explicit_prep = task.get("prep_days")
            elif project.get("prep_days") is not None:
                explicit_prep = project.get("prep_days")
            elif nearest and nearest.get("prep_days") is not None:
                explicit_prep = nearest.get("prep_days")
            if explicit_prep is None:
                if nearest and nearest.get("kind") == "presentation":
                    prep_days = 5
                elif nearest and nearest.get("_calendar"):
                    prep_days = 1
                else:
                    prep_days = 3
            else:
                try:
                    prep_days = max(0, int(explicit_prep))
                except (TypeError, ValueError):
                    prep_days = 3
            preparation = _preparation_bonus(nearest_days, prep_days)
            last_worked = (task or {}).get("last_worked_at") or project.get("last_worked_at")
            continuity, neglect = _activity_bonus(last_worked, now)
            score = round(p_points + urgency + preparation + continuity + neglect, 2)
            reasons = [f"{['Low','Medium','High'][max(1,min(3,priority))-1]} priority"]
            if nearest_days is not None:
                if nearest_days <= 0:
                    reasons.append("deadline is due/overdue")
                else:
                    reasons.append(f"deadline in {nearest_days} day{'s' if nearest_days != 1 else ''}")
                if preparation > 0:
                    reasons.append("preparation window active")
            if continuity > 0:
                reasons.append("continuity bonus")
            if neglect > 0:
                reasons.append("long-term item has been neglected")
            result.append({
                "key": f"{project.get('id')}::{(task or {}).get('id') or 'project'}",
                "project_id": project.get("id"),
                "project_name": project.get("name"),
                "task_id": (task or {}).get("id"),
                "title": (task or {}).get("name") or project.get("next_action") or project.get("name"),
                "next_action": project.get("next_action") or "",
                "priority": priority,
                "score": score,
                "deadline_days": nearest_days,
                "deadline_title": (nearest or {}).get("title"),
                "factors": {
                    "priority": p_points,
                    "urgency": urgency,
                    "preparation": round(preparation, 2),
                    "continuity": continuity,
                    "neglect": round(neglect, 2),
                },
                "why": "; ".join(reasons),
            })
    return sorted(result, key=lambda x: (-x["score"], x["project_name"], x["title"]))


def recommend(state: dict[str, Any], now: datetime | None = None, exclude_key: str | None = None, seed: int | None = None) -> dict[str, Any] | None:
    pool = [x for x in candidates(state, now) if x["key"] != exclude_key]
    if not pool:
        return None
    top = pool[0]
    second = pool[1] if len(pool) > 1 else None
    deterministic = top.get("deadline_days") is not None and top["deadline_days"] <= 2
    if second is None or top["score"] - second["score"] >= 15:
        deterministic = True
    if deterministic:
        picked = top
        mode = "deterministic"
    else:
        near = [x for x in pool if top["score"] - x["score"] <= 12][:5]
        temperature = 6.0
        weights = [math.exp((x["score"] - top["score"]) / temperature) for x in near]
        rng = random.Random(seed)
        picked = rng.choices(near, weights=weights, k=1)[0]
        mode = "weighted-near-top"
    return {**picked, "selection_mode": mode, "candidate_count": len(pool)}
