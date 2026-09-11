from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from . import server as base

_ORIGINAL_EXTENSION_ACTION = base._extension_action
_ALLOWED_CATEGORIES = {"科研", "PhD", "学校", "课程", "行政", "职业", "其他"}


async def _extension_action_v3(payload: dict[str, Any]) -> dict[str, Any]:
    """NextPlan Chrome bridge actions beyond the legacy MCP surface.

    Supports explicit project creation, category/area reassignment, compact
    project-state snapshot updates, and destructive project/task deletion while
    preserving legacy task/deadline actions from the base server.
    """
    action = str(payload.get("action", "")).strip()
    state = await base._state()

    if action == "create_project":
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("name is required")

        normalized = name.casefold()
        for project in state.get("projects", []):
            if str(project.get("name", "")).strip().casefold() == normalized:
                category = str(payload.get("category", "")).strip()
                if category and category in _ALLOWED_CATEGORIES and project.get("category") != category:
                    return await base._emit(
                        {
                            "type": "project_updated",
                            "project_id": project.get("id"),
                            "changes": {"category": category},
                            "summary": f"Updated project area: {project.get('name', name)} -> {category}",
                        },
                        via="nextplan-chrome-bridge",
                    )
                return {
                    "status": "already_exists",
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                }

        category = str(payload.get("category", "")).strip() or "其他"
        if category not in _ALLOWED_CATEGORIES:
            raise ValueError(f"Unsupported category: {category}")
        next_action = str(payload.get("next_action", "")).strip()
        try:
            priority = int(payload.get("priority", 2))
        except (TypeError, ValueError):
            priority = 2
        priority = max(1, min(3, priority))

        project_id = str(payload.get("project_id", "")).strip()
        if not project_id:
            project_id = f"project-{base._slug(name)}-{uuid.uuid4().hex[:6]}"

        project = {
            "id": project_id,
            "name": name,
            "category": category,
            "status": "active",
            "priority": priority,
            "next_action": next_action,
            "milestones": [],
        }
        return await base._emit(
            {
                "type": "project_created",
                "project_id": project_id,
                "project": project,
                "summary": f"Created project: {name}",
            },
            via="nextplan-chrome-bridge",
        )

    if action == "update_project_snapshot":
        project_id = str(payload.get("project_id", "")).strip()
        project = base._find_project(state, project_id)
        if not project:
            raise ValueError(f"Unknown project_id: {project_id}")

        changes: dict[str, Any] = {}

        category = str(payload.get("category", "")).strip()
        if category:
            if category not in _ALLOWED_CATEGORIES:
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

        milestone_statuses = payload.get("milestone_statuses") or {}
        if not isinstance(milestone_statuses, dict):
            raise ValueError("milestone_statuses must be an object")
        if milestone_statuses:
            milestones = deepcopy(project.get("milestones", []))
            by_id = {str(m.get("id")): m for m in milestones}
            changed = False
            for milestone_id, status in milestone_statuses.items():
                milestone_id = str(milestone_id).strip()
                if milestone_id not in by_id:
                    raise ValueError(f"Unknown milestone_id {milestone_id} in {project_id}")
                valid_status = base._validate_status(str(status))
                if by_id[milestone_id].get("status") != valid_status:
                    by_id[milestone_id]["status"] = valid_status
                    changed = True
            if changed:
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

    if action == "delete_project":
        project_id = str(payload.get("project_id", "")).strip()
        project = base._find_project(state, project_id)
        if not project:
            return {"status": "already_absent", "project_id": project_id}
        return await base._emit(
            {
                "type": "project_deleted",
                "project_id": project_id,
                "summary": f"Deleted project: {project.get('name', project_id)}",
            },
            via="nextplan-chrome-bridge",
        )

    if action == "delete_task":
        project_id = str(payload.get("project_id", "")).strip()
        task_id = str(payload.get("task_id", "")).strip()
        project = base._find_project(state, project_id)
        if not project:
            raise ValueError(f"Unknown project_id: {project_id}")
        task = base._find_milestone(project, task_id)
        if not task:
            return {"status": "already_absent", "project_id": project_id, "task_id": task_id}
        return await base._emit(
            {
                "type": "task_deleted",
                "project_id": project_id,
                "task_id": task_id,
                "summary": f"Deleted task: {task.get('name', task_id)}",
            },
            via="nextplan-chrome-bridge",
        )

    return await _ORIGINAL_EXTENSION_ACTION(payload)


base._extension_action = _extension_action_v3
app = base.app
mcp = base.mcp
