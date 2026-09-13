from __future__ import annotations

import json
from pathlib import Path

from mcp_server.local_classifier_v1 import classify_local_turn
from mcp_server.local_command_compat_v1 import normalize_turn


ROOT = Path(__file__).resolve().parents[1]


def _state():
    return {
        "projects": [
            {
                "id": "project-windows",
                "name": "Windows验收测试",
                "status": "active",
                "category": "其他",
                "priority": 2,
                "next_action": "",
                "milestones": [],
            }
        ],
        "deadlines": [],
        "calendar_events": [],
    }


def test_no_space_create_command_is_normalized_and_classified():
    turn = normalize_turn({"userText": "NextPlan：新建项目持久化测试", "assistantText": "收到"})
    assert turn["userText"] == "NextPlan 新建项目 持久化测试"
    candidate = classify_local_turn(turn, {"projects": []}, {})
    assert candidate is not None
    assert candidate["kind"] == "create_project"
    assert candidate["action"]["name"] == "持久化测试"


def test_explicit_project_status_command_is_classified():
    candidate = classify_local_turn(
        {"userText": "NextPlan：把“Windows验收测试”项目设置为 waiting", "assistantText": "收到"},
        _state(),
        {},
    )
    assert candidate is not None
    assert candidate["kind"] == "direct_project_status"
    assert candidate["action"] == {
        "action": "update_project",
        "project_id": "project-windows",
        "status": "waiting",
        "capture_source": "explicit_nextplan_command",
        "operation_id": candidate["id"],
    }


def test_bridge_and_desktop_adapter_contain_calendar_compatibility_contract():
    background = (ROOT / "chrome_extension_local" / "background.js").read_text(encoding="utf-8")
    adapter = (ROOT / "desktop_local" / "ui" / "desktop-adapter.js").read_text(encoding="utf-8")
    assert 'CAL_COMPAT_PREFIX = "__NP_CAL_V1__:"' in background
    assert 'action:"upsert_calendar_event"' in background
    assert 'action:"set_deadline"' in background
    assert 'project_id:"calendar"' in background
    assert 'compatibility:"calendar-event-v1"' in background
    assert "__NP_CAL_V1__:" in adapter
    assert "state.deadlines = deadlines" in adapter
    assert "state.calendar_events = nativeEvents" in adapter


def test_v013_versions_are_aligned():
    manifest = json.loads((ROOT / "chrome_extension_local" / "manifest.json").read_text(encoding="utf-8"))
    tauri = json.loads((ROOT / "desktop_local" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "desktop_local" / "package.json").read_text(encoding="utf-8"))
    cargo = (ROOT / "desktop_local" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    assert manifest["version"] == "0.1.3"
    assert tauri["version"] == "0.1.3"
    assert package["version"] == "0.1.3"
    assert 'version = "0.1.3"' in cargo
