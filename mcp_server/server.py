from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

APP_NAME = "NextPlan"
REPO = os.getenv("NEXTPLAN_GITHUB_REPO", "changxinjiresearch/LifeOS")
BRANCH = os.getenv("NEXTPLAN_GITHUB_BRANCH", "main")
STATE_PATH = os.getenv("NEXTPLAN_STATE_PATH", "state.json")
EVENT_DIR = os.getenv("NEXTPLAN_EVENT_DIR", "events/inbox").strip("/")
GITHUB_TOKEN = os.getenv("NEXTPLAN_GITHUB_TOKEN", "")
MCP_BEARER_TOKEN = os.getenv("NEXTPLAN_MCP_BEARER_TOKEN", "")
MCP_PATH_SECRET = os.getenv("NEXTPLAN_MCP_PATH_SECRET", "")
EXTENSION_TOKEN = os.getenv("NEXTPLAN_EXTENSION_TOKEN", "")
ALLOW_INSECURE = os.getenv("NEXTPLAN_ALLOW_INSECURE", "").strip().lower() in {"1", "true", "yes"}
GITHUB_API = "https://api.github.com"
ALLOWED_STATUS = {"active", "waiting", "planned", "completed", "done", "blocked"}

WRITE_ANN = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
READ_ANN = ToolAnnotations(read_only_hint=True, open_world_hint=False)

mcp = MCPServer(
    APP_NAME,
    instructions=(
        "NextPlan is the user's canonical cross-domain task and project state. "
        "When a conversation confirms a meaningful new task, completion, status change, deadline, note, or safe resource pointer, proactively use the appropriate NextPlan tool before finishing the reply. "
        "Use write tools only for confirmed state changes. Discussion, hypotheticals, "
        "tentative plans and unconfirmed completions must not be written. When uncertain, ask first. "
        "Never store secrets, credentials, bank details, identity numbers, medical records or sensitive document contents."
    ),
)


def _require_config() -> None:
    if not GITHUB_TOKEN:
        raise RuntimeError("NEXTPLAN_GITHUB_TOKEN is not configured")


def _headers() -> dict[str, str]:
    _require_config()
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "NextPlan-MCP/1.0",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(text: str, max_len: int = 32) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return (s[:max_len] or "item")


def _event_id(prefix: str) -> str:
    return f"evt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{prefix}-{uuid.uuid4().hex[:8]}"


def _validate_status(status: str, field: str = "status") -> str:
    value = status.strip()
    if value and value not in ALLOWED_STATUS:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(ALLOWED_STATUS))}")
    return value


def _validate_date(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date must be a real calendar date in YYYY-MM-DD format") from exc
    return value


async def _github_get_json(path: str) -> dict[str, Any]:
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    params = {"ref": BRANCH}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=_headers(), params=params)
        r.raise_for_status()
        payload = r.json()
    if payload.get("encoding") != "base64":
        raise RuntimeError(f"Unexpected encoding for {path}")
    raw = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(raw)


async def _github_create_text(path: str, text: str, message: str) -> dict[str, Any]:
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    body = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
    }
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.put(url, headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


async def _state() -> dict[str, Any]:
    return await _github_get_json(STATE_PATH)


async def _wait_applied(event_id: str, timeout_seconds: float = 25.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            last = await _state()
            ids = set(last.get("system", {}).get("event_layer", {}).get("processed_event_ids", []))
            if event_id in ids:
                return {"status": "applied", "event_id": event_id, "state": last}
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return {"status": "accepted_pending_builder", "event_id": event_id, "state": last}


async def _emit(event: dict[str, Any], *, via: str = "nextplan-mcp") -> dict[str, Any]:
    eid = event.setdefault("id", _event_id(_slug(event.get("type", "event"), 18)))
    event.setdefault("at", _now_iso())
    event.setdefault("source", {"kind": "chatgpt", "via": via})
    path = f"{EVENT_DIR}/{eid}.json"
    text = json.dumps(event, ensure_ascii=False, indent=2) + "\n"
    result = await _github_create_text(path, text, f"NextPlan: {event.get('summary') or event['type']}")
    waited = await _wait_applied(eid)
    waited["commit_sha"] = result.get("commit", {}).get("sha")
    waited.pop("state", None)
    return waited


def _find_project(state: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    return next((p for p in state.get("projects", []) if p.get("id") == project_id), None)


def _find_milestone(project: dict[str, Any], milestone_id: str) -> dict[str, Any] | None:
    return next((m for m in project.get("milestones", []) if m.get("id") == milestone_id), None)


@mcp.tool(title="Get NextPlan state", annotations=READ_ANN)
async def get_state() -> dict[str, Any]:
    """Read the canonical NextPlan state. Use this before writes when matching an existing project/task matters."""
    return await _state()


@mcp.tool(title="Search NextPlan", annotations=READ_ANN)
async def search_state(query: str) -> dict[str, Any]:
    """Search projects, milestones and recent events by text without changing anything."""
    q = query.strip().casefold()
    s = await _state()
    projects = []
    for p in s.get("projects", []):
        hit_ms = [m for m in p.get("milestones", []) if q in str(m.get("name", "")).casefold()]
        hay = " ".join([str(p.get("id", "")), str(p.get("name", "")), str(p.get("next_action", "")), str(p.get("category", ""))]).casefold()
        if q in hay or hit_ms:
            projects.append({**p, "matching_milestones": hit_ms})
    events = [e for e in s.get("events", []) if q in (str(e.get("summary", "")) + " " + str(e.get("type", ""))).casefold()][:20]
    return {"projects": projects, "events": events}


@mcp.tool(title="Create NextPlan project", annotations=WRITE_ANN)
async def create_project(name: str, category: str, next_action: str, priority: int = 2, project_id: str = "") -> dict[str, Any]:
    """Create a project only after the user has clearly decided to pursue it. Do not use for brainstorming or tentative ideas."""
    s = await _state()
    normalized = name.strip().casefold()
    for p in s.get("projects", []):
        if str(p.get("name", "")).strip().casefold() == normalized:
            return {"status": "already_exists", "project": p}
    pid = project_id.strip() or f"project-{_slug(name)}-{uuid.uuid4().hex[:6]}"
    event = {
        "type": "project_created",
        "project_id": pid,
        "summary": f"Created project: {name}",
        "project": {"id": pid, "name": name.strip(), "category": category.strip(), "status": "active", "priority": max(1, min(3, int(priority))), "next_action": next_action.strip(), "milestones": []},
    }
    return await _emit(event)


@mcp.tool(title="Create NextPlan task", annotations=WRITE_ANN)
async def create_task(project_id: str, name: str, next_action: str = "", task_id: str = "") -> dict[str, Any]:
    """Create an actionable task only when the user has explicitly decided it should be done. Duplicate task names in the same project are not recreated."""
    s = await _state()
    p = _find_project(s, project_id)
    if not p:
        raise ValueError(f"Unknown project_id: {project_id}")
    normalized = name.strip().casefold()
    for m in p.get("milestones", []):
        if str(m.get("name", "")).strip().casefold() == normalized:
            return {"status": "already_exists", "project_id": project_id, "task": m}
    tid = task_id.strip() or f"task-{_slug(name)}-{uuid.uuid4().hex[:6]}"
    event = {
        "type": "task_created",
        "project_id": project_id,
        "summary": f"Created task: {name}",
        "task": {"id": tid, "name": name.strip(), "status": "active"},
    }
    if next_action.strip():
        event["next_action"] = next_action.strip()
    return await _emit(event)


@mcp.tool(title="Complete NextPlan task", annotations=WRITE_ANN)
async def complete_task(project_id: str, task_id: str, next_action: str = "", project_status: str = "") -> dict[str, Any]:
    """Mark a task/milestone completed only when completion is confirmed by the user or reliable evidence. A draft is not a send; a plan is not completion."""
    s = await _state()
    p = _find_project(s, project_id)
    if not p:
        raise ValueError(f"Unknown project_id: {project_id}")
    m = _find_milestone(p, task_id)
    if not m:
        raise ValueError(f"Unknown task_id {task_id} in {project_id}")
    if m.get("status") == "completed":
        return {"status": "already_completed", "project_id": project_id, "task": m}
    event: dict[str, Any] = {
        "type": "task_completed",
        "project_id": project_id,
        "task_id": task_id,
        "summary": f"Completed task: {m.get('name', task_id)}",
    }
    if next_action.strip():
        event["next_action"] = next_action.strip()
    if project_status.strip():
        event["project_status"] = project_status.strip()
    return await _emit(event)


@mcp.tool(title="Update NextPlan milestone", annotations=WRITE_ANN)
async def update_milestone(project_id: str, milestone_id: str, status: str, next_action: str = "", name: str = "", project_status: str = "") -> dict[str, Any]:
    """Update a known milestone after its state change is confirmed. Valid statuses: active, waiting, planned, completed, blocked."""
    event: dict[str, Any] = {
        "type": "milestone_status_changed",
        "project_id": project_id,
        "milestone_id": milestone_id,
        "status": _validate_status(status),
        "summary": f"Milestone {milestone_id} -> {status}",
    }
    if next_action.strip(): event["next_action"] = next_action.strip()
    if name.strip(): event["name"] = name.strip()
    if project_status.strip(): event["project_status"] = _validate_status(project_status, "project_status")
    return await _emit(event)


@mcp.tool(title="Update NextPlan project", annotations=WRITE_ANN)
async def update_project(project_id: str, status: str = "", next_action: str = "", priority: int = 0) -> dict[str, Any]:
    """Update a project's confirmed status, next action, or priority. Do not infer completion from discussion."""
    changes: dict[str, Any] = {}
    if status.strip(): changes["status"] = _validate_status(status)
    if next_action.strip(): changes["next_action"] = next_action.strip()
    if priority: changes["priority"] = max(1, min(3, int(priority)))
    if not changes:
        return {"status": "no_change"}
    return await _emit({"type": "project_updated", "project_id": project_id, "changes": changes, "summary": f"Updated project: {project_id}"})


@mcp.tool(title="Set NextPlan deadline", annotations=WRITE_ANN)
async def set_deadline(project_id: str, title: str, date: str, category: str = "", deadline_id: str = "") -> dict[str, Any]:
    """Record a deadline only when its date is confirmed. Date must be YYYY-MM-DD."""
    date = _validate_date(date)
    did = deadline_id.strip() or f"deadline-{_slug(title)}-{date}"
    deadline = {"id": did, "project_id": project_id, "title": title.strip(), "date": date}
    if category.strip(): deadline["category"] = category.strip()
    return await _emit({"type": "deadline_set", "project_id": project_id, "deadline": deadline, "summary": f"Set deadline: {title} on {date}"})


@mcp.tool(title="Add NextPlan note", annotations=WRITE_ANN)
async def add_note(title: str, body: str, category: str = "Note") -> dict[str, Any]:
    """Save a non-sensitive note when the user explicitly asks to keep an idea or reference that is not yet a task."""
    nid = f"note-{_slug(title)}-{uuid.uuid4().hex[:6]}"
    return await _emit({"type": "note_added", "summary": f"Added note: {title}", "note": {"id": nid, "title": title.strip(), "body": body.strip(), "category": category.strip() or "Note"}})


@mcp.tool(title="Add NextPlan resource", annotations=WRITE_ANN)
async def add_resource(title: str, location: str, description: str = "", resource_type: str = "link") -> dict[str, Any]:
    """Add a safe pointer to a resource. Store only locations/links and high-level descriptions, never sensitive file contents or secrets."""
    rid = f"resource-{_slug(title)}-{uuid.uuid4().hex[:6]}"
    resource = {"id": rid, "title": title.strip(), "location": location.strip(), "type": resource_type.strip() or "link"}
    if description.strip(): resource["description"] = description.strip()
    return await _emit({"type": "resource_added", "summary": f"Added resource: {title}", "resource": resource})


async def _extension_action(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a small, pre-structured action from the local Chrome bridge.

    The bridge never sends the whole conversation. It sends only the action the
    deterministic local classifier has selected, plus the minimal matching IDs.
    """
    action = str(payload.get("action", "")).strip()
    s = await _state()

    if action == "complete_task":
        project_id = str(payload.get("project_id", "")).strip()
        task_id = str(payload.get("task_id", "")).strip()
        p = _find_project(s, project_id)
        if not p:
            raise ValueError(f"Unknown project_id: {project_id}")
        m = _find_milestone(p, task_id)
        if not m:
            raise ValueError(f"Unknown task_id {task_id} in {project_id}")
        if m.get("status") == "completed":
            return {"status": "already_completed", "project_id": project_id, "task_id": task_id}
        event: dict[str, Any] = {
            "type": "task_completed",
            "project_id": project_id,
            "task_id": task_id,
            "summary": f"Completed task: {m.get('name', task_id)}",
        }
        next_action = str(payload.get("next_action", "")).strip()
        if next_action:
            event["next_action"] = next_action
        project_status = str(payload.get("project_status", "")).strip()
        if project_status:
            event["project_status"] = _validate_status(project_status, "project_status")
        return await _emit(event, via="nextplan-chrome-bridge")

    if action == "update_milestone":
        project_id = str(payload.get("project_id", "")).strip()
        milestone_id = str(payload.get("milestone_id", "")).strip()
        p = _find_project(s, project_id)
        if not p or not _find_milestone(p, milestone_id):
            raise ValueError("Unknown project_id or milestone_id")
        status = _validate_status(str(payload.get("status", "")))
        if not status:
            raise ValueError("status is required")
        event = {
            "type": "milestone_status_changed",
            "project_id": project_id,
            "milestone_id": milestone_id,
            "status": status,
            "summary": f"Milestone {milestone_id} -> {status}",
        }
        next_action = str(payload.get("next_action", "")).strip()
        if next_action:
            event["next_action"] = next_action
        return await _emit(event, via="nextplan-chrome-bridge")

    if action == "update_project":
        project_id = str(payload.get("project_id", "")).strip()
        if not _find_project(s, project_id):
            raise ValueError(f"Unknown project_id: {project_id}")
        changes: dict[str, Any] = {}
        status = str(payload.get("status", "")).strip()
        if status:
            changes["status"] = _validate_status(status)
        next_action = str(payload.get("next_action", "")).strip()
        if next_action:
            changes["next_action"] = next_action
        if not changes:
            raise ValueError("No project changes supplied")
        return await _emit({
            "type": "project_updated",
            "project_id": project_id,
            "changes": changes,
            "summary": f"Updated project: {project_id}",
        }, via="nextplan-chrome-bridge")

    if action == "create_task":
        project_id = str(payload.get("project_id", "")).strip()
        p = _find_project(s, project_id)
        if not p:
            raise ValueError(f"Unknown project_id: {project_id}")
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        normalized = name.casefold()
        for m in p.get("milestones", []):
            if str(m.get("name", "")).strip().casefold() == normalized:
                return {"status": "already_exists", "project_id": project_id, "task_id": m.get("id")}
        tid = str(payload.get("task_id", "")).strip() or f"task-{_slug(name)}-{uuid.uuid4().hex[:6]}"
        event = {
            "type": "task_created",
            "project_id": project_id,
            "summary": f"Created task: {name}",
            "task": {"id": tid, "name": name, "status": "active"},
        }
        next_action = str(payload.get("next_action", "")).strip()
        if next_action:
            event["next_action"] = next_action
        return await _emit(event, via="nextplan-chrome-bridge")

    if action == "set_deadline":
        project_id = str(payload.get("project_id", "")).strip()
        if not _find_project(s, project_id):
            raise ValueError(f"Unknown project_id: {project_id}")
        title = str(payload.get("title", "")).strip()
        date = _validate_date(str(payload.get("date", "")))
        if not title:
            raise ValueError("title is required")
        did = str(payload.get("deadline_id", "")).strip() or f"deadline-{_slug(title)}-{date}"
        deadline = {"id": did, "project_id": project_id, "title": title, "date": date}
        return await _emit({
            "type": "deadline_set",
            "project_id": project_id,
            "deadline": deadline,
            "summary": f"Set deadline: {title} on {date}",
        }, via="nextplan-chrome-bridge")

    raise ValueError(f"Unsupported extension action: {action}")


async def _send_json(send, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"cache-control", b"no-store"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def _read_json_body(receive, max_bytes: int = 64_000) -> dict[str, Any]:
    data = bytearray()
    more = True
    while more:
        message = await receive()
        if message.get("type") != "http.request":
            continue
        chunk = message.get("body", b"")
        data.extend(chunk)
        if len(data) > max_bytes:
            raise ValueError("request too large")
        more = bool(message.get("more_body", False))
    if not data:
        return {}
    parsed = json.loads(bytes(data).decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("JSON body must be an object")
    return parsed


class NextPlanAuthMiddleware:
    """ASGI guard for MCP plus a minimal authenticated Chrome bridge API."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")

        if path == "/healthz":
            return await _send_json(send, 200, {"status": "ok", "service": "NextPlan MCP"})

        if path.startswith("/extension/"):
            if not EXTENSION_TOKEN:
                return await _send_json(send, 503, {"error": "extension_auth_not_configured"})
            if not secrets.compare_digest(auth, f"Bearer {EXTENSION_TOKEN}"):
                return await _send_json(send, 401, {"error": "unauthorized"})
            try:
                if path == "/extension/state" and method == "GET":
                    return await _send_json(send, 200, await _state())
                if path == "/extension/action" and method == "POST":
                    payload = await _read_json_body(receive)
                    return await _send_json(send, 200, await _extension_action(payload))
                return await _send_json(send, 404, {"error": "not_found"})
            except ValueError as exc:
                return await _send_json(send, 400, {"error": "invalid_request", "detail": str(exc)})
            except httpx.HTTPStatusError as exc:
                return await _send_json(send, 502, {"error": "github_error", "detail": str(exc.response.status_code)})
            except Exception:
                return await _send_json(send, 500, {"error": "internal_error"})

        if not (MCP_BEARER_TOKEN or MCP_PATH_SECRET or ALLOW_INSECURE):
            return await _send_json(send, 503, {"error": "server_auth_not_configured"})

        bearer_ok = bool(MCP_BEARER_TOKEN) and secrets.compare_digest(auth, f"Bearer {MCP_BEARER_TOKEN}")
        path_ok = False
        if MCP_PATH_SECRET:
            prefix = f"/{MCP_PATH_SECRET}"
            if path == f"{prefix}/mcp" or path.startswith(f"{prefix}/mcp/"):
                path_ok = True
                scope = dict(scope)
                scope["path"] = path[len(prefix):] or "/mcp"
                scope["raw_path"] = scope["path"].encode()

        if not ALLOW_INSECURE and (MCP_BEARER_TOKEN or MCP_PATH_SECRET) and not (bearer_ok or path_ok):
            return await _send_json(send, 401, {"error": "unauthorized"})
        return await self.app(scope, receive, send)


mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")
app = NextPlanAuthMiddleware(mcp_app)
