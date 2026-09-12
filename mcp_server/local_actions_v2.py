from __future__ import annotations

import re
import uuid
from typing import Any

from .local_actions_v1 import ALLOWED_CATEGORIES, ALLOWED_STATUS, execute_action as execute_action_v1
from .storage_v1 import CanonicalStore


def _slug(text: str, max_len: int = 32) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return value[:max_len] or "item"


def execute_action(store: CanonicalStore, action: dict[str, Any]) -> dict[str, Any]:
    """Stage V local action composition.

    Adds atomic project-blueprint creation while preserving the Stage 1-3 action
    implementation for every existing operation.
    """
    op = str(action.get("action") or "").strip()
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
        "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
