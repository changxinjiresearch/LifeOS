from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .storage_v1 import CanonicalStore

ALLOWED_STATUS = {"active", "waiting", "planned", "completed", "done", "blocked"}
ALLOWED_CATEGORIES = {"科研", "PhD", "学校", "课程", "行政", "职业", "其他"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(text: str, max_len: int = 32) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return (value[:max_len] or "item")


def _event_id(kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"evt-{stamp}-{_slug(kind, 18)}-{uuid.uuid4().hex[:8]}"


def _event(kind: str, summary: str, **payload: Any) -> dict[str, Any]:
    return {
        "id": _event_id(kind),
        "at": _now_iso(),
        "type": kind,
        "summary": summary,
        "source": {"kind": "local", "via": "nextplan-local-core-v1"},
        **payload,
    }


def _project(state: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    return next((p for p in state.get("projects", []) if str(p.get("id")) == project_id), None)


def _milestone(project: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    return next((m for m in project.get("milestones", []) if str(m.get("id")) == task_id), None)


def _validate_status(value: str) -> str:
    value = value.strip()
    if value not in ALLOWED_STATUS:
        raise ValueError(f"invalid status: {value}")
    return value


def _apply(store: CanonicalStore, event: dict[str, Any]) -> dict[str, Any]:
    result = store.append_event(event)
    return {
        "status": result["status"],
        "event_id": result["event_id"],
        "summary": event["summary"],
    }


def execute_action(store: CanonicalStore, action: dict[str, Any]) -> dict[str, Any]:
    op = str(action.get("action") or "").strip()
    if not op:
        raise ValueError("action is required")
    state = store.get_state()

    if op == "create_project":
        name = str(action.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        existing = next((p for p in state.get("projects", []) if str(p.get("name", "")).strip().casefold() == name.casefold()), None)
        if existing:
            return {"status": "already_exists", "project_id": existing.get("id"), "project_name": existing.get("name")}
        category = str(action.get("category") or "其他").strip() or "其他"
        if category not in ALLOWED_CATEGORIES:
            category = "其他"
        pid = str(action.get("project_id") or "").strip() or f"project-{_slug(name)}-{uuid.uuid4().hex[:6]}"
        priority = max(1, min(3, int(action.get("priority") or 2)))
        project = {
            "id": pid,
            "name": name,
            "category": category,
            "status": "active",
            "priority": priority,
            "next_action": str(action.get("next_action") or "").strip(),
            "milestones": [],
        }
        result = _apply(store, _event("project_created", f"Created project: {name}", project_id=pid, project=project))
        return {**result, "project_id": pid, "project_name": name}

    if op in {"update_project", "update_project_snapshot"}:
        pid = str(action.get("project_id") or "").strip()
        project = _project(state, pid)
        if not project:
            raise ValueError(f"Unknown project_id: {pid}")
        changes: dict[str, Any] = {}
        for key in ("name", "next_action"):
            value = str(action.get(key) or "").strip()
            if value and value != str(project.get(key) or ""):
                changes[key] = value
        status = str(action.get("status") or "").strip()
        if status and status != str(project.get("status") or ""):
            changes["status"] = _validate_status(status)
        category = str(action.get("category") or "").strip()
        if category and category in ALLOWED_CATEGORIES and category != project.get("category"):
            changes["category"] = category
        if action.get("priority") not in (None, "", 0):
            priority = max(1, min(3, int(action["priority"])))
            if priority != project.get("priority"):
                changes["priority"] = priority
        if not changes:
            return {"status": "no_change", "project_id": pid}
        result = _apply(store, _event("project_updated", f"Updated project: {project.get('name', pid)}", project_id=pid, changes=changes))
        return {**result, "project_id": pid}

    if op == "delete_project":
        pid = str(action.get("project_id") or "").strip()
        project = _project(state, pid)
        if not project:
            return {"status": "already_absent", "project_id": pid}
        result = _apply(store, _event("project_deleted", f"Deleted project: {project.get('name', pid)}", project_id=pid))
        return {**result, "project_id": pid}

    if op == "create_task":
        pid = str(action.get("project_id") or "").strip()
        project = _project(state, pid)
        if not project:
            raise ValueError(f"Unknown project_id: {pid}")
        name = str(action.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        existing = next((m for m in project.get("milestones", []) if str(m.get("name", "")).strip().casefold() == name.casefold()), None)
        if existing:
            return {"status": "already_exists", "project_id": pid, "task_id": existing.get("id")}
        tid = str(action.get("task_id") or action.get("milestone_id") or "").strip() or f"task-{_slug(name)}-{uuid.uuid4().hex[:6]}"
        task = {"id": tid, "name": name, "status": str(action.get("status") or "active")}
        if task["status"] not in ALLOWED_STATUS:
            task["status"] = "active"
        payload: dict[str, Any] = {"project_id": pid, "task": task}
        next_action = str(action.get("next_action") or "").strip()
        if next_action:
            payload["next_action"] = next_action
        result = _apply(store, _event("task_created", f"Created task: {name}", **payload))
        return {**result, "project_id": pid, "task_id": tid}

    if op in {"update_milestone", "complete_task"}:
        pid = str(action.get("project_id") or "").strip()
        tid = str(action.get("task_id") or action.get("milestone_id") or "").strip()
        project = _project(state, pid)
        if not project:
            raise ValueError(f"Unknown project_id: {pid}")
        task = _milestone(project, tid)
        if not task:
            raise ValueError(f"Unknown task_id {tid} in {pid}")
        status = "completed" if op == "complete_task" else _validate_status(str(action.get("status") or ""))
        if str(task.get("status")) == status:
            return {"status": "no_change", "project_id": pid, "task_id": tid}
        kind = "task_completed" if op == "complete_task" else "milestone_status_changed"
        payload: dict[str, Any] = {"project_id": pid, ("task_id" if kind == "task_completed" else "milestone_id"): tid}
        if kind != "task_completed":
            payload["status"] = status
        for key in ("next_action", "project_status", "name"):
            value = str(action.get(key) or "").strip()
            if value:
                payload[key] = value
        result = _apply(store, _event(kind, f"Milestone {tid} -> {status}", **payload))
        return {**result, "project_id": pid, "task_id": tid}

    if op == "delete_task":
        pid = str(action.get("project_id") or "").strip()
        tid = str(action.get("task_id") or "").strip()
        project = _project(state, pid)
        if not project:
            raise ValueError(f"Unknown project_id: {pid}")
        if not _milestone(project, tid):
            return {"status": "already_absent", "project_id": pid, "task_id": tid}
        result = _apply(store, _event("task_deleted", f"Deleted task: {tid}", project_id=pid, task_id=tid))
        return {**result, "project_id": pid, "task_id": tid}

    if op == "set_deadline":
        pid = str(action.get("project_id") or "").strip()
        title = str(action.get("title") or "").strip()
        date = str(action.get("date") or "").strip()
        if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("deadline requires title and date YYYY-MM-DD")
        did = str(action.get("deadline_id") or "").strip() or f"deadline-{_slug(title)}-{date}"
        deadline = {"id": did, "project_id": pid, "title": title, "date": date}
        result = _apply(store, _event("deadline_set", f"Set deadline: {title} on {date}", project_id=pid or "calendar", deadline=deadline))
        return {**result, "deadline_id": did}

    raise ValueError(f"unsupported local action: {op}")
