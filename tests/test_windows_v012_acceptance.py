from pathlib import Path

from mcp_server.local_classifier_v1 import classify_local_turn


ROOT = Path(__file__).resolve().parents[1]


def test_chinese_colon_nextplan_create_project_is_executable():
    turn = {
        "userText": "NextPlan：新建项目 Windows验收测试",
        "assistantText": "收到，NextPlan Sync 会处理这项变更。",
        "title": "Windows acceptance",
        "url": "https://chatgpt.com/c/windows-v012",
    }
    candidate = classify_local_turn(turn, {"projects": []}, {})
    assert candidate is not None
    assert candidate["kind"] == "create_project"
    assert candidate["requiresConfirmation"] is False if "requiresConfirmation" in candidate else True
    assert candidate["action"]["action"] == "create_project"
    assert candidate["action"]["name"] == "Windows验收测试"


def test_windows_release_hides_desktop_and_local_core_consoles():
    rust = (ROOT / "desktop_local/src-tauri/src/main.rs").read_text(encoding="utf-8")
    assert 'windows_subsystem = "windows"' in rust
    assert "CREATE_NO_WINDOW" in rust
    assert "creation_flags(CREATE_NO_WINDOW)" in rust


def test_bridge_normalizes_nextplan_colon_boundary():
    content = (ROOT / "chrome_extension_local/content.js").read_text(encoding="utf-8")
    assert "normalizeCommandText" in content
    assert "next\\s*plan\\s*[：:]\\s*" in content
    assert "No executable change detected" in content
