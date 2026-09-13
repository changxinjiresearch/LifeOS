from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .local_actions_v1 import ALLOWED_CATEGORIES, ALLOWED_STATUS, execute_action as execute_action_v1
from .storage_v1 import CanonicalStore


def _slug(text: str, max_len: int = 32) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return value[:max_len] or "item"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _execute_calendar_event(store: CanonicalStore, action: dict[str, Any]) -> dict[str, Any]:
    title = str(action.get("title") or "").strip()
    date = str(action.get("date") or "").strip()
    if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("calendar event requires title and date YYYY-MM-DD")
    event_id = str(action.get("calendar_event_id") or action.get("id") or "").strip()
    if not event_id:
        event_id = f"calendar-{_slug(title)}-{date}-{uuid.uuid4().hex[:6]}"
    calendar_event: dict[str, Any] = {
        "id": event_id,
        "title": title,
        "date": date,
        "kind": str(action.get("kind") or "event").strip() or "event",
    }
    for key in ("time", "timezone", "category", "project_id", "notes"):
        value = action.get(key)
        if value not in (None, ""):
            calendar_event[key] = value
    event = {
        "id": f"evt-local-calendar-{uuid.uuid4().hex}",
        "at": _now_iso(),
        "type": "calendar_event_upserted",
        "project_id": str(action.get("project_id") or "calendar"),
        "calendar_event": calendar_event,
        "summary": f"Calendar event: {title} · {date}" + (f" {calendar_event['time']}" if calendar_event.get("time") else ""),
        "source": {"kind": "conversation", "via": "nextplan-local-core-v2"},
    }
    result = store.append_event(event)
    return {
        "status": result["status"],
        "event_id": result["event_id"],
        "calendar_event_id": event_id,
        "title": title,
        "date": date,
        "summary": event["summary"],
    }


def execute_action(store: CanonicalStore, action: dict[str, Any]) -> dict[str, Any]:
    """Stage V local action composition.

    Adds atomic project-blueprint creation and calendar event persistence while
    preserving the Stage 1-3 action implementation for every existing operation.
    """
    op = str(action.get("action") or "").strip()
    if op == "upsert_calendar_event":
        return _execute_calendar_event(store, action)
    if op != "create_project_blueprint":
        return execute_action_v1(store, action)

    name = str(action.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    state = store.get_state()
    existing = next((p for p in state.get("projects", []) if str(p.get("name", "")).strip().casefold() == name.casefold()), None)
    if existing:
        return {"status": "already_exists", "project_id": existing.get("id"), "project_name": existing.get("name")}

    category = str(action.get("category") or "其他").strip() or "其他"
    if category not in ALLOWED_CATEGORIES:
        category = "其他"
    project_id = str(action.get("project_id") or "").strip() or f"project-{_slug(name)}-{uuid.uuid4().hex[:6]}"
    raw_milestones = action.get("milestones") or []
    if not isinstance(raw_milestones, list):
        raise ValueError("milestones must be a list")

    milestones: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_milestones[:20]):
        if not isinstance(raw, dict):
            continue
        step_name = str(raw.get("name") or "").strip()
        if not step_name:
            continue
        status = str(raw.get("status") or ("active" if index == 0 else "planned")).strip()
        if status not in ALLOWED_STATUS:
            status = "planned"
        milestones.append({
            "id": str(raw.get("id") or "").strip() or f"task-{_slug(step_name)}-{uuid.uuid4().hex[:6]}",
            "name": step_name,
            "status": status,
        })

    next_action = str(action.get("next_action") or "").strip()
    if not next_action and milestones:
        active = next((m for m in milestones if m["status"] == "active"), milestones[0])
        next_action = active["name"]
    project = {
        "id": project_id,
        "name": name,
        "category": category,
        "status": "active",
        "priority": max(1, min(3, int(action.get("priority") or 2))),
        "next_action": next_action,
        "milestones": milestones,
    }
    event = {
        "id": f"evt-local-blueprint-{uuid.uuid4().hex}",
        "at": _now_iso(),
        "type": "project_created",
        "project_id": project_id,
        "project": project,
        "summary": f"Created project blueprint: {name}",
        "source": {
            "kind": "conversation" if action.get("evidence_text") else "local",
            "via": "nextplan-local-core-v2",
            **({"authority": "user_assertion", "evidence_text": str(action.get("evidence_text"))[:500]} if action.get("evidence_text") else {}),
        },
    }
    result = store.append_event(event)
    return {
        "status": result["status"],
        "event_id": result["event_id"],
        "project_id": project_id,
        "project_name": name,
        "milestone_count": len(milestones),
        "summary": event["summary"],
    }
