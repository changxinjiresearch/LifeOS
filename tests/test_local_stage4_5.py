from __future__ import annotations

import httpx
import pytest

from mcp_server.local_actions_v2 import execute_action
from mcp_server.local_core_v2 import create_local_app
from mcp_server.local_classifier_v1 import classify_local_turn
from mcp_server.storage_v1 import SQLiteCanonicalStore


@pytest.mark.asyncio
async def test_one_time_pairing_establishes_local_extension_credential(tmp_path):
    app = create_local_app(tmp_path / "pair.db")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        assert (await client.get("/healthz")).json()["paired"] is False
        assert (await client.get("/state")).status_code == 401

        code = app.issue_pairing_code()
        assert len(code) == 6 and code.isdigit()
        wrong = await client.post("/pairing/complete", json={"code": "000000", "extension_id": "test"})
        assert wrong.status_code == 403

        paired = await client.post("/pairing/complete", json={"code": code, "extension_id": "test-extension"})
        assert paired.status_code == 200
        token = paired.json()["token"]
        assert token
        headers = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/state", headers=headers)).status_code == 200
        assert (await client.get("/healthz")).json()["paired"] is True

        reused = await client.post("/pairing/complete", json={"code": code, "extension_id": "attacker"})
        assert reused.status_code == 403


@pytest.mark.asyncio
async def test_chat_creates_confirm_first_project_blueprint_then_can_apply(tmp_path):
    app = create_local_app(tmp_path / "project.db", bootstrap_token="test-token")
    headers = {"Authorization": "Bearer test-token"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.post("/conversation/capture", headers=headers, json={
            "turn": {
                "userText": "我准备开始找工作，第一步先把简历做好，然后开始申请职位。",
                "assistantText": "可以，我们先从简历开始。",
            },
            "apply": True,
        })
        assert response.status_code == 200
        body = response.json()
        candidate = body["candidate"]
        assert candidate["kind"] == "conversation_project_discovery"
        assert candidate["requiresConfirmation"] is True
        assert candidate["action"]["action"] == "create_project_blueprint"
        assert candidate["action"]["name"] == "找工作"
        assert [x["name"] for x in candidate["action"]["milestones"]] == ["做简历", "申请职位"]
        assert "receipt" not in body
        assert (await client.get("/projects", headers=headers)).json()["projects"] == []

        applied = await client.post("/actions/execute", headers=headers, json={"action": candidate["action"]})
        assert applied.status_code == 200
        assert applied.json()["milestone_count"] == 2
        project = (await client.get("/projects", headers=headers)).json()["projects"][0]
        assert project["name"] == "找工作"
        assert project["milestones"][0]["name"] == "做简历"
        assert project["milestones"][0]["status"] == "active"
        assert project["milestones"][1]["status"] == "planned"
        assert project["next_action"] == "做简历"


@pytest.mark.asyncio
async def test_project_grows_from_later_chat_without_duplicate_project(tmp_path):
    app = create_local_app(tmp_path / "growth.db", bootstrap_token="test-token")
    headers = {"Authorization": "Bearer test-token"}
    execute_action(app.store, {
        "action": "create_project_blueprint",
        "project_id": "job",
        "name": "找工作",
        "category": "职业",
        "milestones": [
            {"id": "resume", "name": "做简历", "status": "active"},
            {"id": "apply", "name": "申请职位", "status": "planned"},
        ],
    })
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.post("/conversation/capture", headers=headers, json={
            "turn": {
                "userText": "申请之前我还应该准备一份 cover letter。",
                "assistantText": "可以把它加到申请流程里。",
            },
            "apply": True,
        })
        candidate = response.json()["candidate"]
        assert candidate["kind"] == "conversation_project_growth"
        assert candidate["requiresConfirmation"] is True
        assert candidate["action"]["action"] == "create_task"
        assert candidate["action"]["project_id"] == "job"
        assert candidate["action"]["name"] == "准备 Cover Letter"
        assert len((await client.get("/projects", headers=headers)).json()["projects"]) == 1

        await client.post("/actions/execute", headers=headers, json={"action": candidate["action"]})
        project = (await client.get("/projects", headers=headers)).json()["projects"][0]
        assert [m["name"] for m in project["milestones"]].count("准备 Cover Letter") == 1


@pytest.mark.asyncio
async def test_existing_stage4_progress_capture_still_auto_applies_locally(tmp_path):
    app = create_local_app(tmp_path / "progress.db", bootstrap_token="test-token")
    headers = {"Authorization": "Bearer test-token"}
    execute_action(app.store, {
        "action": "create_project_blueprint", "project_id": "job", "name": "帮助宝宝找实习", "category": "职业",
        "milestones": [
            {"id": "resume", "name": "做简历", "status": "active"},
            {"id": "apply", "name": "搭建自动投简历工作流", "status": "planned"},
        ],
    })
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.post("/conversation/capture", headers=headers, json={
            "turn": {"userText": "我现在已经把宝宝简历做完了。", "assistantText": "很好。"},
            "apply": True,
        })
        body = response.json()
        assert body["candidate"]["kind"] == "conversation_fact"
        assert body["candidate"]["provenance"]["sourceAuthority"] == "user_assertion"
        assert body["receipt"]["status"] == "applied"
        project = (await client.get("/projects", headers=headers)).json()["projects"][0]
        assert project["milestones"][0]["status"] == "completed"
        assert project["milestones"][1]["status"] == "active"


def test_speculation_and_assistant_only_text_do_not_create_project_truth():
    empty = {"projects": []}
    assert classify_local_turn({"userText": "以后有机会我可能想找实习。", "assistantText": "可以。"}, empty, {}) is None
    assert classify_local_turn({"userText": "好的。", "assistantText": "你现在正式开始找工作了，先做简历。"}, empty, {}) is None


def test_existing_ambiguous_resume_status_keeps_confirmation_guard():
    state = {
        "projects": [
            {"id": "a", "name": "A", "status": "active", "milestones": [{"id": "x", "name": "准备简历", "status": "active"}]},
            {"id": "b", "name": "B", "status": "active", "milestones": [{"id": "y", "name": "修改简历", "status": "active"}]},
        ]
    }
    candidate = classify_local_turn({"userText": "简历做完了。", "assistantText": ""}, state, {})
    assert candidate is not None
    assert candidate["requiresConfirmation"] is True
