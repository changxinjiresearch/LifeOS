#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import build_state as legacy  # noqa: E402

AUTOMATION_TYPES = {
    "automation_rule_upserted",
    "automation_rule_removed",
    "automation_snapshot_refreshed",
}


def _upsert_rule(state, rule):
    items = state.setdefault("automation_rules", [])
    rid = rule.get("id")
    if not rid:
        raise ValueError("automation_rule requires id")
    cur = next((x for x in items if x.get("id") == rid), None)
    if cur:
        cur.update(rule)
    else:
        items.append(rule)


def _apply_automation_event(state, event):
    et = event["type"]
    if et == "automation_rule_upserted":
        _upsert_rule(state, deepcopy(event.get("automation_rule") or {}))
    elif et == "automation_rule_removed":
        rid = str(event.get("automation_rule_id") or "")
        state["automation_rules"] = [x for x in state.setdefault("automation_rules", []) if str(x.get("id")) != rid]
    elif et == "automation_snapshot_refreshed":
        snap = deepcopy(event.get("automation_snapshot") or {})
        state["automation_feed"] = deepcopy(snap.get("findings") or [])
        state["automation_meta"] = {
            "last_run_at": snap.get("generated_at") or event.get("at"),
            "finding_count": int(snap.get("finding_count") or len(state["automation_feed"])),
            "automation_version": snap.get("automation_version") or "1.0",
        }
    legacy.append_history(state, event)


def main():
    state = legacy.load_json(legacy.STATE_PATH)
    state.setdefault("automation_rules", [])
    state.setdefault("automation_feed", [])
    state.setdefault("automation_meta", {})
    layer = state.setdefault("system", {}).setdefault("event_layer", {
        "version": 1,
        "mode": "append-only-event-files",
        "inbox": "events/inbox",
        "builder": "engine/build_state_v2.py",
        "processed_event_ids": [],
    })
    processed = set(layer.setdefault("processed_event_ids", []))
    paths = sorted(legacy.EVENT_DIR.glob("*.json")) if legacy.EVENT_DIR.exists() else []
    applied = []
    for path in paths:
        event = legacy.load_json(path)
        eid = legacy.require(event, "id", str)
        if eid in processed or event.get("type") not in AUTOMATION_TYPES:
            continue
        legacy.require(event, "at", str)
        _apply_automation_event(state, event)
        processed.add(eid)
        applied.append(eid)
    if applied:
        layer["processed_event_ids"] = sorted(processed)
        layer["processed_count"] = len(processed)
        layer["last_applied"] = applied
        layer["builder"] = "engine/build_state_v2.py"
        legacy.save_json(legacy.STATE_PATH, state)
    legacy.main()
    # legacy.main may preserve the old builder label; normalize it after the full pass.
    final = legacy.load_json(legacy.STATE_PATH)
    final.setdefault("automation_rules", [])
    final.setdefault("automation_feed", [])
    final.setdefault("automation_meta", {})
    final.setdefault("system", {}).setdefault("event_layer", {})["builder"] = "engine/build_state_v2.py"
    legacy.save_json(legacy.STATE_PATH, final)


if __name__ == "__main__":
    main()
