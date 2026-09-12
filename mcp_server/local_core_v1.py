from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from .cloud_classifier_v6 import classify_turn
from .local_actions_v1 import execute_action
from .storage_v1 import SQLiteCanonicalStore


def _target_from_action(action: dict[str, Any] | None) -> dict[str, Any]:
    action = action or {}
    op = str(action.get("action") or "").strip()
    groups = {
        "project": {"create_project", "update_project_snapshot", "update_project", "delete_project"},
        "task": {"create_task", "update_milestone", "complete_task", "delete_task"},
        "deadline": {"set_deadline"},
        "calendar_event": {"upsert_calendar_event", "remove_calendar_event"},
        "note": {"add_note", "update_note", "remove_note"},
        "resource": {"add_resource", "update_resource", "remove_resource"},
        "automation_rule": {"upsert_automation_rule", "remove_automation_rule"},
        "agent_policy": {"upsert_agent_policy", "remove_agent_policy"},
    }
    id_keys = {
        "project": ("project_id",),
        "task": ("task_id", "milestone_id"),
        "deadline": ("deadline_id",),
        "calendar_event": ("calendar_event_id",),
        "note": ("note_id",),
        "resource": ("resource_id",),
        "automation_rule": ("rule_id",),
        "agent_policy": ("policy_id",),
    }
    for entity_type, ops in groups.items():
        if op in ops:
            entity_id = next((action.get(key) for key in id_keys[entity_type] if action.get(key)), None)
            return {"entity_type": entity_type, **({"entity_id": str(entity_id)} if entity_id else {})}
    return {"entity_type": "unknown"}


def _normalize_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    value = dict(candidate)
    action = value.get("action")
    if isinstance(action, dict):
        action = dict(action)
        cid = str(value.get("id") or "").strip()
        if cid:
            action.setdefault("operation_id", cid)
        value["action"] = action
    destructive = bool(value.get("destructive"))
    required = bool(value.get("requiresConfirmation")) or destructive
    value["protocol_version"] = "local-1.0"
    value.setdefault("intent", str(value.get("kind") or (action or {}).get("action") or "informational"))
    value.setdefault("target", _target_from_action(action if isinstance(action, dict) else None))
    value["requiresConfirmation"] = required
    value["destructive"] = destructive
    value["confirmation"] = {"required": required, "destructive": destructive}
    return value


async def _read_json(receive) -> dict[str, Any]:
    chunks: list[bytes] = []
    more = True
    while more:
        message = await receive()
        if message.get("type") != "http.request":
            continue
        chunks.append(message.get("body", b""))
        more = bool(message.get("more_body"))
    if not chunks or not b"".join(chunks):
        return {}
    obj = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("request body must be an object")
    return obj


async def _send_json(send, status: int, body: dict[str, Any]) -> None:
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(raw)).encode())]})
    await send({"type": "http.response.body", "body": raw})


class LocalCoreApp:
    def __init__(self, db_path: str | Path, token: str | None = None):
        self.store = SQLiteCanonicalStore(db_path)
        saved = self.store.get_metadata("local_core_token")
        self.token = token or saved or secrets.token_urlsafe(32)
        if not saved or token:
            self.store.set_metadata("local_core_token", self.token)

    def _authorized(self, scope) -> bool:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        supplied = headers.get("authorization", "")
        return secrets.compare_digest(supplied, f"Bearer {self.token}")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await _send_json(send, 404, {"error": "not_found"})
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()

        if path == "/healthz" and method == "GET":
            state = self.store.get_state()
            return await _send_json(send, 200, {
                "status": "ok",
                "runtime": "nextplan-local-core-v1",
                "canonical_store": "sqlite-local",
                "schema_version": self.store.SCHEMA_VERSION,
                "project_count": len(state.get("projects", [])),
            })

        if not self._authorized(scope):
            return await _send_json(send, 401, {"error": "unauthorized"})

        try:
            if path == "/state" and method == "GET":
                return await _send_json(send, 200, self.store.get_state())

            if path == "/projects" and method == "GET":
                return await _send_json(send, 200, {"projects": self.store.get_state().get("projects", [])})

            if path == "/activity" and method == "GET":
                return await _send_json(send, 200, {"activity": self.store.list_activity(100)})

            if path == "/conversation/capture" and method == "POST":
                payload = await _read_json(receive)
                turn = payload.get("turn") or {}
                client = payload.get("client") or {}
                if not isinstance(turn, dict) or not isinstance(client, dict):
                    raise ValueError("turn and client must be objects")
                candidate = _normalize_candidate(classify_turn(turn, self.store.get_state(), client))
                response: dict[str, Any] = {
                    "status": "ok",
                    "runtime": "local-v1",
                    "candidate": candidate,
                }
                if payload.get("apply") and candidate and not candidate.get("requiresConfirmation") and isinstance(candidate.get("action"), dict):
                    response["receipt"] = execute_action(self.store, dict(candidate["action"]))
                return await _send_json(send, 200, response)

            if path == "/actions/execute" and method == "POST":
                payload = await _read_json(receive)
                action = payload.get("action") if isinstance(payload.get("action"), dict) else payload
                if not isinstance(action, dict):
                    raise ValueError("action must be an object")
                receipt = execute_action(self.store, action)
                return await _send_json(send, 200, receipt)

            return await _send_json(send, 404, {"error": "not_found"})
        except ValueError as exc:
            return await _send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
        except Exception as exc:
            return await _send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__})


def create_local_app(db_path: str | Path, token: str | None = None) -> LocalCoreApp:
    return LocalCoreApp(db_path, token=token)


_DEFAULT_DB = Path(os.getenv("NEXTPLAN_LOCAL_DB", str(Path.home() / ".nextplan" / "nextplan.db")))
app = create_local_app(_DEFAULT_DB, token=os.getenv("NEXTPLAN_LOCAL_TOKEN") or None)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("NEXTPLAN_LOCAL_PORT", "47123"))
    uvicorn.run("mcp_server.local_core_v1:app", host="127.0.0.1", port=port, reload=False)
