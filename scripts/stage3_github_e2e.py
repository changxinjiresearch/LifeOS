#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.agent_stage3 import execute_external_action  # noqa: E402
from mcp_server.connectors_v1 import ConnectorRegistry, GitHubConnector  # noqa: E402


async def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY are required")

    connector = GitHubConnector(token, repo, branch)
    registry = ConnectorRegistry()
    registry.register(connector)

    # 1) Real read-only provider flow.
    read = await execute_external_action(
        registry,
        {},
        provider="github",
        capability="repo.get",
        payload={},
        user_explicitly_requested=True,
    )
    assert read["status"] == "verified", read
    assert read["receipt"]["verified"] is True

    # 2) Consequential action must stop at the permission boundary.
    blocked = await execute_external_action(
        registry,
        {},
        provider="github",
        capability="issue.create",
        payload={"title": "Stage III permission smoke - should not be created"},
        user_explicitly_requested=True,
    )
    assert blocked["status"] == "needs_confirmation", blocked

    # 3) Real reversible provider write + verification + compensating rollback.
    path = f"agent_sandbox/stage3-e2e-{run_id}.txt"
    created = await execute_external_action(
        registry,
        {},
        provider="github",
        capability="file.create",
        payload={
            "path": path,
            "content": "NextPlan Stage III E2E smoke. Safe to delete.\n",
            "message": f"NextPlan Stage III E2E: create {path}",
            "branch": branch,
        },
        user_explicitly_requested=True,
        explicit_confirmation=True,
        idempotency_key=f"stage3-e2e-{run_id}",
    )
    assert created["status"] == "verified", created
    assert created["receipt"]["verified"] is True

    rollback_result = await connector.rollback(
        "file.create",
        {"path": path, "branch": branch},
        created["_rollback_result"],
    )
    assert rollback_result["status"] == "rolled_back", rollback_result
    assert rollback_result["verified"] is True

    print("STAGE3_GITHUB_E2E=PASS")
    print(f"READ_ONLY_VERIFIED={read['receipt']['verified']}")
    print(f"CONSEQUENTIAL_PERMISSION_GATE={blocked['status']}")
    print(f"REVERSIBLE_WRITE_VERIFIED={created['receipt']['verified']}")
    print(f"ROLLBACK_VERIFIED={rollback_result['verified']}")


if __name__ == "__main__":
    asyncio.run(main())
