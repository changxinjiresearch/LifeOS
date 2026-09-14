from __future__ import annotations

from mcp_server.local_actions_v4 import execute_action
from mcp_server.local_classifier_v1 import classify_local_turn
from mcp_server.storage_v3 import SQLiteCanonicalStoreV3


def _base_state() -> dict:
    return {
        "projects": [
            {
                "id": "project-final",
                "name": "Windows最终验收",
                "status": "active",
                "category": "其他",
                "priority": 2,
                "next_action": "测试任务A",
                "milestones": [
                    {"id": "task-a", "name": "测试任务A", "status": "active"}
                ],
            }
        ],
        "deadlines": [],
        "calendar_events": [],
        "notes": [],
        "resources": [],
        "automation_rules": [],
        "events": [],
    }


def _classify(text: str, state: dict | None = None):
    return classify_local_turn(
        {
            "userText": text,
            "assistantText": "收到，NextPlan Sync 会处理这项变更。",
            "title": "Windows final acceptance",
        },
        state or _base_state(),
        {"timezone": "Australia/Sydney", "now": "2026-09-14T10:00:00+10:00"},
    )


def test_full_local_classifier_chain_reaches_note_resource_automation_calendar_and_deadline():
    note = _classify("NextPlan：把这句话保存为笔记，标题：最终笔记")
    assert note and note["action"]["action"] == "add_note"
    assert note["action"]["title"] == "最终笔记"

    resource = _classify("NextPlan：把 https://example.com/final 保存为资源，标题：最终资源")
    assert resource and resource["action"]["action"] == "add_resource"
    assert resource["action"]["location"] == "https://example.com/final"

    automation = _classify("NextPlan：开启 preparation 自动化规则，提前5天")
    assert automation and automation["action"]["action"] == "upsert_automation_rule"
    assert automation["action"]["rule_id"] == "preparation-window"
    assert automation["action"]["threshold_days"] == 5

    calendar = _classify("NextPlan：记录一下，明天下午4点有一个测试 meeting")
    assert calendar and calendar["action"]["action"] == "upsert_calendar_event"
    assert calendar["action"]["time"] == "16:00"

    deadline = _classify("NextPlan：记录 deadline 2026年12月30日")
    assert deadline and deadline["action"]["action"] == "set_deadline"
    assert deadline["action"]["date"] == "2026-12-30"


def test_task_completion_is_not_misrouted_as_project_status():
    candidate = _classify("NextPlan：把“测试任务A”标记为完成")
    assert candidate is not None
    assert candidate["action"]["action"] == "complete_task"
    assert candidate["action"]["task_id"] == "task-a"
    assert candidate["action"]["project_id"] == "project-final"


def test_v4_action_executor_covers_feature_parity_and_persists(tmp_path):
    db = tmp_path / "nextplan.db"
    store = SQLiteCanonicalStoreV3(db)

    created = execute_action(store, {"action": "create_project", "name": "Windows最终验收"})
    pid = created["project_id"]

    note = execute_action(
        store,
        {
            "action": "add_note",
            "note_id": "note-final",
            "title": "最终笔记",
            "body": "本地笔记正文",
            "project_id": pid,
        },
    )
    assert note["note_id"] == "note-final"

    resource = execute_action(
        store,
        {
            "action": "add_resource",
            "resource_id": "resource-final",
            "title": "最终资源",
            "location": "https://example.com/final",
            "project_id": pid,
        },
    )
    assert resource["resource_id"] == "resource-final"

    rule = execute_action(
        store,
        {
            "action": "upsert_automation_rule",
            "rule_id": "preparation-window",
            "enabled": True,
            "threshold_days": 5,
        },
    )
    assert rule["rule"]["threshold_days"] == 5

    calendar = execute_action(
        store,
        {
            "action": "upsert_calendar_event",
            "calendar_event_id": "calendar-final",
            "title": "测试 meeting",
            "date": "2026-09-15",
            "time": "16:00",
            "kind": "meeting",
            "project_id": pid,
        },
    )
    assert calendar["calendar_event_id"] == "calendar-final"

    execute_action(
        store,
        {
            "action": "set_deadline",
            "deadline_id": "deadline-final",
            "title": "最终 Deadline",
            "date": "2026-12-30",
            "project_id": pid,
        },
    )

    state = store.get_state()
    assert any(n["id"] == "note-final" for n in state["notes"])
    assert any(r["id"] == "resource-final" for r in state["resources"])
    assert any(r["id"] == "preparation-window" and r["threshold_days"] == 5 for r in state["automation_rules"])
    assert any(c["id"] == "calendar-final" and c["time"] == "16:00" for c in state["calendar_events"])
    assert any(d["id"] == "deadline-final" for d in state["deadlines"])

    reopened = SQLiteCanonicalStoreV3(db).get_state()
    assert any(n["id"] == "note-final" for n in reopened["notes"])
    assert any(r["id"] == "resource-final" for r in reopened["resources"])
    assert any(r["id"] == "preparation-window" for r in reopened["automation_rules"])
    assert any(c["id"] == "calendar-final" for c in reopened["calendar_events"])

    execute_action(store, {"action": "remove_note", "note_id": "note-final"})
    execute_action(store, {"action": "remove_resource", "resource_id": "resource-final"})
    execute_action(store, {"action": "remove_calendar_event", "calendar_event_id": "calendar-final"})
    execute_action(store, {"action": "remove_automation_rule", "rule_id": "preparation-window"})
    final = store.get_state()
    assert not any(n["id"] == "note-final" for n in final["notes"])
    assert not any(r["id"] == "resource-final" for r in final["resources"])
    assert not any(c["id"] == "calendar-final" for c in final["calendar_events"])
    assert not any(r["id"] == "preparation-window" for r in final["automation_rules"])
