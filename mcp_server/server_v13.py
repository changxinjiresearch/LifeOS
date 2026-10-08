"""Opt-in Web-first Jarvis ASGI endpoints. Existing NextPlan stays untouched."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs

from . import server_v12 as legacy
from . import server_v11
from .jarvis_p0_contracts import JarvisContractError
from .jarvis_workspace_v1 import JarvisWorkspace
from .jarvis_brain_v1 import JarvisBrain

PREFIX = "/jarvis/v1"
ORIGINS = {"https://changxinjiresearch.github.io", "http://localhost:3000",
           "http://127.0.0.1:3000"}
_workspace = None


def _configured():
    return (os.getenv("NEXTPLAN_JARVIS_ENABLED") == "1"
            and len(os.getenv("NEXTPLAN_JARVIS_TOKEN", "")) >= 32
            and bool(os.getenv("NEXTPLAN_JARVIS_DB"))
            and bool(os.getenv("NEXTPLAN_JARVIS_PERSISTENT_ROOT")))


def _store():
    global _workspace
    if not _configured():
        raise RuntimeError("not configured")
    root = Path(os.environ["NEXTPLAN_JARVIS_PERSISTENT_ROOT"]).resolve(strict=True)
    db = Path(os.environ["NEXTPLAN_JARVIS_DB"]).expanduser().resolve()
    if not db.is_relative_to(root) or db == root:
        raise RuntimeError("db outside persistent storage")
    if os.getenv("NEXTPLAN_JARVIS_TEST_MODE") != "1" and not os.path.ismount(root):
        raise RuntimeError("persistent volume missing")
    if _workspace is None or _workspace.path != db:
        _workspace = JarvisWorkspace(db)
    return _workspace


def _headers(scope):
    return {k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])}


async def _send(send, status, obj, origin=""):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    hs = [(b"content-type", b"application/json; charset=utf-8"),
          (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
    if origin in ORIGINS:
        hs += [(b"access-control-allow-origin", origin.encode()), (b"vary", b"Origin")]
    await send({"type": "http.response.start", "status": status, "headers": hs})
    await send({"type": "http.response.body", "body": body})


async def _payload(scope, receive):
    body = bytearray()
    while True:
        part = await receive()
        if part.get("type") == "http.disconnect":
            raise JarvisContractError("disconnected")
        body.extend(part.get("body", b""))
        if len(body) > 32768:
            raise JarvisContractError("request too large")
        if not part.get("more_body"):
            break
    obj = json.loads(body) if body else {}
    if not isinstance(obj, dict):
        raise JarvisContractError("JSON object expected")
    return obj


async def app(scope, receive, send):
    if scope.get("type") != "http" or not str(scope.get("path") or "").startswith(PREFIX):
        return await legacy.app(scope, receive, send)
    path = str(scope.get("path") or "")
    method = str(scope.get("method") or "GET").upper()
    headers = _headers(scope)
    origin = headers.get("origin", "")
    if origin and origin not in ORIGINS:
        return await _send(send, 403, {"error": "origin_forbidden"})
    if method == "OPTIONS":
        if origin not in ORIGINS:
            return await _send(send, 403, {"error": "origin_forbidden"})
        await send({"type": "http.response.start", "status": 204, "headers": [
            (b"access-control-allow-origin", origin.encode()),
            (b"access-control-allow-methods", b"GET,POST,OPTIONS"),
            (b"access-control-allow-headers", b"authorization,content-type"),
            (b"access-control-max-age", b"600"), (b"vary", b"Origin")]})
        return await send({"type": "http.response.body", "body": b""})
    if path == PREFIX + "/status" and method == "GET":
        return await _send(send, 200, {
            "status": "available" if _configured() else "disabled",
            "private_storage": "configured" if _configured() else "not_configured",
            "canonical_sync": "not_migrated",
            "automatic_chatgpt_context": False}, origin)
    if not _configured():
        return await _send(send, 503, {"error": "jarvis_private_store_not_configured"}, origin)
    auth = headers.get("authorization", "")
    if not secrets.compare_digest(auth, "Bearer " + os.environ["NEXTPLAN_JARVIS_TOKEN"]):
        return await _send(send, 401, {"error": "unauthorized"}, origin)
    if method not in {"GET", "POST"}:
        return await _send(send, 405, {"error": "method_not_allowed"}, origin)
    try:
        store = _store()
        q = parse_qs((scope.get("query_string") or b"").decode("utf-8"))
        arg = lambda key: q.get(key, [""])[0]
        payload = await _payload(scope, receive) if method == "POST" else {}
        if path == PREFIX + "/capabilities" and method == "GET":
            result = JarvisBrain(store).capabilities()
        elif path == PREFIX + "/legacy/projects" and method == "GET":
            state = await server_v11.base._state()
            result = {"status": "read_only", "authority": "legacy_github",
                      "projects": [{"id": p.get("id"), "name": p.get("name"),
                                    "status": p.get("status"), "next_action": p.get("next_action")}
                                   for p in state.get("projects", [])]}
        elif path == PREFIX + "/sync/state" and method == "GET":
            result = store.snapshot()
        elif path == PREFIX + "/sync/bootstrap" and method == "POST":
            result = store.bootstrap(payload.get("projects"),
                                     explicitly_confirmed=payload.get("confirmed") is True)
        elif path == PREFIX + "/sync/action" and method == "POST":
            result = store.mutate(payload.get("intent"), payload.get("values"))
        elif path == PREFIX + "/context/record" and method == "POST":
            result = store.record_context(payload)
        elif path == PREFIX + "/knowledge/search" and method == "GET":
            result = {"items": store.search(arg("q"), arg("project_id"))}
        elif path == PREFIX + "/knowledge/delete" and method == "POST":
            result = store.delete_context(payload.get("id"),
                                          confirmed=payload.get("confirmed") is True)
        elif path == PREFIX + "/context/bundle" and method == "GET":
            result = store.context_bundle(arg("project_id"))
        elif path == PREFIX + "/brain/ask" and method == "POST":
            result = await JarvisBrain(store).ask(payload.get("question"),
                                                  payload.get("project_id", ""))
        else:
            return await _send(send, 404, {"error": "not_found"}, origin)
        return await _send(send, 200, result, origin)
    except JarvisContractError as exc:
        return await _send(send, 400, {"error": "validation_error", "detail": str(exc)}, origin)
    except (OSError, RuntimeError, sqlite3.Error):
        return await _send(send, 503, {"error": "jarvis_private_store_unavailable"}, origin)
    except (ValueError, TypeError, json.JSONDecodeError):
        return await _send(send, 400, {"error": "invalid_request"}, origin)


mcp = legacy.mcp
