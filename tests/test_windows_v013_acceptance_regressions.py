from __future__ import annotations

from pathlib import Path

from mcp_server.local_actions_v3 import execute_action
from mcp_server.local_classifier_v1 import classify_local_turn
from mcp_server.storage_v3 import SQLiteCanonicalStoreV3


def _apply_turn(store: SQLiteCanonicalStoreV3, user_text: str, *, now: str = "2026-09-13T15:57:45Z"):
    turn = {
        "userText": user_text,
        "assistantText": "收到，NextPlan Sync 会处理这项变更。",
        "title": "Windows acceptance",
        "url": "https://chatgpt.com/c/test",
    }
    candidate = classify_local_turn(
        turn,
        store.get_state(),
        {
            "source": "nextplan-local-extension",
            "bridgeVersion": "0.1.3",
            "now": now,
            "timezone": "Australia/Sydney",
        },
    )
    assert candidate is not None, user_text
    assert isinstance(candidate.get("action"), dict), candidate
    return candidate, execute_action(store, dict(candidate["action"]))


def test_explicit_project_status_waiting_persists(tmp_path: Path):
    store = SQLiteCanonicalStoreV3(tmp_path / "nextplan.db")
    execute_action(store, {"action": "create_project", "name": "Windows验收测试V2", "category": "其他"})

    candidate, receipt = _apply_turn(store, 'NextPlan：把“Windows验收测试V2”设置为 waiting')

    assert candidate["kind"] == "direct_project_status"
    assert candidate["action"]["status"] == "waiting"
    assert receipt["status"] == "applied"
    project = next(p for p in store.get_state()["projects"] if p["name"] == "Windows验收测试V2")
    assert project["status"] == "waiting"


def test_calendar_meeting_is_written_to_canonical_state(tmp_path: Path):
    store = SQLiteCanonicalStoreV3(tmp_path / "nextplan.db")

    candidate, receipt = _apply_turn(
        store,
        "NextPlan：记录一下，明天下午4点有一个测试 meeting",
        now="2026-09-13T06:00:00Z",
    )

    assert candidate["kind"] == "calendar_event"
    assert candidate["action"]["action"] == "upsert_calendar_event"
    assert candidate["action"]["time"] == "16:00"
    assert receipt["status"] == "applied"
    events = store.get_state()["calendar_events"]
    assert len(events) == 1
    assert events[0]["title"] == "Meeting"
    assert events[0]["date"] == "2026-09-14"
    assert events[0]["time"] == "16:00"


def test_arbitrary_project_name_is_created_and_survives_restart(tmp_path: Path):
    db = tmp_path / "nextplan.db"
    store = SQLiteCanonicalStoreV3(db)

    candidate, receipt = _apply_turn(store, "NextPlan：新建项目 持久化测试")

    assert candidate["kind"] == "create_project"
    assert candidate["action"]["name"] == "持久化测试"
    assert receipt["status"] == "applied"
    assert any(p["name"] == "持久化测试" for p in store.get_state()["projects"])

    restarted = SQLiteCanonicalStoreV3(db)
    assert any(p["name"] == "持久化测试" for p in restarted.get_state()["projects"])


def test_bridge_does_not_mark_turn_seen_before_capture_finishes():
    source = Path("chrome_extension_local/content.js").read_text(encoding="utf-8")
    assert "const inflight = new Set()" in source
    assert "seen.add(fingerprint)" not in source
    assert "inflight.delete(fingerprint)" in source
    assert "setTimeout(schedule, 1800)" in source
