from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from mcp_server.local_core_v3 import create_local_app


@pytest.mark.asyncio
async def test_desktop_core_queues_and_applies_new_project_confirmation(tmp_path):
    app = create_local_app(tmp_path / "nextplan.db", bootstrap_token="desktop-token", execution_dry_run=True)
    headers = {"Authorization": "Bearer desktop-token"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["runtime"] == "nextplan-local-core-v3"
        assert health.json()["schema_version"] == 2

        capture = await client.post("/conversation/capture", headers=headers, json={
            "turn": {
                "userText": "我准备开始找工作，第一步先把简历做好，然后开始申请职位。",
                "assistantText": "可以，我们先把简历整理好。",
                "title": "ChatGPT",
                "url": "https://chatgpt.com/c/test",
            },
            "client": {"source": "acceptance"},
            "apply": True,
        })
        assert capture.status_code == 200
        body = capture.json()
        assert body["candidate"]["kind"] == "conversation_project_discovery"
        assert body["candidate"]["requiresConfirmation"] is True
        assert body["candidate"]["action"]["evidence_text"].startswith("我准备开始找工作")
        assert body["queued"] is True
        assert "receipt" not in body

        pending = (await client.get("/pending", headers=headers)).json()["pending"]
        assert len(pending) == 1
        candidate_id = pending[0]["id"]
        applied = await client.post("/pending/apply", headers=headers, json={"id": candidate_id})
        assert applied.status_code == 200
        assert applied.json()["status"] == "applied"

        state = (await client.get("/state", headers=headers)).json()
        project = next(p for p in state["projects"] if p["name"] == "找工作")
        assert project["milestones"]
        assert project["milestones"][0]["status"] == "active"
        assert (await client.get("/pending", headers=headers)).json()["pending"] == []


@pytest.mark.asyncio
async def test_workspace_artifact_binding_and_verification(tmp_path):
    workspace = tmp_path / "job-search"
    workspace.mkdir()
    resume = workspace / "Resume_Final.pdf"
    resume.write_bytes(b"nextplan-resume-final")

    app = create_local_app(tmp_path / "workspace.db", bootstrap_token="desktop-token", execution_dry_run=True)
    headers = {"Authorization": "Bearer desktop-token"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        await client.post("/actions/execute", headers=headers, json={"action": {"action": "create_project", "project_id": "job", "name": "找工作", "category": "职业"}})
        await client.post("/actions/execute", headers=headers, json={"action": {"action": "create_task", "project_id": "job", "task_id": "resume", "name": "做简历"}})

        bound = await client.post("/workspaces/bind", headers=headers, json={"project_id": "job", "path": str(workspace)})
        assert bound.status_code == 200
        assert bound.json()["binding"]["authorized"] is True

        attached = await client.post("/artifacts/attach", headers=headers, json={
            "project_id": "job", "milestone_id": "resume", "path": str(resume)
        })
        assert attached.status_code == 200
        artifact = attached.json()["artifact"]
        assert artifact["availability"] == "available"
        assert artifact["verification_status"] == "verified"
        assert len(artifact["sha256"]) == 64

        state = (await client.get("/state", headers=headers)).json()
        assert state["workspace_bindings"][0]["path"] == str(workspace.resolve())
        assert state["artifacts"][0]["milestone_id"] == "resume"

        resume.unlink()
        verified = await client.post("/artifacts/verify", headers=headers, json={"artifact_id": artifact["id"]})
        assert verified.status_code == 200
        assert verified.json()["verification"]["availability"] == "missing"
        artifacts = (await client.get("/artifacts", headers=headers)).json()["artifacts"]
        assert artifacts[0]["availability"] == "missing"


@pytest.mark.asyncio
async def test_structured_execution_copy_verifies_and_shell_is_not_exposed(tmp_path):
    source_ws = tmp_path / "source"
    dest_ws = tmp_path / "dest"
    outside = tmp_path / "outside"
    source_ws.mkdir(); dest_ws.mkdir(); outside.mkdir()
    source = source_ws / "report.txt"
    source.write_text("verified-copy", encoding="utf-8")

    app = create_local_app(tmp_path / "execution.db", bootstrap_token="desktop-token", execution_dry_run=False)
    headers = {"Authorization": "Bearer desktop-token"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        for pid, name, ws in (("source", "Source", source_ws), ("dest", "Dest", dest_ws)):
            await client.post("/actions/execute", headers=headers, json={"action": {"action": "create_project", "project_id": pid, "name": name}})
            assert (await client.post("/workspaces/bind", headers=headers, json={"project_id": pid, "path": str(ws)})).status_code == 200
        artifact = (await client.post("/artifacts/attach", headers=headers, json={"project_id": "source", "path": str(source)})).json()["artifact"]

        action = {"capability": "file.copy", "source_artifact_id": artifact["id"], "destination_project_id": "dest", "destination_name": "copied-report.txt"}
        preview = await client.post("/local-actions/preview", headers=headers, json={"action": action})
        assert preview.status_code == 200
        assert preview.json()["risk"] == "R1"
        assert preview.json()["requires_confirmation"] is False

        executed = await client.post("/local-actions/execute", headers=headers, json={"action": action})
        assert executed.status_code == 200
        receipt = executed.json()
        assert receipt["status"] == "success"
        assert receipt["verification"]["status"] == "verified"
        assert (dest_ws / "copied-report.txt").read_text(encoding="utf-8") == "verified-copy"

        state = (await client.get("/state", headers=headers)).json()
        assert state["local_execution_receipts"][-1]["id"] == receipt["id"]

        app_preview = await client.post("/local-actions/preview", headers=headers, json={"action": {"capability": "application.open", "application_path": str(Path(sys.executable).resolve())}})
        assert app_preview.status_code == 200
        assert app_preview.json()["risk"] == "R2"
        assert app_preview.json()["requires_confirmation"] is True
        blocked = await client.post("/local-actions/execute", headers=headers, json={"action": {"capability": "application.open", "application_path": str(Path(sys.executable).resolve())}})
        assert blocked.json()["status"] == "confirmation_required"

        denied = await client.post("/local-actions/preview", headers=headers, json={"action": {"capability": "folder.open", "path": str(outside)}})
        assert denied.status_code == 403

        shell = await client.post("/local-actions/preview", headers=headers, json={"action": {"capability": "shell.execute", "command": "echo nope"}})
        assert shell.status_code == 400
        assert "unsupported local capability" in shell.json()["detail"]


@pytest.mark.asyncio
async def test_desktop_status_pairing_code_and_permission_mode(tmp_path):
    app = create_local_app(tmp_path / "desktop.db", bootstrap_token="desktop-token", execution_dry_run=True)
    headers = {"Authorization": "Bearer desktop-token"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        unauth_code = await client.post("/pairing/code", json={})
        assert unauth_code.status_code == 401
        code = await client.post("/pairing/code", headers=headers, json={})
        assert code.status_code == 200
        assert len(code.json()["code"]) == 6
        assert code.json()["code"].isdigit()

        update = await client.post("/permissions/update", headers=headers, json={"mode": "conservative"})
        assert update.status_code == 200
        permissions = (await client.get("/permissions", headers=headers)).json()["permissions"]
        assert permissions["mode"] == "conservative"

        status = await client.get("/desktop/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["permission_mode"] == "conservative"
        assert Path(status.json()["db_path"]).name == "desktop.db"
