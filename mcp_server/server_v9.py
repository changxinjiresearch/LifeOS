from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from . import server_v8 as v8
from . import server_v6 as v6
from .cloud_classifier_v4 import classify_turn as classify_turn_v4
from .phase_c_engine import analytics_snapshot, unified_search, weekly_review

base = v8.base
_LEGACY_EXECUTE = v8._phase_b_action
_LEGACY_APP = v8.app


def _target_from_action_v9(action: dict[str, Any] | None) -> dict[str, Any]:
    action = action or {}
    op = str(action.get("action", "")).strip()
    if op in {"add_note", "update_note", "remove_note"}:
        entity_id = action.get("note_id")
        return {"entity_type": "note", **({"entity_id": str(entity_id)} if entity_id else {})}
    if op in {"add_resource", "update_resource", "remove_resource"}:
        entity_id = action.get("resource_id")
        return {"entity_type": "resource", **({"entity_id": str(entity_id)} if entity_id else {})}
    return v6._target_from_action(action)


async def _phase_c_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "add_note":
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not title or not body:
            raise ValueError("title and body are required")
        project_id = str(payload.get("project_id", "")).strip()
        if project_id:
            state = await base._state()
            if not base._find_project(state, project_id):
                raise ValueError(f"Unknown project_id: {project_id}")
        nid = str(payload.get("note_id", "")).strip() or f"note-{base._slug(title)}-{uuid.uuid4().hex[:6]}"
        note: dict[str, Any] = {
            "id": nid,
            "title": title,
            "body": body,
            "category": str(payload.get("category", "Note")).strip() or "Note",
        }
        if project_id:
            note["project_id"] = project_id
        tags = payload.get("tags")
        if isinstance(tags, list):
            note["tags"] = [str(x).strip() for x in tags if str(x).strip()][:20]
        event = {"type": "note_added", "project_id": project_id or "notes", "note": note, "summary": f"Added note: {title}"}
        result = await base._emit(event, via="nextplan-phase-c")
        return {**result, "note_id": nid, "summary": event["summary"]}

    if action == "update_note":
        nid = str(payload.get("note_id", "")).strip()
        if not nid:
            raise ValueError("note_id is required")
        state = await base._state()
        current = next((n for n in state.get("notes", []) if str(n.get("id")) == nid), None)
        if not current:
            raise ValueError(f"Unknown note_id: {nid}")
        changes: dict[str, Any] = {}
        for key in ("title", "body", "category", "project_id"):
            if key in payload and str(payload.get(key, "")).strip():
                changes[key] = str(payload.get(key)).strip()
        if isinstance(payload.get("tags"), list):
            changes["tags"] = [str(x).strip() for x in payload["tags"] if str(x).strip()][:20]
        if not changes:
            return {"status": "no_change", "note_id": nid, "summary": "No note changes supplied"}
        event = {"type": "note_updated", "note_id": nid, "changes": changes, "project_id": changes.get("project_id") or current.get("project_id") or "notes", "summary": f"Updated note: {current.get('title', nid)}"}
        result = await base._emit(event, via="nextplan-phase-c")
        return {**result, "note_id": nid, "summary": event["summary"]}

    if action == "remove_note":
        nid = str(payload.get("note_id", "")).strip()
        if not nid:
            raise ValueError("note_id is required")
        state = await base._state()
        current = next((n for n in state.get("notes", []) if str(n.get("id")) == nid), None)
        if not current:
            return {"status": "already_absent", "note_id": nid, "summary": "Note already absent"}
        event = {"type": "note_removed", "note_id": nid, "project_id": current.get("project_id") or "notes", "summary": f"Removed note: {current.get('title', nid)}"}
        result = await base._emit(event, via="nextplan-phase-c")
        return {**result, "note_id": nid, "summary": event["summary"]}

    if action == "add_resource":
        title = str(payload.get("title", "")).strip()
        location = str(payload.get("location", "")).strip()
        if not title or not location:
            raise ValueError("title and location are required")
        project_id = str(payload.get("project_id", "")).strip()
        if project_id:
            state = await base._state()
            if not base._find_project(state, project_id):
                raise ValueError(f"Unknown project_id: {project_id}")
        rid = str(payload.get("resource_id", "")).strip() or f"resource-{base._slug(title)}-{uuid.uuid4().hex[:6]}"
        resource: dict[str, Any] = {
            "id": rid,
            "title": title,
            "location": location,
            "type": str(payload.get("resource_type", "link")).strip() or "link",
        }
        if str(payload.get("description", "")).strip():
            resource["description"] = str(payload.get("description")).strip()
        if project_id:
            resource["project_id"] = project_id
        tags = payload.get("tags")
        if isinstance(tags, list):
            resource["tags"] = [str(x).strip() for x in tags if str(x).strip()][:20]
        event = {"type": "resource_added", "project_id": project_id or "resources", "resource": resource, "summary": f"Added resource: {title}"}
        result = await base._emit(event, via="nextplan-phase-c")
        return {**result, "resource_id": rid, "summary": event["summary"]}

    if action == "update_resource":
        rid = str(payload.get("resource_id", "")).strip()
        if not rid:
            raise ValueError("resource_id is required")
        state = await base._state()
        current = next((r for r in state.get("resources", []) if str(r.get("id")) == rid), None)
        if not current:
            raise ValueError(f"Unknown resource_id: {rid}")
        changes: dict[str, Any] = {}
        for key in ("title", "location", "description", "project_id"):
            if key in payload and str(payload.get(key, "")).strip():
                changes[key] = str(payload.get(key)).strip()
        if str(payload.get("resource_type", "")).strip():
            changes["type"] = str(payload.get("resource_type")).strip()
        if isinstance(payload.get("tags"), list):
            changes["tags"] = [str(x).strip() for x in payload["tags"] if str(x).strip()][:20]
        if not changes:
            return {"status": "no_change", "resource_id": rid, "summary": "No resource changes supplied"}
        event = {"type": "resource_updated", "resource_id": rid, "changes": changes, "project_id": changes.get("project_id") or current.get("project_id") or "resources", "summary": f"Updated resource: {current.get('title', rid)}"}
        result = await base._emit(event, via="nextplan-phase-c")
        return {**result, "resource_id": rid, "summary": event["summary"]}

    if action == "remove_resource":
        rid = str(payload.get("resource_id", "")).strip()
        if not rid:
            raise ValueError("resource_id is required")
        state = await base._state()
        current = next((r for r in state.get("resources", []) if str(r.get("id")) == rid), None)
        if not current:
            return {"status": "already_absent", "resource_id": rid, "summary": "Resource already absent"}
        event = {"type": "resource_removed", "resource_id": rid, "project_id": current.get("project_id") or "resources", "summary": f"Removed resource: {current.get('title', rid)}"}
        result = await base._emit(event, via="nextplan-phase-c")
        return {**result, "resource_id": rid, "summary": event["summary"]}

    return await _LEGACY_EXECUTE(payload)


v6._EXECUTE_ACTION = _phase_c_action
v6.classify_turn = classify_turn_v4
v6._target_from_action = _target_from_action_v9


def _parse_now(client: dict[str, Any]) -> datetime | None:
    raw = str(client.get("now") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def app(scope, receive, send):
    if scope.get("type") == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if path in {"/extension/weekly-review", "/extension/search", "/extension/analytics"} and method == "POST":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if not base.EXTENSION_TOKEN:
                return await base._send_json(send, 503, {"error": "extension_auth_not_configured"})
            if not v6._authorized(headers):
                return await base._send_json(send, 401, {"error": "unauthorized"})
            try:
                payload = await base._read_json_body(receive)
                state = await base._state()
                client = payload.get("client") or {}
                now = _parse_now(client)
                if path == "/extension/weekly-review":
                    return await base._send_json(send, 200, {"status": "ok", "weekly_review": weekly_review(state, now)})
                if path == "/extension/analytics":
                    return await base._send_json(send, 200, {"status": "ok", "analytics": analytics_snapshot(state, now)})
                query = str(payload.get("query") or "")
                limit = int(payload.get("limit") or 50)
                return await base._send_json(send, 200, {"status": "ok", "query": query, "results": unified_search(state, query, limit)})
            except ValueError as exc:
                return await base._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
            except Exception as exc:
                return await base._send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})
    return await _LEGACY_APP(scope, receive, send)


mcp = base.mcp
