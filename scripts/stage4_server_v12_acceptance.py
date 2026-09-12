#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json

import httpx

from mcp_server import server_v12


TOKEN = "stage4-acceptance-token"


def fixture_state():
    return {
        "projects": [
            {
                "id": "internship",
                "name": "帮助宝宝找实习",
                "status": "active",
                "next_action": "做简历",
                "milestones": [
                    {"id": "resume", "name": "做简历", "status": "active"},
                    {"id": "auto-apply", "name": "搭建自动投简历工作流", "status": "planned"},
                ],
            }
        ]
    }


async def main():
    # Exercise the exact production ASGI composition without touching canonical GitHub state.
    server_v12.v11.base.EXTENSION_TOKEN = TOKEN

    async def fake_state():
        return fixture_state()

    server_v12.v11.base._state = fake_state

    transport = httpx.ASGITransport(app=server_v12.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://nextplan.test") as client:
        response = await client.post(
            "/extension/classify",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "turn": {
                    "userText": "我现在已经把宝宝简历做完了。",
                    "assistantText": "太好了。",
                    "title": "ChatGPT",
                    "url": "https://chatgpt.com/c/test",
                },
                "client": {"timezone": "Australia/Adelaide", "bridgeVersion": "0.5.0"},
            },
        )
        response.raise_for_status()
        payload = response.json()
        candidate = payload.get("candidate") or {}
        assert candidate.get("kind") == "conversation_fact", payload
        assert candidate.get("requiresConfirmation") is False, payload
        assert candidate.get("action", {}).get("action") == "complete_task", payload
        assert candidate.get("action", {}).get("project_id") == "internship", payload
        assert candidate.get("action", {}).get("task_id") == "resume", payload
        assert candidate.get("provenance", {}).get("assistantUsedAsEvidence") is False, payload

        # Assistant-only completion must not create a write candidate.
        response2 = await client.post(
            "/extension/classify",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "turn": {
                    "userText": "好的。",
                    "assistantText": "宝宝简历现在已经正式完成。",
                    "title": "ChatGPT",
                    "url": "https://chatgpt.com/c/test",
                },
                "client": {"timezone": "Australia/Adelaide", "bridgeVersion": "0.5.0"},
            },
        )
        response2.raise_for_status()
        assert response2.json().get("candidate") is None, response2.text

    print(json.dumps({"status": "PASS", "composition": "server_v12", "ordinary_fact": True, "assistant_only_guard": True}))


if __name__ == "__main__":
    asyncio.run(main())
