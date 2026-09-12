from __future__ import annotations

import secrets
from typing import Any

import httpx

from . import server_v4 as v4
from .cloud_classifier import classify_turn

base = v4.base
_PREVIOUS_EXTENSION_ACTION = base._extension_action


async def _extension_action_v5(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    if action != "upsert_calendar_event":
        return await _PREVIOUS_EXTENSION_ACTION(payload)

    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError("title is required")

    date = base._validate_date(str(payload.get("date", "")))
    time_value = str(payload.get("time", "")).strip()
    timezone_name = str(payload.get("timezone", "")).strip()
    category = str(payload.get("category", "")).strip()
    kind = str(payload.get("kind", "")).strip() or "event"
    project_id = str(payload.get("project_id", "")).strip()

    if project_id:
        state = await base._state()
        if not base._find_project(state, project_id):
            raise ValueError(f"Unknown project_id: {project_id}")

    key_time = time_value.replace(":", "") if time_value else "allday"
    did = str(payload.get("deadline_id", "")).strip() or f"calendar-{base._slug(title)}-{date}-{key_time}"
    deadline: dict[str, Any] = {
        "id": did,
        "title": title,
        "date": date,
        "kind": kind,
    }
    if project_id:
        deadline["project_id"] = project_id
    if time_value:
        deadline["time"] = time_value
    if timezone_name:
        deadline["timezone"] = timezone_name
    if category:
        deadline["category"] = category

    return await base._emit(
        {
            "type": "deadline_set",
            "project_id": project_id or "calendar",
            "deadline": deadline,
            "summary": f"Calendar: {title} on {date}" + (f" {time_value}" if time_value else ""),
        },
        via="nextplan-cloud-classifier",
    )


base._extension_action = _extension_action_v5
_legacy_app = v4.app


async def app(scope, receive, send):
    if scope.get("type") == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()

        if path == "/extension/classify" and method == "POST":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            auth = headers.get("authorization", "")

            if not base.EXTENSION_TOKEN:
                return await base._send_json(send, 503, {"error": "extension_auth_not_configured"})
            if not secrets.compare_digest(auth, f"Bearer {base.EXTENSION_TOKEN}"):
                return await base._send_json(send, 401, {"error": "unauthorized"})

            try:
                payload = await base._read_json_body(receive)
                turn = payload.get("turn") or {}
                client = payload.get("client") or {}
                if not isinstance(turn, dict):
                    raise ValueError("turn must be an object")
                if not isinstance(client, dict):
                    raise ValueError("client must be an object")
                state = await base._state()
                candidate = classify_turn(turn, state, client)
                return await base._send_json(send, 200, {
                    "status": "ok",
                    "classifier": "cloud-v1",
                    "candidate": candidate,
                })
            except ValueError as exc:
                return await base._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
            except httpx.HTTPStatusError as exc:
                return await base._send_json(send, 502, {"error": "github_error", "detail": str(exc.response.status_code)})
            except Exception as exc:
                return await base._send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})

    return await _legacy_app(scope, receive, send)


mcp = base.mcp
