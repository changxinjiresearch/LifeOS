from __future__ import annotations

from datetime import datetime
from typing import Any

from . import server_v7 as v7
from . import server_v6 as v6
from . import server_v5 as v5
from .cloud_classifier_v3 import classify_turn as classify_turn_v3
from .decision_engine import recommend

base = v6.base
_LEGACY_EXECUTE = v5._extension_action_v5


async def _phase_b_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "complete_task":
        project_id = str(payload.get("project_id", "")).strip()
        task_id = str(payload.get("task_id", "")).strip()
        state = await base._state()
        project = base._find_project(state, project_id)
        if not project:
            raise ValueError(f"Unknown project_id: {project_id}")
        task = base._find_milestone(project, task_id)
        if not task:
            raise ValueError(f"Unknown task_id {task_id} in {project_id}")
        if task.get("status") == "completed":
            return {"status": "no_change", "project_id": project_id, "task_id": task_id, "summary": f"Already completed: {task.get('name', task_id)}"}
        event: dict[str, Any] = {
            "type": "task_completed",
            "project_id": project_id,
            "task_id": task_id,
            "auto_advance": bool(payload.get("auto_advance", True)),
            "summary": f"Completed task: {task.get('name', task_id)}",
        }
        if str(payload.get("next_action", "")).strip():
            event["next_action"] = str(payload.get("next_action")).strip()
        result = await base._emit(event, via="nextplan-phase-b")
        return {**result, "project_id": project_id, "task_id": task_id, "summary": event["summary"]}

    if action == "update_milestone" and str(payload.get("status", "")).strip() == "completed":
        project_id = str(payload.get("project_id", "")).strip()
        milestone_id = str(payload.get("milestone_id", "")).strip()
        state = await base._state()
        project = base._find_project(state, project_id)
        if not project or not base._find_milestone(project, milestone_id):
            raise ValueError("Unknown project_id or milestone_id")
        event: dict[str, Any] = {
            "type": "milestone_status_changed",
            "project_id": project_id,
            "milestone_id": milestone_id,
            "status": "completed",
            "auto_advance": bool(payload.get("auto_advance", True)),
            "summary": f"Milestone {milestone_id} -> completed",
        }
        result = await base._emit(event, via="nextplan-phase-b")
        return {**result, "project_id": project_id, "task_id": milestone_id, "summary": event["summary"]}

    if action == "set_deadline":
        project_id = str(payload.get("project_id", "")).strip()
        if project_id:
            state = await base._state()
            if not base._find_project(state, project_id):
                raise ValueError(f"Unknown project_id: {project_id}")
        title = str(payload.get("title", "")).strip()
        if not title:
            raise ValueError("title is required")
        date = base._validate_date(str(payload.get("date", "")))
        did = str(payload.get("deadline_id", "")).strip() or f"deadline-{base._slug(title)}-{date}"
        deadline: dict[str, Any] = {"id": did, "title": title, "date": date}
        for key in ("project_id", "task_id", "category", "time", "timezone", "prep_days"):
            value = payload.get(key)
            if value not in (None, ""):
                deadline[key] = value
        event = {
            "type": "deadline_set",
            "project_id": project_id or "calendar",
            "deadline": deadline,
            "summary": f"Set deadline: {title} on {date}" + (f" {deadline.get('time')}" if deadline.get("time") else ""),
        }
        result = await base._emit(event, via="nextplan-phase-b")
        return {**result, "deadline_id": did, "summary": event["summary"]}

    if action == "upsert_calendar_event":
        title = str(payload.get("title", "")).strip()
        if not title:
            raise ValueError("title is required")
        date = base._validate_date(str(payload.get("date", "")))
        kind = str(payload.get("kind", "")).strip() or "event"
        if kind not in {"event", "meeting", "appointment", "presentation", "reminder"}:
            raise ValueError("invalid calendar event kind")
        project_id = str(payload.get("project_id", "")).strip()
        if project_id:
            state = await base._state()
            if not base._find_project(state, project_id):
                raise ValueError(f"Unknown project_id: {project_id}")
        time_value = str(payload.get("time", "")).strip()
        key_time = time_value.replace(":", "") if time_value else "allday"
        cid = str(payload.get("calendar_event_id", "")).strip() or f"calendar-{base._slug(title)}-{date}-{key_time}"
        item: dict[str, Any] = {"id": cid, "title": title, "date": date, "kind": kind}
        for key in ("time", "end_time", "timezone", "project_id", "task_id", "category", "location", "notes", "prep_days"):
            value = payload.get(key)
            if value not in (None, ""):
                item[key] = value
        event = {
            "type": "calendar_event_upserted",
            "project_id": project_id or "calendar",
            "calendar_event": item,
            "summary": f"Calendar: {title} on {date}" + (f" {time_value}" if time_value else ""),
        }
        result = await base._emit(event, via="nextplan-phase-b")
        return {**result, "calendar_event_id": cid, "summary": event["summary"]}

    if action == "remove_calendar_event":
        cid = str(payload.get("calendar_event_id", "")).strip()
        if not cid:
            raise ValueError("calendar_event_id is required")
        state = await base._state()
        if not any(str(x.get("id")) == cid for x in state.get("calendar_events", [])):
            return {"status": "already_absent", "calendar_event_id": cid, "summary": "Calendar event already absent"}
        event = {"type": "calendar_event_removed", "calendar_event_id": cid, "summary": f"Removed calendar event: {cid}"}
        result = await base._emit(event, via="nextplan-phase-b")
        return {**result, "calendar_event_id": cid, "summary": event["summary"]}

    return await _LEGACY_EXECUTE(payload)


# server_v6 resolves these globals at request time. This upgrades the cloud layer
# without changing the installed Thin Bridge.
v6._EXECUTE_ACTION = _phase_b_action
v6.classify_turn = classify_turn_v3
_PHASE_A_APP = v6.app


def _parse_now(client: dict[str, Any]) -> datetime | None:
    raw = str(client.get("now") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def app(scope, receive, send):
    if scope.get("type") == "http" and scope.get("path") == "/extension/recommend" and scope.get("method", "GET").upper() == "POST":
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        if not base.EXTENSION_TOKEN:
            return await base._send_json(send, 503, {"error": "extension_auth_not_configured"})
        if not v6._authorized(headers):
            return await base._send_json(send, 401, {"error": "unauthorized"})
        try:
            payload = await base._read_json_body(receive)
            client = payload.get("client") or {}
            exclude_key = str(payload.get("exclude_key") or "").strip() or None
            state = await base._state()
            recommendation = recommend(state, _parse_now(client), exclude_key=exclude_key)
            return await base._send_json(send, 200, {
                "status": "ok",
                "decision_engine": "v1.0",
                "recommendation": recommendation,
            })
        except ValueError as exc:
            return await base._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
        except Exception as exc:
            return await base._send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})
    return await _PHASE_A_APP(scope, receive, send)


mcp = base.mcp
