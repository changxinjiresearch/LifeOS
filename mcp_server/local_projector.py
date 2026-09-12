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
            },
        },
        "projects": [],
        "events": [],
    })


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Apply one canonical event without any GitHub/file-system side effects.

    This deliberately reuses the proven Stage I-III pure projectors. The local
    store owns transactionality/idempotency; this function only projects state.
    """
    working = ensure_local_defaults(deepcopy(state))
    eid = legacy.require(event, "id", str)
    legacy.require(event, "at", str)
    et = legacy.require(event, "type", str)

    processed = set(working["system"]["event_layer"].setdefault("processed_event_ids", []))
    if eid in processed:
        return working

    if et in v3.AGENT_TYPES:
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
    """Return stable canonical semantics for GitHub -> SQLite parity checks."""
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
