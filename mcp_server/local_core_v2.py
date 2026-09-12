from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from .local_actions_v2 import execute_action
from .local_classifier_v1 import classify_local_turn
from .local_pairing_v1 import LocalPairingManager
from .storage_v1 import SQLiteCanonicalStore


def _target_from_action(action: dict[str, Any] | None) -> dict[str, Any]:
    action = action or {}
    op = str(action.get("action") or "").strip()
    groups = {
        "project": {"create_project", "create_project_blueprint", "update_project_snapshot", "update_project", "delete_project"},
        "task": {"create_task", "update_milestone", "complete_task", "delete_task"},
        "deadline": {"set_deadline"},
    }
    id_keys = {"project": ("project_id",), "task": ("task_id", "milestone_id"), "deadline": ("deadline_id",)}
    for entity_type, ops in groups.items():
        if op in ops:
            entity_id = next((action.get(k) for k in id_keys[entity_type] if action.get(k)), None)
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
        provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
        if provenance.get("evidenceText"):
            action.setdefault("evidence_text", provenance["evidenceText"])
        value["action"] = action
    destructive = bool(value.get("destructive"))
    required = bool(value.get("requiresConfirmation")) or destructive
    value["protocol_version"] = "local-2.0"
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
    raw = b"".join(chunks)
    if not raw:
        return {}
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("request body must be an object")
    return obj


async def _send_json(send, status: int, body: dict[str, Any]) -> None:
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(raw)).encode()),
        (b"access-control-allow-origin", b"chrome-extension://*"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": raw})


class LocalCoreAppV2:
    def __init__(self, db_path: str | Path, bootstrap_token: str | None = None):
        self.store = SQLiteCanonicalStore(db_path)
        self.bootstrap_token = bootstrap_token
        self.pairing = LocalPairingManager()

    def issue_pairing_code(self) -> str:
        return self.pairing.issue_code()

    def _paired_token(self) -> str:
        return self.store.get_metadata("paired_extension_token") or ""

    def _authorized(self, scope) -> bool:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        supplied = headers.get("authorization", "")
        candidates = [x for x in (self.bootstrap_token, self._paired_token()) if x]
        return any(secrets.compare_digest(supplied, f"Bearer {token}") for token in candidates)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await _send_json(send, 404, {"error": "not_found"})
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()

        if path == "/healthz" and method == "GET":
            state = self.store.get_state()
            return await _send_json(send, 200, {
                "status": "ok",
                "runtime": "nextplan-local-core-v2",
                "canonical_store": "sqlite-local",
                "schema_version": self.store.SCHEMA_VERSION,
                "project_count": len(state.get("projects", [])),
                "paired": bool(self._paired_token()),
            })

        if path == "/pairing/status" and method == "GET":
            return await _send_json(send, 200, {
                "status": "ok",
                "paired": bool(self._paired_token()),
                "pairing": self.pairing.status(),
            })

        if path == "/pairing/complete" and method == "POST":
            payload = await _read_json(receive)
            code = str(payload.get("code") or "").strip()
            extension_id = str(payload.get("extension_id") or "").strip()[:200]
            if not code or not self.pairing.consume(code):
                return await _send_json(send, 403, {"error": "invalid_or_expired_pairing_code"})
            token = secrets.token_urlsafe(32)
            self.store.set_metadata("paired_extension_token", token)
            if extension_id:
                self.store.set_metadata("paired_extension_id", extension_id)
            return await _send_json(send, 200, {"status": "paired", "token": token})

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
                candidate = _normalize_candidate(classify_local_turn(turn, self.store.get_state(), client))
                response: dict[str, Any] = {"status": "ok", "runtime": "local-v2", "candidate": candidate}
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


def create_local_app(db_path: str | Path, bootstrap_token: str | None = None) -> LocalCoreAppV2:
    return LocalCoreAppV2(db_path, bootstrap_token=bootstrap_token)


_DEFAULT_DB = Path(os.getenv("NEXTPLAN_LOCAL_DB", str(Path.home() / ".nextplan" / "nextplan.db")))
app = create_local_app(_DEFAULT_DB, bootstrap_token=os.getenv("NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN") or None)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("NEXTPLAN_LOCAL_PORT", "47123"))
    uvicorn.run("mcp_server.local_core_v2:app", host="127.0.0.1", port=port, reload=False)
