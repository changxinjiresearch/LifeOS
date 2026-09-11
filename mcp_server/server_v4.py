from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from . import server_v3 as v3

base = v3.base
_PREVIOUS_EXTENSION_ACTION = base._extension_action


async def _extension_action_v4(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    if action != "update_project_snapshot":
        return await _PREVIOUS_EXTENSION_ACTION(payload)

    state = await base._state()
    project_id = str(payload.get("project_id", "")).strip()
    project = base._find_project(state, project_id)
    if not project:
        raise ValueError(f"Unknown project_id: {project_id}")

    changes: dict[str, Any] = {}

    new_name = str(payload.get("name", "")).strip()
    if new_name and new_name != str(project.get("name", "")).strip():
        normalized = new_name.casefold()
        for other in state.get("projects", []):
            if other.get("id") != project_id and str(other.get("name", "")).strip().casefold() == normalized:
                raise ValueError(f"Project name already exists: {new_name}")
        changes["name"] = new_name

    category = str(payload.get("category", "")).strip()
    if category:
        if category not in v3._ALLOWED_CATEGORIES:
            raise ValueError(f"Unsupported category: {category}")
        if project.get("category") != category:
            changes["category"] = category

    next_action = str(payload.get("next_action", "")).strip()
    if next_action and next_action != str(project.get("next_action", "")).strip():
        changes["next_action"] = next_action

    project_status = str(payload.get("status", "")).strip()
    if project_status:
        project_status = base._validate_status(project_status)
        if project.get("status") != project_status:
            changes["status"] = project_status

    milestones = deepcopy(project.get("milestones", []))
    milestones_changed = False

    current_step = str(payload.get("current_step", "")).strip()
    if current_step:
        normalized_step = current_step.casefold()
        step = next(
            (m for m in milestones if str(m.get("name", "")).strip().casefold() == normalized_step),
            None,
        )
        if step is None:
            step = {
                "id": f"step-{base._slug(current_step)}-{uuid.uuid4().hex[:6]}",
                "name": current_step,
                "status": "active",
            }
            milestones.append(step)
            milestones_changed = True
        elif step.get("status") != "active":
            step["status"] = "active"
            milestones_changed = True

    milestone_statuses = payload.get("milestone_statuses") or {}
    if not isinstance(milestone_statuses, dict):
        raise ValueError("milestone_statuses must be an object")
    if milestone_statuses:
        by_id = {str(m.get("id")): m for m in milestones}
        for milestone_id, status in milestone_statuses.items():
            milestone_id = str(milestone_id).strip()
            if milestone_id not in by_id:
                raise ValueError(f"Unknown milestone_id {milestone_id} in {project_id}")
            valid_status = base._validate_status(str(status))
            if by_id[milestone_id].get("status") != valid_status:
                by_id[milestone_id]["status"] = valid_status
                milestones_changed = True

    if milestones_changed:
        changes["milestones"] = milestones

    if not changes:
        return {"status": "no_change", "project_id": project_id}

    return await base._emit(
        {
            "type": "project_updated",
            "project_id": project_id,
            "changes": changes,
            "summary": f"Updated project snapshot: {project.get('name', project_id)}",
        },
        via="nextplan-chrome-bridge",
    )


base._extension_action = _extension_action_v4
app = base.app
mcp = base.mcp
