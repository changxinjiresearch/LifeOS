from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any

DAY = timedelta(days=1)


def _dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _now(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _project_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(p.get("id")): p for p in state.get("projects", []) if p.get("id")}


def _last_activity_by_project(state: dict[str, Any]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for e in state.get("events", []):
        pid = str(e.get("project_id") or "")
        at = _dt(e.get("at"))
        if not pid or not at:
            continue
        if pid not in out or at > out[pid]:
            out[pid] = at
    return out


def _calendar_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for d in state.get("deadlines", []):
        date = _dt(d.get("date") or d.get("due"))
        if date:
            items.append({**d, "_date": date, "_type": "deadline"})
    for e in state.get("calendar_events", []):
        date = _dt(e.get("date") or e.get("due"))
        if date:
            items.append({**e, "_date": date, "_type": "calendar_event"})
    return sorted(items, key=lambda x: (x["_date"], str(x.get("time") or "")))


def weekly_review(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)
    start = now - 7 * DAY
    projects = state.get("projects", [])
    events = [e for e in state.get("events", []) if (_dt(e.get("at")) or datetime.min.replace(tzinfo=timezone.utc)) >= start]
    last_activity = _last_activity_by_project(state)

    completion_types = {
        "task_completed",
        "milestone_completed",
        "milestone_status_changed",
        "project_status_changed",
    }
    completed_events = []
    for e in events:
        if e.get("type") not in completion_types:
            continue
        summary = str(e.get("summary") or "")
        if e.get("type") == "milestone_status_changed" and "completed" not in summary.casefold():
            continue
        completed_events.append(e)

    waiting = [p for p in projects if p.get("status") == "waiting"]
    blocked = [p for p in projects if p.get("status") == "blocked"]
    active = [p for p in projects if p.get("status") == "active"]
    stale = []
    missing_next = []
    for p in active:
        pid = str(p.get("id") or "")
        last = last_activity.get(pid)
        age = (now - last).days if last else None
        if last is None or age >= 7:
            stale.append({
                "project_id": pid,
                "name": p.get("name"),
                "days_since_activity": age,
                "priority": p.get("priority", 1),
            })
        active_tasks = [m for m in p.get("milestones", []) if m.get("status") == "active"]
        if not str(p.get("next_action") or "").strip() and not active_tasks:
            missing_next.append({"project_id": pid, "name": p.get("name")})

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    upcoming = []
    overdue = []
    for item in _calendar_items(state):
        delta = (item["_date"].date() - today.date()).days
        row = {
            "id": item.get("id"),
            "title": item.get("title") or item.get("name") or "Untitled",
            "date": item["_date"].date().isoformat(),
            "time": item.get("time") or "",
            "kind": item.get("kind") or item["_type"],
            "type": item["_type"],
            "project_id": item.get("project_id"),
            "days": delta,
        }
        if delta < 0 and item["_type"] == "deadline":
            overdue.append(row)
        elif 0 <= delta <= 14:
            upcoming.append(row)

    suggestions: list[str] = []
    if overdue:
        suggestions.append(f"Resolve {len(overdue)} overdue deadline(s) first.")
    if blocked:
        suggestions.append(f"Review {len(blocked)} blocked project(s) and identify an unblock condition.")
    if stale:
        suggestions.append(f"Choose a next action for {len(stale)} active project(s) with no movement for at least a week.")
    if missing_next:
        suggestions.append(f"Add a concrete next action to {len(missing_next)} active project(s).")
    if not suggestions:
        suggestions.append("No structural warning detected; continue the highest-scoring current action.")

    return {
        "review_version": "1.0",
        "generated_at": now.isoformat(),
        "window_days": 7,
        "movement": {
            "state_changes": len(events),
            "completion_events": len(completed_events),
            "completed": [
                {"summary": e.get("summary"), "at": e.get("at"), "project_id": e.get("project_id")}
                for e in completed_events[:20]
            ],
        },
        "status": {
            "active": len(active),
            "waiting": len(waiting),
            "blocked": len(blocked),
            "waiting_projects": [{"id": p.get("id"), "name": p.get("name")} for p in waiting],
            "blocked_projects": [{"id": p.get("id"), "name": p.get("name")} for p in blocked],
        },
        "attention": {
            "stale_active": stale,
            "missing_next_action": missing_next,
            "overdue_deadlines": overdue,
        },
        "upcoming_14_days": upcoming[:30],
        "suggestions": suggestions,
    }


def analytics_snapshot(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)
    projects = state.get("projects", [])
    events = state.get("events", [])
    milestones = [(p, m) for p in projects for m in p.get("milestones", [])]
    last_activity = _last_activity_by_project(state)

    status_counts = Counter(str(p.get("status") or "unknown") for p in projects)
    area_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in projects:
        area_groups[str(p.get("category") or "Other")].append(p)

    def pct(p: dict[str, Any]) -> int:
        ms = p.get("milestones", [])
        if not ms:
            return 100 if p.get("status") in {"completed", "done"} else 0
        return round(100 * sum(1 for m in ms if m.get("status") in {"completed", "done"}) / len(ms))

    area_progress = {
        area: round(sum(pct(p) for p in group) / len(group)) if group else 0
        for area, group in area_groups.items()
    }
    event_dates = [_dt(e.get("at")) for e in events]
    event_dates = [d for d in event_dates if d]
    events_7 = sum(1 for d in event_dates if d >= now - 7 * DAY)
    events_30 = sum(1 for d in event_dates if d >= now - 30 * DAY)
    completion_events_30 = 0
    for e in events:
        d = _dt(e.get("at"))
        if not d or d < now - 30 * DAY:
            continue
        typ = str(e.get("type") or "")
        summary = str(e.get("summary") or "").casefold()
        if typ in {"task_completed", "milestone_completed"} or (typ == "milestone_status_changed" and "completed" in summary):
            completion_events_30 += 1

    active_projects = [p for p in projects if p.get("status") == "active"]
    next_action_coverage = 0
    if active_projects:
        next_action_coverage = round(100 * sum(bool(str(p.get("next_action") or "").strip()) for p in active_projects) / len(active_projects))

    stale = []
    for p in active_projects:
        last = last_activity.get(str(p.get("id") or ""))
        age = (now - last).days if last else 9999
        stale.append({"id": p.get("id"), "name": p.get("name"), "days": None if age == 9999 else age})
    stale.sort(key=lambda x: 9999 if x["days"] is None else x["days"], reverse=True)

    waiting_ages = []
    for p in projects:
        if p.get("status") != "waiting":
            continue
        last = last_activity.get(str(p.get("id") or ""))
        waiting_ages.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "days_since_activity": (now - last).days if last else None,
        })

    today = now.date()
    calendar = _calendar_items(state)
    overdue = sum(1 for x in calendar if x["_type"] == "deadline" and x["_date"].date() < today)
    upcoming_14 = sum(1 for x in calendar if 0 <= (x["_date"].date() - today).days <= 14)

    return {
        "analytics_version": "1.0",
        "generated_at": now.isoformat(),
        "projects": {
            "total": len(projects),
            "status": dict(status_counts),
            "active": len(active_projects),
            "next_action_coverage_pct": next_action_coverage,
        },
        "milestones": {
            "total": len(milestones),
            "completed": sum(1 for _, m in milestones if m.get("status") in {"completed", "done"}),
            "active": sum(1 for _, m in milestones if m.get("status") == "active"),
            "waiting": sum(1 for _, m in milestones if m.get("status") == "waiting"),
            "blocked": sum(1 for _, m in milestones if m.get("status") == "blocked"),
        },
        "movement": {
            "events_7_days": events_7,
            "events_30_days": events_30,
            "completion_events_30_days": completion_events_30,
        },
        "time": {
            "overdue_deadlines": overdue,
            "upcoming_14_days": upcoming_14,
        },
        "area_progress_pct": area_progress,
        "stale_active_projects": stale[:10],
        "waiting_age": waiting_ages,
        "notes": len(state.get("notes", [])),
        "resources": len(state.get("resources", [])),
    }


def _tokens(query: str) -> tuple[str, dict[str, str]]:
    filters: dict[str, str] = {}
    terms: list[str] = []
    for token in re.findall(r'"[^"]+"|\S+', query.strip()):
        token = token.strip('"')
        if ":" in token:
            key, value = token.split(":", 1)
            if key.casefold() in {"kind", "type", "status", "area", "project"} and value:
                filters[key.casefold()] = value.casefold()
                continue
        terms.append(token)
    return " ".join(terms).casefold(), filters


def unified_search(state: dict[str, Any], query: str, limit: int = 50) -> list[dict[str, Any]]:
    q, filters = _tokens(query)
    projects = _project_map(state)
    rows: list[dict[str, Any]] = []

    def add(kind: str, entity_id: str, title: Any, subtitle: Any = "", *, status: Any = "", area: Any = "", project_id: Any = "", payload: dict[str, Any] | None = None):
        title_s, sub_s = str(title or ""), str(subtitle or "")
        project_name = str(projects.get(str(project_id), {}).get("name") or "") if project_id else ""
        hay = " ".join([kind, entity_id, title_s, sub_s, str(status or ""), str(area or ""), project_name]).casefold()
        if q and not all(term in hay for term in q.split()):
            return
        if filters.get("kind") and filters["kind"] not in kind.casefold():
            return
        if filters.get("type") and filters["type"] not in kind.casefold():
            return
        if filters.get("status") and filters["status"] != str(status or "").casefold():
            return
        if filters.get("area") and filters["area"] not in str(area or "").casefold():
            return
        if filters.get("project") and filters["project"] not in (str(project_id) + " " + project_name).casefold():
            return
        score = 1
        if q:
            if q == title_s.casefold(): score += 10
            elif q in title_s.casefold(): score += 6
            elif q in sub_s.casefold(): score += 3
        rows.append({
            "kind": kind,
            "id": entity_id,
            "title": title_s,
            "subtitle": sub_s,
            "status": status or "",
            "area": area or "",
            "project_id": project_id or "",
            "score": score,
            **({"payload": payload} if payload else {}),
        })

    for p in state.get("projects", []):
        add("project", str(p.get("id") or ""), p.get("name"), p.get("next_action"), status=p.get("status"), area=p.get("category"), project_id=p.get("id"))
        for m in p.get("milestones", []):
            add("task", str(m.get("id") or ""), m.get("name"), p.get("name"), status=m.get("status"), area=p.get("category"), project_id=p.get("id"))
    for n in state.get("notes", []):
        add("note", str(n.get("id") or ""), n.get("title"), n.get("body") or n.get("text"), area=n.get("category"), project_id=n.get("project_id"))
    for r in state.get("resources", []):
        add("resource", str(r.get("id") or ""), r.get("title") or r.get("name"), r.get("description") or r.get("location"), area=r.get("type"), project_id=r.get("project_id"))
    for d in state.get("deadlines", []):
        add("deadline", str(d.get("id") or ""), d.get("title") or d.get("name"), f"{d.get('date') or d.get('due') or ''} {d.get('time') or ''}".strip(), area=d.get("category"), project_id=d.get("project_id"))
    for e in state.get("calendar_events", []):
        add("calendar", str(e.get("id") or ""), e.get("title") or e.get("name"), f"{e.get('date') or ''} {e.get('time') or ''} {e.get('kind') or ''}".strip(), area=e.get("category"), project_id=e.get("project_id"))
    for e in state.get("events", [])[:100]:
        add("history", str(e.get("id") or ""), e.get("summary"), e.get("at"), project_id=e.get("project_id"))

    rows.sort(key=lambda x: (-int(x.get("score", 0)), str(x.get("title") or "").casefold()))
    return rows[: max(1, min(200, int(limit)))]
