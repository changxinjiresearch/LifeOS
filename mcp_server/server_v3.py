from __future__ import annotations

import uuid
from typing import Any

from . import server as base

_ORIGINAL_EXTENSION_ACTION = base._extension_action


async def _extension_action_v3(payload: dict[str, Any]) -> dict[str, Any]:
    """NextPlan Chrome bridge v0.3 actions.

    Adds explicit project creation plus destructive project/task deletion while
    preserving all v0.2 actions implemented by the base server.
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
                return {
                    "status": "already_exists",
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                }

        category = str(payload.get("category", "")).strip() or "其他"
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


# NextPlanAuthMiddleware resolves this function from the base module at request
# time, so replacing it here upgrades /extension/action without duplicating the
# entire MCP server implementation.
base._extension_action = _extension_action_v3
app = base.app
mcp = base.mcp
