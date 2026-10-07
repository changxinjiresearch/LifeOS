from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from engine import build_state as legacy
from engine import build_state_v2 as v2
from engine import build_state_v3 as v3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_local_defaults(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("projects", [])
    state.setdefault("deadlines", [])
    state.setdefault("calendar_events", [])
    state.setdefault("notes", [])
    state.setdefault("resources", [])
    state.setdefault("automation_rules", [])
    state.setdefault("automation_feed", [])
    state.setdefault("automation_meta", {})
    state.setdefault("agent_policies", [])
    state.setdefault("external_signals", [])
    state.setdefault("agent_actions", [])
    state.setdefault("agent_reconciliations", [])
    state.setdefault("agent_runs", [])
    state.setdefault("agent_meta", {}).setdefault("provider_cursors", {})
    # Stage V Local v0.1 runtime state. These remain event-projected and local-only.
    state.setdefault("workspace_bindings", [])
    state.setdefault("artifacts", [])
    state.setdefault("local_execution_receipts", [])
    state.setdefault("local_permissions", {"mode": "balanced"})
    system = state.setdefault("system", {})
    system.setdefault("name", "NextPlan")
    system["architecture"] = "local-conversation-event-layer-central-state"
    system["canonical_store"] = "sqlite-local"
    layer = system.setdefault("event_layer", {})
    layer["version"] = 1
    layer["mode"] = "sqlite-append-only-events"
    layer["builder"] = "mcp_server/local_projector.py"
    layer.setdefault("processed_event_ids", [])
    layer["processed_count"] = len(layer["processed_event_ids"])
    layer.setdefault("status", "ready")
    return state


def new_local_state() -> dict[str, Any]:
    return ensure_local_defaults({
        "system": {
            "name": "NextPlan",
            "last_updated": _now_iso(),
            "rules": {
                "discussion_does_not_change_status": True,
                "planning_does_not_equal_completion": True,
                "completion_requires_confirmed_evidence": True,
                "waiting_items_are_not_actionable": True,
                "event_ids_are_idempotent": True,
                "assistant_statement_is_not_fact_authority": True,
                "local_shell_is_not_exposed": True,
                "workspace_access_requires_explicit_binding": True,
            },
        },
        "projects": [],
        "events": [],
    })


def _replace_by_id(items: list[dict[str, Any]], value: dict[str, Any], key: str = "id") -> None:
    target = str(value.get(key) or "")
    for idx, item in enumerate(items):
        if str(item.get(key) or "") == target:
            items[idx] = deepcopy(value)
            return
    items.append(deepcopy(value))


def _apply_local_runtime_event(state: dict[str, Any], event: dict[str, Any]) -> bool:
    et = str(event.get("type") or "")
    if et == "workspace_bound":
        binding = deepcopy(event.get("binding") or {})
        pid = str(binding.get("project_id") or event.get("project_id") or "")
        if not pid:
            raise ValueError("workspace_bound requires project_id")
        binding["project_id"] = pid
        _replace_by_id(state["workspace_bindings"], binding, key="project_id")
        return True
    if et == "workspace_unbound":
        pid = str(event.get("project_id") or "")
        state["workspace_bindings"] = [x for x in state["workspace_bindings"] if str(x.get("project_id") or "") != pid]
        return True
    if et == "artifact_attached":
        artifact = deepcopy(event.get("artifact") or {})
        if not artifact.get("id"):
            raise ValueError("artifact_attached requires artifact.id")
        _replace_by_id(state["artifacts"], artifact)
        return True
    if et == "artifact_verified":
        aid = str(event.get("artifact_id") or "")
        changes = deepcopy(event.get("changes") or {})
        for artifact in state["artifacts"]:
            if str(artifact.get("id") or "") == aid:
                artifact.update(changes)
                break
        return True
    if et == "artifact_removed":
        aid = str(event.get("artifact_id") or "")
        state["artifacts"] = [x for x in state["artifacts"] if str(x.get("id") or "") != aid]
        return True
    if et == "local_execution_recorded":
        receipt = deepcopy(event.get("receipt") or {})
        if receipt:
            state["local_execution_receipts"].append(receipt)
            state["local_execution_receipts"] = state["local_execution_receipts"][-1000:]
        return True
    if et == "local_permission_updated":
        changes = event.get("changes") or {}
        if isinstance(changes, dict):
            state["local_permissions"].update(deepcopy(changes))
        return True
    if et == "project_status_batch_updated":
        updates = event.get("updates") or []
        if not isinstance(updates, list) or not updates:
            raise ValueError("project_status_batch_updated requires updates")
        projects = {str(p.get("id") or ""): p for p in state.get("projects", [])}
        for update in updates:
            if not isinstance(update, dict):
                raise ValueError("project_status_batch_updated update must be an object")
            pid = str(update.get("project_id") or "")
            status = str(update.get("status") or "")
            if not pid or pid not in projects:
                raise ValueError(f"Unknown project_id: {pid}")
            if status not in {"active", "waiting", "planned", "completed", "done", "blocked"}:
                raise ValueError(f"invalid status: {status}")
        for update in updates:
            project = projects[str(update["project_id"])]
            project["status"] = str(update["status"])
        return True
    return False


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Apply one canonical event without GitHub or external service side effects."""
    working = ensure_local_defaults(deepcopy(state))
    eid = legacy.require(event, "id", str)
    legacy.require(event, "at", str)
    et = legacy.require(event, "type", str)

    processed = set(working["system"]["event_layer"].setdefault("processed_event_ids", []))
    if eid in processed:
        return working

    if _apply_local_runtime_event(working, event):
        pass
    elif et in v3.AGENT_TYPES:
        v3._apply_agent_event(working, event)
    elif et in v2.AUTOMATION_TYPES:
        v2._apply_automation_event(working, event)
    else:
        legacy.apply_event(working, event)

    processed.add(eid)
    layer = working["system"]["event_layer"]
    layer["processed_event_ids"] = sorted(processed)
    layer["processed_count"] = len(processed)
    layer["last_applied"] = [eid]
    layer["last_build_at"] = event.get("at") or _now_iso()
    layer["status"] = "ready"
    layer["mode"] = "sqlite-append-only-events"
    layer["builder"] = "mcp_server/local_projector.py"
    working["system"]["architecture"] = "local-conversation-event-layer-central-state"
    working["system"]["canonical_store"] = "sqlite-local"
    working["system"]["last_updated"] = event.get("at") or _now_iso()
    return working


def semantic_projection(state: dict[str, Any]) -> dict[str, Any]:
    """Return stable pre-Local-v0.1 semantics for GitHub -> SQLite parity checks."""
    keys = (
        "projects",
        "deadlines",
        "calendar_events",
        "notes",
        "resources",
        "automation_rules",
        "automation_feed",
        "agent_policies",
        "external_signals",
        "agent_actions",
        "agent_reconciliations",
        "agent_runs",
    )
    return {key: deepcopy(state.get(key, [])) for key in keys}
