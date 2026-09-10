from __future__ import annotations

import secrets
from typing import Any

from . import server as legacy


async def _handle_delete_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    state = await legacy._state()

    if action == "delete_project":
        project_id = str(payload.get("project_id", "")).strip()
        project = legacy._find_project(state, project_id)
        if not project:
            raise ValueError(f"Unknown project_id: {project_id}")
        return await legacy._emit({
            "type": "project_deleted",
            "project_id": project_id,
            "summary": f"Deleted project: {project.get('name', project_id)}",
        }, via="nextplan-chrome-bridge")

    if action == "delete_task":
        project_id = str(payload.get("project_id", "")).strip()
        task_id = str(payload.get("task_id", "")).strip()
        project = legacy._find_project(state, project_id)
        if not project:
            raise ValueError(f"Unknown project_id: {project_id}")
        task = legacy._find_milestone(project, task_id)
        if not task:
            raise ValueError(f"Unknown task_id {task_id} in {project_id}")
        return await legacy._emit({
            "type": "task_deleted",
            "project_id": project_id,
            "task_id": task_id,
            "summary": f"Deleted task: {task.get('name', task_id)}",
        }, via="nextplan-chrome-bridge")

    raise ValueError(f"Unsupported delete action: {action}")


class NextPlanV2Wrapper:
    """Adds destructive Chrome-bridge actions while preserving the existing MCP app.

    Delete actions are intentionally accepted only through the authenticated
    extension endpoint. The browser classifier marks them as confirmation-only,
    so they can never be auto-synced by confidence threshold alone.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if path != "/extension/action" or method != "POST":
            return await self.app(scope, receive, send)

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not legacy.EXTENSION_TOKEN:
            return await legacy._send_json(send, 503, {"error": "extension_auth_not_configured"})
        if not secrets.compare_digest(auth, f"Bearer {legacy.EXTENSION_TOKEN}"):
            return await legacy._send_json(send, 401, {"error": "unauthorized"})

        try:
            payload = await legacy._read_json_body(receive)
            action = str(payload.get("action", "")).strip()
            if action in {"delete_project", "delete_task"}:
                result = await _handle_delete_action(payload)
            else:
                result = await legacy._extension_action(payload)
            return await legacy._send_json(send, 200, result)
        except ValueError as exc:
            return await legacy._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
        except Exception:
            return await legacy._send_json(send, 500, {"error": "internal_error"})


app = NextPlanV2Wrapper(legacy.app)
