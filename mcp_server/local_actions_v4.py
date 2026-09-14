from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .local_actions_v3 import execute_action as execute_action_v3
from .storage_v1 import CanonicalStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _event(kind: str, summary: str, **payload: Any) -> dict[str, Any]:
    return {
        "id": f"evt-local-{kind}-{uuid.uuid4().hex}",
        "at": _now_iso(),
        "type": kind,
        "summary": summary,
        "source": {"kind": "local", "via": "nextplan-local-core-v4"},
        **payload,
    }


def _project_exists(state: dict[str, Any], project_id: str) -> bool:
    return any(str(p.get("id") or "") == project_id for p in state.get("projects", []))


def _item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((x for x in items if str(x.get("id") or "") == item_id), None)


def _tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tags must be a list")
    return [str(x).strip() for x in value if str(x).strip()][:50]


def execute_action(store: CanonicalStore, action: dict[str, Any]) -> dict[str, Any]:
    op = str(action.get("action") or "").strip()
    supported = {
        "add_note", "update_note", "remove_note",
        "add_resource", "update_resource", "remove_resource",
        "upsert_automation_rule", "remove_automation_rule",
        "upsert_calendar_event", "remove_calendar_event",
    }
    if op not in supported:
        return execute_action_v3(store, action)

    state = store.get_state()

    if op == "add_note":
        title = str(action.get("title") or "").strip()
        if not title:
            raise ValueError("note title is required")
        pid = str(action.get("project_id") or "").strip()
        if pid and not _project_exists(state, pid):
            raise ValueError(f"Unknown project_id: {pid}")
        existing = next((n for n in state.get("notes", []) if str(n.get("title") or "").strip().casefold() == title.casefold() and str(n.get("project_id") or "") == pid), None)
        if existing:
            return {"status": "already_exists", "note_id": existing.get("id"), "title": existing.get("title")}
        nid = str(action.get("note_id") or "").strip() or f"note-{uuid.uuid4().hex[:12]}"
        note = {
            "id": nid,
            "title": title,
            "body": str(action.get("body") or "").strip(),
            "category": str(action.get("category") or "Note").strip() or "Note",
            "tags": _tags(action.get("tags")),
            "updated_at": _now_iso(),
        }
        if pid:
            note["project_id"] = pid
        result = store.append_event(_event("note_added", f"Saved note: {title}", project_id=pid or "system", note=note))
        return {"status": result["status"], "note_id": nid, "title": title, "event_id": result["event_id"]}

    if op == "update_note":
        nid = str(action.get("note_id") or "").strip()
        note = _item(state.get("notes", []), nid)
        if not note:
            raise ValueError(f"Unknown note_id: {nid}")
        changes: dict[str, Any] = {}
        for key in ("title", "body", "category", "project_id"):
            if key in action:
                value = str(action.get(key) or "").strip()
                if key == "title" and not value:
                    raise ValueError("note title cannot be empty")
                if key == "project_id" and value and not _project_exists(state, value):
                    raise ValueError(f"Unknown project_id: {value}")
                changes[key] = value
        if "tags" in action:
            changes["tags"] = _tags(action.get("tags"))
        if not changes:
            return {"status": "no_change", "note_id": nid}
        result = store.append_event(_event("note_updated", f"Updated note: {note.get('title', nid)}", project_id=str(note.get("project_id") or "system"), note_id=nid, changes=changes))
        return {"status": result["status"], "note_id": nid, "event_id": result["event_id"]}

    if op == "remove_note":
        nid = str(action.get("note_id") or "").strip()
        note = _item(state.get("notes", []), nid)
        if not note:
            return {"status": "already_absent", "note_id": nid}
        result = store.append_event(_event("note_removed", f"Removed note: {note.get('title', nid)}", project_id=str(note.get("project_id") or "system"), note_id=nid))
        return {"status": result["status"], "note_id": nid, "event_id": result["event_id"]}

    if op == "add_resource":
        title = str(action.get("title") or "").strip()
        location = str(action.get("location") or "").strip()
        if not title:
            raise ValueError("resource title is required")
        if not location:
            raise ValueError("resource location is required")
        pid = str(action.get("project_id") or "").strip()
        if pid and not _project_exists(state, pid):
            raise ValueError(f"Unknown project_id: {pid}")
        existing = next((r for r in state.get("resources", []) if str(r.get("location") or "") == location and str(r.get("project_id") or "") == pid), None)
        if existing:
            return {"status": "already_exists", "resource_id": existing.get("id"), "title": existing.get("title")}
        rid = str(action.get("resource_id") or "").strip() or f"resource-{uuid.uuid4().hex[:12]}"
        resource = {
            "id": rid,
            "title": title,
            "location": location,
            "type": str(action.get("resource_type") or action.get("type") or "link").strip() or "link",
            "description": str(action.get("description") or "").strip(),
            "tags": _tags(action.get("tags")),
            "updated_at": _now_iso(),
        }
        if pid:
            resource["project_id"] = pid
        result = store.append_event(_event("resource_added", f"Saved resource: {title}", project_id=pid or "system", resource=resource))
        return {"status": result["status"], "resource_id": rid, "title": title, "event_id": result["event_id"]}

    if op == "update_resource":
        rid = str(action.get("resource_id") or "").strip()
        resource = _item(state.get("resources", []), rid)
        if not resource:
            raise ValueError(f"Unknown resource_id: {rid}")
        changes: dict[str, Any] = {}
        mapping = {"title": "title", "location": "location", "description": "description", "resource_type": "type", "type": "type", "project_id": "project_id"}
        for incoming, target in mapping.items():
            if incoming in action:
                value = str(action.get(incoming) or "").strip()
                if target in {"title", "location"} and not value:
                    raise ValueError(f"resource {target} cannot be empty")
                if target == "project_id" and value and not _project_exists(state, value):
                    raise ValueError(f"Unknown project_id: {value}")
                changes[target] = value
        if "tags" in action:
            changes["tags"] = _tags(action.get("tags"))
        if not changes:
            return {"status": "no_change", "resource_id": rid}
        result = store.append_event(_event("resource_updated", f"Updated resource: {resource.get('title', rid)}", project_id=str(resource.get("project_id") or "system"), resource_id=rid, changes=changes))
        return {"status": result["status"], "resource_id": rid, "event_id": result["event_id"]}

    if op == "remove_resource":
        rid = str(action.get("resource_id") or "").strip()
        resource = _item(state.get("resources", []), rid)
        if not resource:
            return {"status": "already_absent", "resource_id": rid}
        result = store.append_event(_event("resource_removed", f"Removed resource: {resource.get('title', rid)}", project_id=str(resource.get("project_id") or "system"), resource_id=rid))
        return {"status": result["status"], "resource_id": rid, "event_id": result["event_id"]}

    if op == "upsert_automation_rule":
        rid = str(action.get("rule_id") or "").strip()
        if not rid:
            raise ValueError("rule_id is required")
        current = next((r for r in state.get("automation_rules", []) if str(r.get("id") or "") == rid), {})
        rule = dict(current)
        rule["id"] = rid
        if "enabled" in action:
            rule["enabled"] = bool(action.get("enabled"))
        else:
            rule.setdefault("enabled", True)
        if "threshold_days" in action:
            try:
                days = int(action.get("threshold_days"))
            except (TypeError, ValueError):
                raise ValueError("threshold_days must be an integer")
            if not 1 <= days <= 365:
                raise ValueError("threshold_days must be between 1 and 365")
            rule["threshold_days"] = days
        rule["updated_at"] = _now_iso()
        result = store.append_event(_event("automation_rule_upserted", f"Updated automation rule: {rid}", automation_rule=rule))
        return {"status": result["status"], "rule_id": rid, "rule": rule, "event_id": result["event_id"]}

    if op == "remove_automation_rule":
        rid = str(action.get("rule_id") or "").strip()
        if not rid:
            raise ValueError("rule_id is required")
        if not any(str(r.get("id") or "") == rid for r in state.get("automation_rules", [])):
            return {"status": "already_absent", "rule_id": rid}
        result = store.append_event(_event("automation_rule_removed", f"Removed automation rule: {rid}", automation_rule_id=rid))
        return {"status": result["status"], "rule_id": rid, "event_id": result["event_id"]}

    if op == "upsert_calendar_event":
        title = str(action.get("title") or "").strip()
        date = str(action.get("date") or "").strip()
        if not title or not date:
            raise ValueError("calendar event title and date are required")
        pid = str(action.get("project_id") or "").strip()
        if pid and not _project_exists(state, pid):
            raise ValueError(f"Unknown project_id: {pid}")
        existing = next((c for c in state.get("calendar_events", []) if str(c.get("project_id") or "") == pid and str(c.get("title") or "") == title and str(c.get("date") or "") == date and str(c.get("time") or "") == str(action.get("time") or "") and str(c.get("kind") or "event") == str(action.get("kind") or "event")), None)
        cid = str(action.get("calendar_event_id") or action.get("id") or "").strip() or str((existing or {}).get("id") or "") or f"calendar-{uuid.uuid4().hex[:12]}"
        event = {
            "id": cid,
            "title": title,
            "date": date,
            "time": str(action.get("time") or "").strip(),
            "kind": str(action.get("kind") or "event").strip() or "event",
            "category": str(action.get("category") or "其他").strip() or "其他",
            "timezone": str(action.get("timezone") or "").strip(),
        }
        if pid:
            event["project_id"] = pid
        result = store.append_event(_event("calendar_event_upserted", f"Saved calendar event: {title}", project_id=pid or "system", calendar_event=event))
        return {"status": result["status"], "calendar_event_id": cid, "calendar_event": event, "event_id": result["event_id"]}

    if op == "remove_calendar_event":
        cid = str(action.get("calendar_event_id") or "").strip()
        event = _item(state.get("calendar_events", []), cid)
        if not event:
            return {"status": "already_absent", "calendar_event_id": cid}
        result = store.append_event(_event("calendar_event_removed", f"Removed calendar event: {event.get('title', cid)}", project_id=str(event.get("project_id") or "system"), calendar_event_id=cid))
        return {"status": result["status"], "calendar_event_id": cid, "event_id": result["event_id"]}

    raise ValueError(f"unsupported local action: {op}")
