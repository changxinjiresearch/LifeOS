from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from engine.build_state import apply_event
from mcp_server.cloud_classifier_v3 import classify_turn
from mcp_server.decision_engine import candidates, recommend


def base_state():
    return {
        "schema_version": 2,
        "system": {},
        "projects": [
            {
                "id": "a",
                "name": "High Far",
                "category": "科研",
                "status": "active",
                "priority": 3,
                "next_action": "Do high far work",
                "milestones": [{"id": "a1", "name": "A1", "status": "active"}],
            },
            {
                "id": "b",
                "name": "Presentation Project",
                "category": "课程",
                "status": "active",
                "priority": 2,
                "next_action": "Prepare presentation",
                "milestones": [{"id": "b1", "name": "Prepare slides", "status": "active"}],
            },
            {
                "id": "w",
                "name": "Waiting Paper",
                "category": "科研",
                "status": "waiting",
                "priority": 3,
                "next_action": "Wait for editor",
                "milestones": [{"id": "w1", "name": "Editorial decision", "status": "waiting"}],
            },
        ],
        "deadlines": [{"id": "db", "title": "Presentation deadline", "date": "2026-09-14", "project_id": "b"}],
        "calendar_events": [],
        "events": [],
    }


def test_workflow_auto_advances_next_planned_item():
    state = {
        "projects": [{
            "id": "p", "name": "P", "category": "X", "status": "active", "priority": 2,
            "next_action": "Step 1",
            "milestones": [
                {"id": "s1", "name": "Step 1", "status": "active"},
                {"id": "s2", "name": "Step 2", "status": "planned"},
            ],
        }],
        "deadlines": [], "calendar_events": [], "events": [],
    }
    apply_event(state, {"id": "evt-test-1", "at": "2026-09-12T00:00:00Z", "type": "task_completed", "project_id": "p", "task_id": "s1"})
    p = state["projects"][0]
    assert p["milestones"][0]["status"] == "completed"
    assert p["milestones"][1]["status"] == "active"
    assert p["next_action"] == "Step 2"
    assert p["status"] == "active"


def test_workflow_completes_project_when_last_item_finishes():
    state = {
        "projects": [{
            "id": "p", "name": "P", "category": "X", "status": "active", "priority": 2,
            "next_action": "Only step", "milestones": [{"id": "s1", "name": "Only step", "status": "active"}],
        }],
        "deadlines": [], "calendar_events": [], "events": [],
    }
    apply_event(state, {"id": "evt-test-2", "at": "2026-09-12T00:00:00Z", "type": "task_completed", "project_id": "p", "task_id": "s1"})
    assert state["projects"][0]["status"] == "completed"


def test_calendar_event_has_separate_collection():
    state = {"projects": [], "deadlines": [], "calendar_events": [], "events": []}
    apply_event(state, {
        "id": "evt-cal-1", "at": "2026-09-12T00:00:00Z", "type": "calendar_event_upserted",
        "calendar_event": {"id": "c1", "title": "Meeting", "date": "2026-09-16", "time": "16:30", "kind": "meeting"},
    })
    assert state["calendar_events"][0]["kind"] == "meeting"
    assert state["deadlines"] == []


def test_decision_engine_excludes_waiting_and_deadline_can_override_priority():
    state = base_state()
    now = datetime.fromisoformat("2026-09-12T12:00:00+09:30")
    cs = candidates(state, now)
    assert all(x["project_id"] != "w" for x in cs)
    rec = recommend(state, now, seed=1)
    assert rec is not None
    assert rec["project_id"] == "b"
    assert rec["deadline_days"] == 2


def test_pick_something_else_excludes_current_key():
    state = base_state()
    now = datetime.fromisoformat("2026-09-12T12:00:00+09:30")
    first = recommend(state, now, seed=1)
    second = recommend(state, now, exclude_key=first["key"], seed=1)
    assert second is not None
    assert second["key"] != first["key"]


def test_classifier_separates_meeting_from_deadline():
    state = base_state()
    client = {"now": "2026-09-12T14:50:00+09:30", "timezone": "Australia/Adelaide"}
    meeting = classify_turn({"userText": "NextPlan：帮我记录一下，下周三下午四点半和导师有一个 meeting。", "assistantText": "", "title": ""}, state, client)
    assert meeting["action"]["action"] == "upsert_calendar_event"
    assert meeting["action"]["kind"] == "meeting"
    assert meeting["action"]["date"] == "2026-09-16"
    assert meeting["action"]["time"] == "16:30"

    deadline = classify_turn({"userText": "NextPlan：记录一下9月20日是论文deadline", "assistantText": "", "title": ""}, state, client)
    assert deadline["action"]["action"] == "set_deadline"
    assert deadline["action"]["date"] == "2026-09-20"
