#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def main() -> int:
    github_token = _require_env("GITHUB_TOKEN")
    repo = _require_env("GITHUB_REPOSITORY")
    run_id = _require_env("GITHUB_RUN_ID")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip() or "1"

    # Configure the exact production server module with CI-scoped credentials.
    # The extension token is ephemeral and non-secret; the GitHub token is the
    # short-lived Actions token and is never written to canonical state.
    os.environ["NEXTPLAN_GITHUB_TOKEN"] = github_token
    os.environ["NEXTPLAN_GITHUB_REPO"] = repo
    os.environ["NEXTPLAN_GITHUB_BRANCH"] = "main"
    os.environ["NEXTPLAN_EXTENSION_TOKEN"] = "stage3-ci-acceptance-token"

    from mcp_server import server_v11  # imported only after env configuration

    transport = httpx.ASGITransport(app=server_v11.app)
    headers = {"Authorization": "Bearer stage3-ci-acceptance-token"}
    base_url = "http://nextplan-stage3.local"
    project_id = "project-item-daed6c"
    unique = f"{run_id}-{attempt}"
    temp_path = f"agent_sandbox/stage3-server-v11-{unique}.txt"

    async with httpx.AsyncClient(transport=transport, base_url=base_url, timeout=90) as client:
        async def post(path: str, payload: dict) -> dict:
            response = await client.post(path, headers=headers, json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"{path} failed with HTTP {response.status_code}: {response.text[:500]}")
            body = response.json()
            if not isinstance(body, dict):
                raise RuntimeError(f"{path} returned a non-object response")
            return body

        trigger = await post("/extension/agent/trigger", {
            "provider": "github",
            "event_type": "stage3_acceptance_probe",
            "provider_event_id": f"github-actions:{unique}",
            "verified_source": True,
            "project_id": project_id,
            "payload": {
                "repository": repo,
                "workflow": "NextPlan Stage III contract tests",
                "run_id": run_id,
                "attempt": attempt,
                "purpose": "server_v11 canonical production acceptance evidence",
            },
        })
        signal = trigger.get("signal") or {}
        signal_id = str(signal.get("id") or "")
        if not signal_id:
            raise RuntimeError("trigger did not return a signal id")

        read = await post("/extension/agent/execute", {
            "provider": "github",
            "capability": "repo.get",
            "payload": {},
            "project_id": project_id,
            "user_explicitly_requested": True,
            "idempotency_key": f"stage3-read-{unique}",
        })
        read_receipt = read.get("receipt") or {}
        if read.get("status") != "verified" or not bool(read_receipt.get("verified")):
            raise RuntimeError("repo.get was not verified")
        read_action_id = str(read_receipt.get("action_id") or "")

        write = await post("/extension/agent/execute", {
            "provider": "github",
            "capability": "file.create",
            "payload": {
                "path": temp_path,
                "content": f"NextPlan Stage III server_v11 acceptance {unique}\n",
                "message": f"NextPlan Stage III server_v11 acceptance: create {temp_path}",
                "branch": "main",
            },
            "project_id": project_id,
            "user_explicitly_requested": True,
            "explicit_confirmation": True,
            "idempotency_key": f"stage3-write-{unique}",
            "reconcile": {
                "summary": "Stage III server_v11 acceptance verified external write",
                "canonical_changes": {},
            },
        })
        write_receipt = write.get("receipt") or {}
        if write.get("status") != "verified" or not bool(write_receipt.get("verified")):
            raise RuntimeError("file.create was not verified")
        write_action_id = str(write_receipt.get("action_id") or "")
        reconciliation = (write.get("reconciliation") or {}).get("record") or {}
        reconciliation_id = str(reconciliation.get("id") or "")
        if not reconciliation_id:
            raise RuntimeError("verified write did not record reconciliation evidence")

        # Rollback resolves the original action from canonical state. Wait until
        # the action event has been applied by the canonical builder if needed.
        for _ in range(90):
            state = await server_v11.base._state()
            if any(str(a.get("action_id") or a.get("id") or "") == write_action_id for a in state.get("agent_actions", [])):
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("write action never appeared in canonical state")

        rollback = await post("/extension/agent/rollback", {
            "action_id": write_action_id,
            "explicit_confirmation": True,
        })
        rollback_receipt = rollback.get("receipt") or {}
        if rollback.get("status") != "rolled_back" or not bool(rollback_receipt.get("verified")):
            raise RuntimeError("rollback was not verified")
        rollback_action_id = str(rollback_receipt.get("action_id") or "")

        # Independent rollback verification against GitHub: the temporary file
        # must be absent after the server_v11 rollback path reports success.
        verify_headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "NextPlan-Stage3-Acceptance/1.0",
        }
        verify = await client.get(
            f"https://api.github.com/repos/{repo}/contents/{temp_path}",
            headers=verify_headers,
            params={"ref": "main"},
        )
        if verify.status_code != 404:
            raise RuntimeError(f"rollback verification expected 404, got {verify.status_code}")

        run = await post("/extension/agent/run", {
            "run_id": f"stage3-acceptance-{unique}",
            "project_id": project_id,
            "status": "completed",
            "verified": True,
            "signal_ids": [signal_id],
            "action_ids": [x for x in [read_action_id, write_action_id, rollback_action_id] if x],
            "reconciliation_ids": [reconciliation_id],
            "summary": "Stage III server_v11 acceptance run completed",
        })
        run_record = run.get("run") or {}
        if run.get("status") != "recorded" or run_record.get("status") != "completed" or not bool(run_record.get("verified")):
            raise RuntimeError("agent run evidence was not recorded")

    # Print only non-secret audit evidence for workflow logs.
    print(json.dumps({
        "status": "PASS",
        "signal_id": signal_id,
        "read_action_id": read_action_id,
        "write_action_id": write_action_id,
        "rollback_action_id": rollback_action_id,
        "reconciliation_id": reconciliation_id,
        "run_id": run_record.get("id"),
        "temp_path": temp_path,
        "rollback_verified": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
