#!/usr/bin/env python3
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
EVENT_DIR = ROOT / "events" / "inbox"
ALLOWED_STATUS = {"active", "waiting", "planned", "completed", "done", "blocked"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def require(obj, key, typ=None):
    if key not in obj:
        raise ValueError(f"missing required field: {key}")
    val = obj[key]
    if typ is not None and not isinstance(val, typ):
        raise ValueError(f"field {key} must be {typ.__name__}")
    return val


def find_project(state, project_id):
    for p in state.setdefault("projects", []):
        if p.get("id") == project_id:
            return p
    raise ValueError(f"unknown project_id: {project_id}")


def find_milestone(project, milestone_id):
    for m in project.setdefault("milestones", []):
        if m.get("id") == milestone_id:
            return m
    raise ValueError(f"unknown milestone_id {milestone_id} in {project.get('id')}")


def set_status(obj, status):
    if status not in ALLOWED_STATUS:
        raise ValueError(f"invalid status: {status}")
    obj["status"] = status


def append_history(state, event):
    history = state.setdefault("events", [])
    eid = event["id"]
    if any(x.get("id") == eid for x in history):
        return
    history.insert(0, {
        "id": eid,
        "at": event["at"],
        "project_id": event.get("project_id", "system"),
        "type": event["type"],
        "summary": event.get("summary") or event.get("title") or event["type"],
        "source": event.get("source", {"kind": "chatgpt"}),
    })


def upsert_deadline(state, d):
    deadlines = state.setdefault("deadlines", [])
    did = d.get("id")
    key = (d.get("project_id"), d.get("task_id"), d.get("title") or d.get("name"), d.get("date") or d.get("due"))
    for cur in deadlines:
        cur_key = (cur.get("project_id"), cur.get("task_id"), cur.get("title") or cur.get("name"), cur.get("date") or cur.get("due"))
        if (did and cur.get("id") == did) or cur_key == key:
            cur.update(d)
            return
    deadlines.append(d)


def upsert_calendar_event(state, obj):
    items = state.setdefault("calendar_events", [])
    oid = obj.get("id")
    key = (obj.get("project_id"), obj.get("title"), obj.get("date"), obj.get("time"), obj.get("kind"))
    for cur in items:
        cur_key = (cur.get("project_id"), cur.get("title"), cur.get("date"), cur.get("time"), cur.get("kind"))
        if (oid and cur.get("id") == oid) or cur_key == key:
            cur.update(obj)
            return
    items.append(obj)


def upsert_named(items, obj, *, id_key="id", name_keys=("title", "name")):
    oid = obj.get(id_key)
    for cur in items:
        if oid and cur.get(id_key) == oid:
            cur.update(obj)
            return
    for nk in name_keys:
        if obj.get(nk):
            for cur in items:
                if cur.get(nk) == obj.get(nk):
                    cur.update(obj)
                    return
    items.append(obj)


def auto_advance_project(project, completed_id):
    milestones = project.setdefault("milestones", [])
    if any(m.get("status") == "active" for m in milestones):
        project["status"] = "active"
        active = next((m for m in milestones if m.get("status") == "active"), None)
        if active:
            project["next_action"] = active.get("name", project.get("next_action", ""))
        return
    planned = [m for m in milestones if m.get("status") == "planned"]
    if planned:
        completed_index = next((i for i, m in enumerate(milestones) if m.get("id") == completed_id), -1)
        next_item = next((m for i, m in enumerate(milestones) if i > completed_index and m.get("status") == "planned"), planned[0])
        next_item["status"] = "active"
        project["status"] = "active"
        project["next_action"] = next_item.get("name", "")
        return
    if milestones and all(m.get("status") in {"completed", "done"} for m in milestones):
        project["status"] = "completed"
        project["next_action"] = "项目已完成"
        return
    if any(m.get("status") == "blocked" for m in milestones):
        project["status"] = "blocked"
    elif any(m.get("status") == "waiting" for m in milestones):
        project["status"] = "waiting"


def apply_event(state, event):
    require(event, "id", str)
    require(event, "at", str)
    et = require(event, "type", str)

    if et == "event_only":
        pass

    elif et == "project_created":
        project = deepcopy(require(event, "project", dict))
        require(project, "id", str)
        require(project, "name", str)
        existing = next((p for p in state.setdefault("projects", []) if p.get("id") == project["id"]), None)
        if existing:
            existing.update(project)
        else:
            project.setdefault("category", "行政")
            project.setdefault("status", "active")
            project.setdefault("priority", 2)
            project.setdefault("next_action", "")
            project.setdefault("milestones", [])
            state["projects"].append(project)

    elif et == "project_updated":
        p = find_project(state, require(event, "project_id", str))
        changes = deepcopy(require(event, "changes", dict))
        changes.pop("id", None)
        if "status" in changes:
            set_status(p, changes.pop("status"))
        p.update(changes)

    elif et == "project_status_changed":
        p = find_project(state, require(event, "project_id", str))
        set_status(p, require(event, "status", str))
        if "next_action" in event:
            p["next_action"] = event["next_action"]

    elif et == "project_deleted":
        project_id = require(event, "project_id", str)
        if not any(p.get("id") == project_id for p in state.setdefault("projects", [])):
            raise ValueError(f"unknown project_id: {project_id}")
        state["projects"] = [p for p in state["projects"] if p.get("id") != project_id]
        state["deadlines"] = [d for d in state.setdefault("deadlines", []) if d.get("project_id") != project_id]
        state["calendar_events"] = [d for d in state.setdefault("calendar_events", []) if d.get("project_id") != project_id]

    elif et in {"milestone_added", "task_created"}:
        p = find_project(state, require(event, "project_id", str))
        m = deepcopy(event.get("milestone") or event.get("task") or {})
        require(m, "id", str)
        require(m, "name", str)
        m.setdefault("status", "active")
        existing = next((x for x in p.setdefault("milestones", []) if x.get("id") == m["id"]), None)
        if existing is None:
            norm = m["name"].strip().casefold()
            existing = next((x for x in p["milestones"] if str(x.get("name", "")).strip().casefold() == norm), None)
        if existing:
            existing.update(m)
        else:
            p["milestones"].append(m)
        if event.get("activate_project", True) and p.get("status") in {"planned", "waiting", "blocked"}:
            p["status"] = "active"
        if "next_action" in event:
            p["next_action"] = event["next_action"]
        elif m.get("status") == "active":
            p["next_action"] = m.get("name", p.get("next_action", ""))

    elif et in {"milestone_status_changed", "task_updated", "task_completed"}:
        p = find_project(state, require(event, "project_id", str))
        mid = event.get("milestone_id") or event.get("task_id")
        if not isinstance(mid, str):
            raise ValueError("milestone_id/task_id is required")
        m = find_milestone(p, mid)
        status = "completed" if et == "task_completed" else require(event, "status", str)
        set_status(m, status)
        if "name" in event:
            m["name"] = event["name"]
        if "deadline" in event:
            m["deadline"] = event["deadline"]
        if "prep_days" in event:
            m["prep_days"] = event["prep_days"]
        if "last_worked_at" in event:
            m["last_worked_at"] = event["last_worked_at"]
        if "next_action" in event:
            p["next_action"] = event["next_action"]
        if "project_status" in event:
            set_status(p, event["project_status"])
        elif status == "active":
            p["status"] = "active"
            p["next_action"] = m.get("name", p.get("next_action", ""))
        elif status == "completed" and event.get("auto_advance", True):
            auto_advance_project(p, mid)

    elif et == "task_deleted":
        p = find_project(state, require(event, "project_id", str))
        task_id = require(event, "task_id", str)
        if not any(m.get("id") == task_id for m in p.setdefault("milestones", [])):
            raise ValueError(f"unknown task_id {task_id} in {p.get('id')}")
        p["milestones"] = [m for m in p["milestones"] if m.get("id") != task_id]

    elif et == "deadline_set":
        d = deepcopy(require(event, "deadline", dict))
        if not (d.get("date") or d.get("due")):
            raise ValueError("deadline requires date/due")
        upsert_deadline(state, d)

    elif et == "deadline_removed":
        did = require(event, "deadline_id", str)
        state["deadlines"] = [d for d in state.setdefault("deadlines", []) if d.get("id") != did]

    elif et == "calendar_event_upserted":
        c = deepcopy(require(event, "calendar_event", dict))
        require(c, "id", str)
        require(c, "title", str)
        require(c, "date", str)
        c.setdefault("kind", "event")
        upsert_calendar_event(state, c)

    elif et == "calendar_event_removed":
        cid = require(event, "calendar_event_id", str)
        state["calendar_events"] = [c for c in state.setdefault("calendar_events", []) if c.get("id") != cid]

    elif et == "note_added":
        note = deepcopy(require(event, "note", dict))
        note.setdefault("at", event["at"])
        upsert_named(state.setdefault("notes", []), note)

    elif et == "resource_added":
        resource = deepcopy(require(event, "resource", dict))
        upsert_named(state.setdefault("resources", []), resource)

    else:
        raise ValueError(f"unsupported event type: {et}")

    append_history(state, event)


def main():
    state = load_json(STATE_PATH)
    state.setdefault("deadlines", [])
    state.setdefault("calendar_events", [])
    state.setdefault("notes", [])
    state.setdefault("resources", [])
    system = state.setdefault("system", {})
    layer = system.setdefault("event_layer", {
        "version": 1,
        "mode": "append-only-event-files",
        "inbox": "events/inbox",
        "builder": "engine/build_state.py",
        "processed_event_ids": [],
    })
    processed = set(layer.setdefault("processed_event_ids", []))

    paths = sorted(EVENT_DIR.glob("*.json")) if EVENT_DIR.exists() else []
    applied, errors = [], []
    for path in paths:
        try:
            event = load_json(path)
            eid = require(event, "id", str)
            if eid in processed:
                continue
            apply_event(state, event)
            processed.add(eid)
            applied.append(eid)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    if errors:
        raise SystemExit("NextPlan event build failed:\n" + "\n".join(errors))

    layer["processed_event_ids"] = sorted(processed)
    layer["processed_count"] = len(processed)
    layer["last_build_at"] = now_iso()
    layer["last_applied"] = applied
    layer["status"] = "ready"
    system["architecture"] = "conversation-event-layer-central-state"
    rules = system.setdefault("rules", {})
    rules.update({
        "assistant_writes_confirmed_state_changes": True,
        "discussion_does_not_change_status": True,
        "planning_does_not_equal_completion": True,
        "completion_requires_confirmed_evidence": True,
        "waiting_items_are_not_actionable": True,
        "event_ids_are_idempotent": True,
        "event_files_are_append_only": True,
    })
    system["last_updated"] = max(
        [x for x in [state.get("events", [{}])[0].get("at") if state.get("events") else None] if x]
        or [system.get("last_updated") or now_iso()]
    )
    save_json(STATE_PATH, state)
    print(json.dumps({"applied": applied, "processed_count": len(processed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
