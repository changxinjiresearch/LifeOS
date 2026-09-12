from __future__ import annotations

import secrets
from typing import Any

import httpx

from . import server_v5 as v5
from .cloud_classifier import classify_turn

base = v5.base
_EXECUTE_ACTION = v5._extension_action_v5
_LEGACY_APP = v5.app


def _target_from_action(action: dict[str, Any] | None) -> dict[str, Any]:
    action = action or {}
    op = str(action.get("action", "")).strip()
    if op in {"create_project", "update_project_snapshot", "update_project", "delete_project"}:
        return {"entity_type": "project", **({"entity_id": str(action.get("project_id"))} if action.get("project_id") else {})}
    if op in {"create_task", "update_milestone", "complete_task", "delete_task"}:
        entity_id = action.get("task_id") or action.get("milestone_id")
        return {"entity_type": "task", **({"entity_id": str(entity_id)} if entity_id else {})}
    if op == "set_deadline":
        return {"entity_type": "deadline", **({"entity_id": str(action.get("deadline_id"))} if action.get("deadline_id") else {})}
    if op == "upsert_calendar_event":
        return {"entity_type": "calendar_event", **({"entity_id": str(action.get("calendar_event_id"))} if action.get("calendar_event_id") else {})}
    return {"entity_type": "unknown"}


def _normalize_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    c = dict(candidate)
    candidate_id = str(c.get("id", "")).strip()
    action = c.get("action")
    if isinstance(action, dict):
        action = dict(action)
        if candidate_id:
            action.setdefault("operation_id", candidate_id)
        c["action"] = action

    destructive = bool(c.get("destructive"))
    required = bool(c.get("requiresConfirmation")) or destructive
    c["protocol_version"] = "1.0"
    c.setdefault("intent", str(c.get("kind") or (action or {}).get("action") or "informational"))
    c.setdefault("target", _target_from_action(action if isinstance(action, dict) else None))
    c["confirmation"] = {
        "required": required,
        "destructive": destructive,
        **({"reason": str(c.get("reason", ""))} if required and c.get("reason") else {}),
    }
    c["requiresConfirmation"] = required
    c["destructive"] = destructive
    return c


def _normalize_status(raw: str) -> str:
    if raw in {
        "applied",
        "accepted_pending_builder",
        "no_change",
        "already_exists",
        "already_absent",
        "needs_confirmation",
        "rejected",
        "error",
    }:
        return raw
    if raw in {"already_completed", "already_applied"}:
        return "no_change"
    if raw in {"ok", "success"}:
        return "applied"
    return raw or "applied"


def _receipt(action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    operation = str(action.get("action", "")).strip() or "unknown"
    raw_status = str(result.get("status", "")).strip()
    target = _target_from_action(action)
    entity_id = target.get("entity_id")
    if not entity_id:
        entity_id = result.get("project_id") or result.get("task_id") or result.get("deadline_id") or result.get("calendar_event_id")

    receipt: dict[str, Any] = {
        "receipt_version": "1.0",
        "status": _normalize_status(raw_status),
        "operation_id": str(action.get("operation_id", "")).strip(),
        "operation": operation,
        "entity_type": target.get("entity_type", "unknown"),
        "summary": str(result.get("summary") or f"{operation}: {_normalize_status(raw_status)}"),
    }
    if entity_id:
        receipt["entity_id"] = str(entity_id)
    if result.get("event_id"):
        receipt["event_id"] = result.get("event_id")
    if "commit_sha" in result:
        receipt["commit_sha"] = result.get("commit_sha")
    if raw_status and raw_status != receipt["status"]:
        receipt["raw_status"] = raw_status

    # Preserve safe compatibility fields returned by legacy action handlers.
    for key in ("project_id", "task_id", "deadline_id", "calendar_event_id", "project_name"):
        if key in result and key not in receipt:
            receipt[key] = result[key]
    return receipt


def _authorized(headers: dict[str, str]) -> bool:
    if not base.EXTENSION_TOKEN:
        return False
    return secrets.compare_digest(headers.get("authorization", ""), f"Bearer {base.EXTENSION_TOKEN}")


async def app(scope, receive, send):
    if scope.get("type") == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

        if path in {"/extension/classify", "/extension/action"}:
            if not base.EXTENSION_TOKEN:
                return await base._send_json(send, 503, {"error": "extension_auth_not_configured"})
            if not _authorized(headers):
                return await base._send_json(send, 401, {"error": "unauthorized"})

        if path == "/extension/classify" and method == "POST":
            try:
                payload = await base._read_json_body(receive)
                turn = payload.get("turn") or {}
                client = payload.get("client") or {}
                if not isinstance(turn, dict):
                    raise ValueError("turn must be an object")
                if not isinstance(client, dict):
                    raise ValueError("client must be an object")
                state = await base._state()
                candidate = _normalize_candidate(classify_turn(turn, state, client))
                return await base._send_json(send, 200, {
                    "status": "ok",
                    "protocol_version": "1.0",
                    "classifier": "cloud-v1",
                    "candidate": candidate,
                })
            except ValueError as exc:
                return await base._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
            except httpx.HTTPStatusError as exc:
                return await base._send_json(send, 502, {"error": "github_error", "detail": str(exc.response.status_code)})
            except Exception as exc:
                return await base._send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})

        if path == "/extension/action" and method == "POST":
            try:
                payload = await base._read_json_body(receive)
                if not isinstance(payload, dict):
                    raise ValueError("action must be an object")
                result = await _EXECUTE_ACTION(payload)
                return await base._send_json(send, 200, _receipt(payload, result))
            except ValueError as exc:
                return await base._send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
            except httpx.HTTPStatusError as exc:
                return await base._send_json(send, 502, {"error": "github_error", "detail": str(exc.response.status_code)})
            except Exception as exc:
                return await base._send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})

    return await _LEGACY_APP(scope, receive, send)


mcp = base.mcp
