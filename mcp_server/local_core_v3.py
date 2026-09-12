from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from .local_actions_v3 import execute_action
from .local_classifier_v1 import classify_local_turn
from .local_execution_v1 import LocalExecutionGateway
from .local_pairing_v1 import LocalPairingManager
from .storage_v2 import SQLiteCanonicalStoreV2


def _origin(scope: dict[str, Any]) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    value = headers.get("origin", "")
    if value.startswith("chrome-extension://") or value in {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost", "http://localhost", "http://127.0.0.1"}:
        return value
    return ""


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


async def _send_json(send, status: int, body: dict[str, Any], origin: str = "") -> None:
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(raw)).encode()),
        (b"access-control-allow-headers", b"authorization,content-type"),
        (b"access-control-allow-methods", b"GET,POST,OPTIONS"),
    ]
    if origin:
        headers.append((b"access-control-allow-origin", origin.encode()))
        headers.append((b"vary", b"Origin"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": raw})


def _today(state: dict[str, Any]) -> dict[str, Any]:
    active = [p for p in state.get("projects", []) if str(p.get("status")) == "active"]
    blocked = [p for p in state.get("projects", []) if str(p.get("status")) == "blocked"]
    waiting = [p for p in state.get("projects", []) if str(p.get("status")) == "waiting"]
    active.sort(key=lambda p: (int(p.get("priority") or 2), str(p.get("name") or "")))
    items = [
        {"project_id": p.get("id"), "project": p.get("name"), "next_action": p.get("next_action") or "", "priority": p.get("priority", 2)}
        for p in active if p.get("next_action")
    ]
    return {"top_action": items[0] if items else None, "active": items, "waiting": waiting, "blocked": blocked}


class LocalCoreAppV3:
    def __init__(self, db_path: str | Path, bootstrap_token: str | None = None, *, execution_dry_run: bool = False):
        self.store = SQLiteCanonicalStoreV2(db_path)
        self.db_path = str(Path(db_path).expanduser().resolve())
        self.bootstrap_token = bootstrap_token
        self.pairing = LocalPairingManager()
        self.execution = LocalExecutionGateway(self.store, dry_run=execution_dry_run)

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
        origin = _origin(scope)

        if method == "OPTIONS":
            return await _send_json(send, 204, {}, origin)

        if path == "/healthz" and method == "GET":
            state = self.store.get_state()
            return await _send_json(send, 200, {
                "status": "ok",
                "runtime": "nextplan-local-core-v3",
                "canonical_store": "sqlite-local",
                "schema_version": self.store.SCHEMA_VERSION,
                "project_count": len(state.get("projects", [])),
                "paired": bool(self._paired_token()),
            }, origin)

        if path == "/pairing/status" and method == "GET":
            return await _send_json(send, 200, {"status": "ok", "paired": bool(self._paired_token()), "pairing": self.pairing.status()}, origin)

        if path == "/pairing/complete" and method == "POST":
            payload = await _read_json(receive)
            code = str(payload.get("code") or "").strip()
            extension_id = str(payload.get("extension_id") or "").strip()[:200]
            if not code or not self.pairing.consume(code):
                return await _send_json(send, 403, {"error": "invalid_or_expired_pairing_code"}, origin)
            token = secrets.token_urlsafe(32)
            self.store.set_metadata("paired_extension_token", token)
            if extension_id:
                self.store.set_metadata("paired_extension_id", extension_id)
            return await _send_json(send, 200, {"status": "paired", "token": token}, origin)

        if not self._authorized(scope):
            return await _send_json(send, 401, {"error": "unauthorized"}, origin)

        try:
            if path == "/pairing/code" and method == "POST":
                return await _send_json(send, 200, {"status": "ok", "code": self.issue_pairing_code(), "expires_in_seconds": self.pairing.ttl_seconds}, origin)

            if path == "/state" and method == "GET":
                return await _send_json(send, 200, self.store.get_state(), origin)
            if path == "/projects" and method == "GET":
                return await _send_json(send, 200, {"projects": self.store.get_state().get("projects", [])}, origin)
            if path == "/today" and method == "GET":
                return await _send_json(send, 200, _today(self.store.get_state()), origin)
            if path == "/activity" and method == "GET":
                return await _send_json(send, 200, {"activity": self.store.list_activity(200)}, origin)
            if path == "/workspaces" and method == "GET":
                return await _send_json(send, 200, {"workspaces": self.store.get_state().get("workspace_bindings", [])}, origin)
            if path == "/artifacts" and method == "GET":
                return await _send_json(send, 200, {"artifacts": self.store.get_state().get("artifacts", [])}, origin)
            if path == "/permissions" and method == "GET":
                return await _send_json(send, 200, {"permissions": self.store.get_state().get("local_permissions", {})}, origin)
            if path == "/pending" and method == "GET":
                return await _send_json(send, 200, {"pending": self.store.list_pending_candidates(100)}, origin)
            if path == "/desktop/status" and method == "GET":
                state = self.store.get_state()
                return await _send_json(send, 200, {
                    "status": "ok",
                    "runtime": "nextplan-local-core-v3",
                    "db_path": self.db_path,
                    "paired": bool(self._paired_token()),
                    "pending_count": len(self.store.list_pending_candidates(500)),
                    "permission_mode": (state.get("local_permissions") or {}).get("mode", "balanced"),
                }, origin)

            if path == "/conversation/capture" and method == "POST":
                payload = await _read_json(receive)
                turn = payload.get("turn") or {}
                client = payload.get("client") or {}
                if not isinstance(turn, dict) or not isinstance(client, dict):
                    raise ValueError("turn and client must be objects")
                candidate = classify_local_turn(turn, self.store.get_state(), client)
                response: dict[str, Any] = {"status": "ok", "runtime": "local-v3", "candidate": candidate}
                if candidate and candidate.get("requiresConfirmation"):
                    self.store.queue_candidate(candidate, {"title": turn.get("title"), "url": turn.get("url"), "userText": str(turn.get("userText") or "")[:1000]})
                    response["queued"] = True
                elif payload.get("apply") and candidate and isinstance(candidate.get("action"), dict):
                    response["receipt"] = execute_action(self.store, dict(candidate["action"]))
                return await _send_json(send, 200, response, origin)

            if path == "/pending/apply" and method == "POST":
                payload = await _read_json(receive)
                candidate_id = str(payload.get("id") or "").strip()
                candidate = self.store.get_pending_candidate(candidate_id)
                if not candidate or not isinstance(candidate.get("action"), dict):
                    raise ValueError("pending candidate not found")
                receipt = execute_action(self.store, dict(candidate["action"]))
                self.store.resolve_candidate(candidate_id, "applied", receipt)
                return await _send_json(send, 200, receipt, origin)

            if path == "/pending/ignore" and method == "POST":
                payload = await _read_json(receive)
                result = self.store.resolve_candidate(str(payload.get("id") or "").strip(), "ignored", {"reason": "user_ignored"})
                return await _send_json(send, 200, result, origin)

            if path in {"/actions/execute", "/workspaces/bind", "/artifacts/attach", "/artifacts/verify", "/permissions/update"} and method == "POST":
                payload = await _read_json(receive)
                action = payload.get("action") if isinstance(payload.get("action"), dict) else payload
                if path == "/workspaces/bind":
                    action = {"action": "bind_workspace", **action}
                elif path == "/artifacts/attach":
                    action = {"action": "attach_artifact", **action}
                elif path == "/artifacts/verify":
                    action = {"action": "verify_artifact", **action}
                elif path == "/permissions/update":
                    action = {"action": "update_local_permissions", **action}
                receipt = execute_action(self.store, action)
                return await _send_json(send, 200, receipt, origin)

            if path == "/local-actions/preview" and method == "POST":
                payload = await _read_json(receive)
                action = payload.get("action") if isinstance(payload.get("action"), dict) else payload
                return await _send_json(send, 200, self.execution.preview(action), origin)

            if path == "/local-actions/execute" and method == "POST":
                payload = await _read_json(receive)
                action = payload.get("action") if isinstance(payload.get("action"), dict) else payload
                receipt = self.execution.execute(action, confirmed=bool(payload.get("confirmed")))
                return await _send_json(send, 200, receipt, origin)

            return await _send_json(send, 404, {"error": "not_found"}, origin)
        except PermissionError as exc:
            return await _send_json(send, 403, {"error": "permission_denied", "detail": str(exc)}, origin)
        except (ValueError, FileExistsError) as exc:
            return await _send_json(send, 400, {"error": "invalid_request", "detail": str(exc)}, origin)
        except Exception as exc:
            return await _send_json(send, 500, {"error": "internal_error", "detail": type(exc).__name__}, origin)


def create_local_app(db_path: str | Path, bootstrap_token: str | None = None, *, execution_dry_run: bool = False) -> LocalCoreAppV3:
    return LocalCoreAppV3(db_path, bootstrap_token=bootstrap_token, execution_dry_run=execution_dry_run)


_DEFAULT_DB = Path(os.getenv("NEXTPLAN_LOCAL_DB", str(Path.home() / ".nextplan" / "nextplan.db")))
app = create_local_app(_DEFAULT_DB, bootstrap_token=os.getenv("NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN") or None)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("NEXTPLAN_LOCAL_PORT", "47123"))
    uvicorn.run("mcp_server.local_core_v3:app", host="127.0.0.1", port=port, reload=False)
