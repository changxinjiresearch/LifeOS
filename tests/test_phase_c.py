from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from engine.build_state import apply_event
from mcp_server.phase_c_engine import analytics_snapshot, unified_search, weekly_review
from mcp_server.cloud_classifier_v4 import classify_turn


def base_state():
    return {
        "schema_version": 2,
        "system": {},
        "projects": [
            {
                "id": "p1",
                "name": "Research Project",
                "category": "科研",
                "status": "active",
                "priority": 3,
                "next_action": "Run experiment",
                "milestones": [
                    {"id": "m1", "name": "Run experiment", "status": "active"},
                    {"id": "m2", "name": "Write paper", "status": "planned"},
                ],
            },
            {
                "id": "p2",
                "name": "Waiting Paper",
                "category": "科研",
                "status": "waiting",
                "priority": 3,
                "next_action": "Wait for editor",
                "milestones": [{"id": "w1", "name": "Decision", "status": "waiting"}],
            },
        ],
        "deadlines": [{"id": "d1", "title": "Submission", "date": "2026-09-15", "project_id": "p1"}],
        "calendar_events": [{"id": "c1", "title": "Supervisor meeting", "date": "2026-09-16", "time": "16:30", "kind": "meeting", "project_id": "p1"}],
        "notes": [{"id": "n1", "title": "Pathology idea", "body": "Use spatial validation", "project_id": "p1"}],
        "resources": [{"id": "r1", "title": "Repository", "location": "https://example.com/repo", "project_id": "p1", "type": "link"}],
        "events": [
            {"id": "e1", "at": "2026-09-11T06:00:00Z", "type": "task_completed", "project_id": "p1", "summary": "Completed task: setup"},
            {"id": "e2", "at": "2026-08-30T06:00:00Z", "type": "project_updated", "project_id": "p2", "summary": "Waiting for editor"},
        ],
    }


def test_weekly_review_has_movement_waiting_and_upcoming():
    s = base_state()
    out = weekly_review(s, datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc))
    assert out["movement"]["completion_events"] == 1
    assert out["status"]["waiting"] == 1
    assert any(x["title"] == "Submission" for x in out["upcoming_14_days"])
    assert any(x["title"] == "Supervisor meeting" for x in out["upcoming_14_days"])


def test_analytics_snapshot_core_metrics():
    s = base_state()
    out = analytics_snapshot(s, datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc))
    assert out["projects"]["total"] == 2
    assert out["projects"]["status"]["active"] == 1
    assert out["projects"]["status"]["waiting"] == 1
    assert out["movement"]["events_7_days"] == 1
    assert out["time"]["upcoming_14_days"] == 2
    assert out["notes"] == 1 and out["resources"] == 1


def test_unified_search_covers_notes_resources_calendar_and_filters():
    s = base_state()
    assert any(x["kind"] == "note" for x in unified_search(s, "Pathology"))
    assert any(x["kind"] == "resource" for x in unified_search(s, "Repository"))
    assert any(x["kind"] == "calendar" for x in unified_search(s, "Supervisor"))
    only_waiting = unified_search(s, "status:waiting")
    assert only_waiting and all(x["status"] == "waiting" for x in only_waiting)
    project_results = unified_search(s, "project:Research")
    assert any(x["project_id"] == "p1" for x in project_results)


def test_note_resource_lifecycle_in_builder():
    s = base_state()
    add = {"id": "e3", "at": "2026-09-12T06:10:00Z", "type": "note_added", "project_id": "p1", "summary": "add", "note": {"id": "n2", "title": "New note", "body": "Body", "project_id": "p1"}}
    apply_event(s, add)
    assert any(n["id"] == "n2" for n in s["notes"])
    apply_event(s, {"id": "e4", "at": "2026-09-12T06:11:00Z", "type": "note_updated", "project_id": "p1", "summary": "update", "note_id": "n2", "changes": {"body": "Updated"}})
    assert next(n for n in s["notes"] if n["id"] == "n2")["body"] == "Updated"
    apply_event(s, {"id": "e5", "at": "2026-09-12T06:12:00Z", "type": "note_removed", "project_id": "p1", "summary": "remove", "note_id": "n2"})
    assert not any(n["id"] == "n2" for n in s["notes"])

    apply_event(s, {"id": "e6", "at": "2026-09-12T06:13:00Z", "type": "resource_added", "project_id": "p1", "summary": "add resource", "resource": {"id": "r2", "title": "Paper", "location": "https://example.com/paper", "project_id": "p1"}})
    apply_event(s, {"id": "e7", "at": "2026-09-12T06:14:00Z", "type": "resource_updated", "project_id": "p1", "summary": "update resource", "resource_id": "r2", "changes": {"description": "Important"}})
    assert next(r for r in s["resources"] if r["id"] == "r2")["description"] == "Important"
    apply_event(s, {"id": "e8", "at": "2026-09-12T06:15:00Z", "type": "resource_removed", "project_id": "p1", "summary": "remove resource", "resource_id": "r2"})
    assert not any(r["id"] == "r2" for r in s["resources"])


def test_classifier_explicit_note_and_resource():
    s = base_state()
    note = classify_turn({"userText": "NextPlan：把这个想法记下来作为笔记：以后验证 pathology grounding"}, s, {})
    assert note and note["action"]["action"] == "add_note"
    resource = classify_turn({"userText": "NextPlan：把 https://example.com/paper 保存为资源"}, s, {})
    assert resource and resource["action"]["action"] == "add_resource"
    assert resource["action"]["location"] == "https://example.com/paper"


def test_state_schema_accepts_phase_c_fields():
    schema = json.loads(Path("state.schema.json").read_text(encoding="utf-8"))
    assert "project_id" in schema["$defs"]["note"]["properties"]
    assert "tags" in schema["$defs"]["note"]["properties"]
    assert "project_id" in schema["$defs"]["resource"]["properties"]
