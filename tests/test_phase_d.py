from datetime import datetime, timezone

from engine.build_state_v2 import _apply_automation_event
from mcp_server.cloud_classifier_v5 import classify_turn
from mcp_server.phase_d_engine import evaluate_automations, plan_state

NOW = datetime(2026, 9, 12, 6, 40, tzinfo=timezone.utc)


def sample_state():
    return {
        "projects": [
            {
                "id": "active",
                "name": "Active Project",
                "category": "科研",
                "status": "active",
                "priority": 3,
                "next_action": "Run experiment",
                "milestones": [{"id": "run", "name": "Run experiment", "status": "active"}],
            },
            {
                "id": "waiting",
                "name": "Waiting Paper",
                "category": "科研",
                "status": "waiting",
                "priority": 3,
                "next_action": "Wait for editor",
                "milestones": [{"id": "decision", "name": "Decision", "status": "waiting"}],
            },
        ],
        "deadlines": [{"id": "d1", "project_id": "active", "title": "Experiment deadline", "date": "2026-09-14", "prep_days": 3}],
        "calendar_events": [],
        "notes": [],
        "resources": [],
        "automation_rules": [],
        "events": [
            {"id": "e1", "at": "2026-09-01T00:00:00Z", "type": "project_updated", "project_id": "active", "summary": "Old movement"},
            {"id": "e2", "at": "2026-09-01T00:00:00Z", "type": "project_updated", "project_id": "waiting", "summary": "Waiting started"},
        ],
    }


def test_ai_plan_uses_actionable_focus_and_time_pressure():
    plan = plan_state(sample_state(), NOW)
    assert plan["planning_version"] == "1.0"
    assert plan["focus_now"]["project_id"] == "active"
    assert all(x.get("project_id") != "waiting" for x in plan["top_candidates"])
    assert any(x["kind"] == "prepare_upcoming_commitment" for x in plan["interventions"])


def test_automation_surfaces_stale_and_waiting_followup():
    out = evaluate_automations(sample_state(), NOW)
    rule_ids = {x["rule_id"] for x in out["findings"]}
    assert "stale-active" in rule_ids
    assert "waiting-followup" in rule_ids
    assert "preparation-window" in rule_ids


def test_automation_rule_override_can_disable_stale_rule():
    state = sample_state()
    state["automation_rules"] = [{"id": "stale-active", "enabled": False}]
    out = evaluate_automations(state, NOW)
    assert "stale-active" not in {x["rule_id"] for x in out["findings"]}


def test_cloud_classifier_understands_rule_change():
    state = sample_state()
    turn = {"userText": "NextPlan：把等待项目自动提醒改成10天"}
    candidate = classify_turn(turn, state, {"now": NOW.isoformat()})
    assert candidate is not None
    assert candidate["action"]["action"] == "upsert_automation_rule"
    assert candidate["action"]["rule_id"] == "waiting-followup"
    assert candidate["action"]["threshold_days"] == 10


def test_state_builder_applies_automation_snapshot_and_rule():
    state = sample_state()
    _apply_automation_event(state, {
        "id": "rule-1",
        "at": NOW.isoformat(),
        "type": "automation_rule_upserted",
        "automation_rule": {"id": "waiting-followup", "enabled": True, "threshold_days": 10},
        "summary": "rule",
    })
    assert state["automation_rules"][0]["threshold_days"] == 10
    _apply_automation_event(state, {
        "id": "snap-1",
        "at": NOW.isoformat(),
        "type": "automation_snapshot_refreshed",
        "automation_snapshot": {"automation_version": "1.0", "generated_at": NOW.isoformat(), "finding_count": 1, "findings": [{"id": "a1", "rule_id": "waiting-followup", "title": "Waiting Paper", "reason": "10 days", "severity": "medium"}]},
        "summary": "snapshot",
    })
    assert state["automation_meta"]["finding_count"] == 1
    assert state["automation_feed"][0]["rule_id"] == "waiting-followup"
