from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from mcp_server.local_actions_v1 import execute_action
from mcp_server.local_core_v1 import create_local_app
from mcp_server.local_projector import semantic_projection
from mcp_server.storage_v1 import SQLiteCanonicalStore
from scripts.migrate_lifeos_to_sqlite import migrate

ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_store_event_projection_and_idempotency(tmp_path):
    store = SQLiteCanonicalStore(tmp_path / "nextplan.db")
    created = execute_action(store, {
        "action": "create_project",
        "project_id": "job",
        "name": "找工作",
        "category": "职业",
        "next_action": "做简历",
    })
    assert created["status"] == "applied"
    task = execute_action(store, {
        "action": "create_task",
        "project_id": "job",
        "task_id": "resume",
        "name": "做简历",
    })
    assert task["status"] == "applied"

    event = {
        "id": "evt-test-complete-resume",
        "at": "2026-09-13T00:00:00Z",
        "type": "task_completed",
        "project_id": "job",
        "task_id": "resume",
        "summary": "Completed resume",
        "source": {"kind": "test"},
    }
    first = store.append_event(event)
    second = store.append_event(event)
    assert first["status"] == "applied"
    assert second["status"] == "no_change"

    project = next(p for p in store.get_state()["projects"] if p["id"] == "job")
    assert project["milestones"][0]["status"] == "completed"
    assert project["status"] == "completed"
    assert project["next_action"] == "项目已完成"
    assert sum(1 for x in store.list_events() if x["id"] == event["id"]) == 1


def test_real_lifeos_snapshot_migrates_with_semantic_parity(tmp_path):
    db = tmp_path / "migrated.db"
    result = migrate(ROOT / "state.json", ROOT / "events" / "inbox", db)
    assert result["status"] == "PASS"
    assert result["semantic_parity"] is True
    assert result["projects"] > 0

    source = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    local = SQLiteCanonicalStore(db).get_state()
    assert semantic_projection(source) == semantic_projection(local)
    assert local["system"]["canonical_store"] == "sqlite-local"
    assert local["system"]["event_layer"]["mode"] == "sqlite-append-only-events"


@pytest.mark.asyncio
async def test_local_core_runs_without_github_or_railway_and_applies_conversation_fact(tmp_path, monkeypatch):
    for key in (
        "NEXTPLAN_GITHUB_TOKEN",
        "NEXTPLAN_GITHUB_REPO",
        "NEXTPLAN_GITHUB_BRANCH",
        "NEXTPLAN_EXTENSION_TOKEN",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    app = create_local_app(tmp_path / "core.db", token="local-test-token")
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer local-test-token"}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["canonical_store"] == "sqlite-local"

        unauth = await client.get("/state")
        assert unauth.status_code == 401

        create_project = await client.post("/actions/execute", headers=headers, json={
            "action": {
                "action": "create_project",
                "project_id": "internship",
                "name": "帮助宝宝找实习",
                "category": "职业",
                "next_action": "做简历",
            }
        })
        assert create_project.status_code == 200
        assert create_project.json()["status"] == "applied"

        create_task = await client.post("/actions/execute", headers=headers, json={
            "action": {
                "action": "create_task",
                "project_id": "internship",
                "task_id": "resume",
                "name": "做简历",
            }
        })
        assert create_task.status_code == 200

        capture = await client.post("/conversation/capture", headers=headers, json={
            "turn": {
                "userText": "我现在已经把宝宝简历做完了。",
                "assistantText": "很好，下一步可以开始投简历。",
                "title": "ChatGPT",
            },
            "client": {"source": "test"},
            "apply": True,
        })
        assert capture.status_code == 200
        body = capture.json()
        assert body["candidate"]["kind"] == "conversation_fact"
        assert body["candidate"]["requiresConfirmation"] is False
        assert body["candidate"]["provenance"]["sourceAuthority"] == "user_assertion"
        assert body["receipt"]["status"] == "applied"

        state_response = await client.get("/state", headers=headers)
        assert state_response.status_code == 200
        project = next(p for p in state_response.json()["projects"] if p["id"] == "internship")
        assert project["milestones"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_local_core_assistant_only_claim_does_not_mutate(tmp_path):
    app = create_local_app(tmp_path / "guard.db", token="guard-token")
    headers = {"Authorization": "Bearer guard-token"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        await client.post("/actions/execute", headers=headers, json={"action": {"action": "create_project", "project_id": "internship", "name": "帮助宝宝找实习", "category": "职业"}})
        await client.post("/actions/execute", headers=headers, json={"action": {"action": "create_task", "project_id": "internship", "task_id": "resume", "name": "做简历"}})
        response = await client.post("/conversation/capture", headers=headers, json={
            "turn": {"userText": "好的。", "assistantText": "宝宝简历现在已经正式完成。"},
            "apply": True,
        })
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        state = (await client.get("/state", headers=headers)).json()
        project = next(p for p in state["projects"] if p["id"] == "internship")
        assert project["milestones"][0]["status"] == "active"
