#!/usr/bin/env python3
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import build_state as legacy  # noqa: E402
from engine import build_state_v2 as v2  # noqa: E402


AGENT_TYPES = {
    "agent_policy_upserted",
    "agent_policy_removed",
    "external_signal_recorded",
    "agent_action_recorded",
    "agent_reconciliation_recorded",
    "agent_run_recorded",
}


def _upsert_by_id(items, item):
    iid = str(item.get("id") or "")
    if not iid:
        raise ValueError("agent item requires id")
    current = next((x for x in items if str(x.get("id")) == iid), None)
    if current:
        current.update(item)
    else:
        items.append(item)


def _apply_agent_event(state, event):
    et = event["type"]
    if et == "agent_policy_upserted":
        _upsert_by_id(state.setdefault("agent_policies", []), deepcopy(event.get("agent_policy") or {}))
    elif et == "agent_policy_removed":
        pid = str(event.get("agent_policy_id") or "")
        state["agent_policies"] = [x for x in state.setdefault("agent_policies", []) if str(x.get("id")) != pid]
    elif et == "external_signal_recorded":
        signal = deepcopy(event.get("external_signal") or {})
        _upsert_by_id(state.setdefault("external_signals", []), signal)
        state["external_signals"] = state["external_signals"][-200:]
        meta = state.setdefault("agent_meta", {})
        meta["last_signal_at"] = signal.get("received_at") or event.get("at")
        if str(signal.get("provider") or "") == "github" and str(signal.get("event_type") or "") == "repo_head_changed":
            payload = signal.get("payload") or {}
            repo = str(payload.get("repository") or "")
            sha = str(payload.get("head_sha") or "")
            if repo and sha:
                meta.setdefault("provider_cursors", {})[f"github:{repo}:head"] = sha
    elif et == "agent_action_recorded":
        receipt = deepcopy(event.get("agent_action") or {})
        _upsert_by_id(state.setdefault("agent_actions", []), receipt)
        state["agent_actions"] = state["agent_actions"][-200:]
        state.setdefault("agent_meta", {})["last_action_at"] = receipt.get("at") or event.get("at")
    elif et == "agent_reconciliation_recorded":
        reconciliation = deepcopy(event.get("agent_reconciliation") or {})
        _upsert_by_id(state.setdefault("agent_reconciliations", []), reconciliation)
        state["agent_reconciliations"] = state["agent_reconciliations"][-200:]
        state.setdefault("agent_meta", {})["last_reconciliation_at"] = reconciliation.get("at") or event.get("at")
    elif et == "agent_run_recorded":
        run = deepcopy(event.get("agent_run") or {})
        _upsert_by_id(state.setdefault("agent_runs", []), run)
        state["agent_runs"] = state["agent_runs"][-100:]
        state.setdefault("agent_meta", {})["last_run_at"] = run.get("at") or event.get("at")
    legacy.append_history(state, event)


def _defaults(state):
    state.setdefault("agent_policies", [])
    state.setdefault("external_signals", [])
    state.setdefault("agent_actions", [])
    state.setdefault("agent_reconciliations", [])
    state.setdefault("agent_runs", [])
    meta = state.setdefault("agent_meta", {})
    meta.setdefault("agent_version", "1.0")
    meta.setdefault("provider_cursors", {})


def main():
    state = legacy.load_json(legacy.STATE_PATH)
    _defaults(state)
    layer = state.setdefault("system", {}).setdefault("event_layer", {
        "version": 1,
        "mode": "append-only-event-files",
        "inbox": "events/inbox",
        "builder": "engine/build_state_v3.py",
        "processed_event_ids": [],
    })
    processed = set(layer.setdefault("processed_event_ids", []))
    paths = sorted(legacy.EVENT_DIR.glob("*.json")) if legacy.EVENT_DIR.exists() else []
    applied = []
    for path in paths:
        event = legacy.load_json(path)
        eid = legacy.require(event, "id", str)
        if eid in processed or event.get("type") not in AGENT_TYPES:
            continue
        legacy.require(event, "at", str)
        _apply_agent_event(state, event)
        processed.add(eid)
        applied.append(eid)
    if applied:
        layer["processed_event_ids"] = sorted(processed)
        layer["processed_count"] = len(processed)
        layer["last_applied"] = applied
        layer["builder"] = "engine/build_state_v3.py"
        legacy.save_json(legacy.STATE_PATH, state)

    v2.main()

    final = legacy.load_json(legacy.STATE_PATH)
    _defaults(final)
    final.setdefault("system", {}).setdefault("event_layer", {})["builder"] = "engine/build_state_v3.py"
    legacy.save_json(legacy.STATE_PATH, final)


if __name__ == "__main__":
    main()
