from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_server import server_v13


class JarvisWebApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vars = {
            "NEXTPLAN_JARVIS_ENABLED": "1",
            "NEXTPLAN_JARVIS_TOKEN": "a" * 48,
            "NEXTPLAN_JARVIS_DB": str(self.root / "private" / "jarvis.db"),
            "NEXTPLAN_JARVIS_PERSISTENT_ROOT": str(self.root),
            "NEXTPLAN_JARVIS_TEST_MODE": "1",
            "NEXTPLAN_JARVIS_MODEL_URL": "",
            "NEXTPLAN_JARVIS_MODEL_NAME": "",
        }
        self.env = patch.dict(os.environ, self.vars)
        self.env.start()
        self.addCleanup(self.env.stop)

    async def call(self, path, method="GET", payload=None, token="a"*48,
                   origin="https://changxinjiresearch.github.io"):
        from mcp_server import server_v13
        blob=json.dumps(payload or {}).encode()
        headers=[(b"origin",origin.encode()),(b"content-type",b"application/json")]
        if token is not None:
            headers.append((b"authorization",("Bearer "+token).encode()))
        scope={"type":"http","method":method,"path":path,"query_string":b"", "headers":headers}
        results=[]
        async def receive():
            return {"type":"http.request","body":blob,"more_body":False}
        async def send(item):
            results.append(item)
        await server_v13.app(scope,receive,send)
        started=results[0]
        raw=results[-1].get("body",b"")
        return started["status"],dict(started["headers"]),json.loads(raw) if raw else {}

    async def test_non_exposed_status(self):
        status,_,r=await self.call("/jarvis/v1/status",token=None)
        self.assertEqual(status,200)
        self.assertEqual(r["status"],"available")
        self.assertEqual(r["canonical_sync"],"not_migrated")

    async def test_wrong_token_is_rejected(self):
        status,_,_=await self.call("/jarvis/v1/sync/state",token="wrong")
        self.assertEqual(status,401)

    async def test_cross_origin_request_is_rejected(self):
        status,_,_=await self.call("/jarvis/v1/sync/state",origin="https://evil.example")
        self.assertEqual(status,403)

    async def test_get_state_from_private_workspace(self):
        status,heads,r=await self.call("/jarvis/v1/sync/state")
        self.assertEqual(status,200)
        self.assertEqual(r["revision"],0)
        self.assertEqual(r["authority"],"shadow_until_migrated")
        self.assertEqual(heads[b"cache-control"],b"no-store")

    async def test_bootstrap_write_and_read(self):
        status,_,r=await self.call("/jarvis/v1/sync/bootstrap",method="POST",payload={
            "confirmed":True,
            "projects":[{"id":"project-one","name":"P1 Demo","status":"active"}]})
        self.assertEqual(status,200)
        self.assertEqual(r["revision"],1)
        _,_,state=await self.call("/jarvis/v1/sync/state")
        self.assertEqual(len(state["projects"]),1)

    async def test_action_write_requires_proposed_intent(self):
        await self.call("/jarvis/v1/sync/bootstrap",method="POST",payload={
            "confirmed":True,"projects":[{"id":"project-one","name":"P1 Demo","status":"active"}]})
        base={"protocol_version":"jarvis-p0-v1","operation_id":"web-op-1",
              "device_id":"chrome-web","target":{"entity_type":"project","entity_id":"project-one"},
              "action":"update_project","expected_revision":1,"status":"proposed","authority":"user_confirmed"}
        status,_,r=await self.call("/jarvis/v1/sync/action",method="POST",payload={
            "intent":base,"values":{"status":"completed"}})
        self.assertEqual(status,200)
        self.assertEqual(r["status"],"applied")
        status,_,r=await self.call("/jarvis/v1/sync/action",method="POST",payload={
            "intent":base,"values":{"status":"waiting"}})
        self.assertEqual(r["status"],"already_applied")

    async def test_record_and_search_consent(self):
        payload={"context_type":"decision","project_id":"project-one",
                 "summary":"We choose protocol B","source_kind":"manual_import",
                 "source_ref":"manual://evidence","user_authorized":True,
                 "confirmed_by_user":True}
        status,_,r=await self.call("/jarvis/v1/context/record",method="POST",payload=payload)
        self.assertEqual(status,200)
        self.assertEqual(r["status"],"recorded")
        status,_,out=await self.call("/jarvis/v1/knowledge/search")
        self.assertEqual(len(out["items"]),1)
        self.assertEqual(out["items"][0]["summary"],payload["summary"])

    async def test_prohibit_unconfirmed_context(self):
        status,_,_=await self.call("/jarvis/v1/context/record",method="POST",payload={
            "context_type":"decision","project_id":"project-one","summary":"Guessed by AI",
            "source_kind":"manual_import","source_ref":"chatgpt://example",
            "user_authorized":True,"confirmed_by_user":False})
        self.assertEqual(status,400)

    async def test_brain_is_read_only(self):
        status,_,r=await self.call("/jarvis/v1/brain/ask",method="POST",payload={
            "question":"现在项目进度怎么样？"})
        self.assertEqual(status,200)
        self.assertEqual(r["executed_actions"],0)

    async def test_no_persistent_mount_refuses_store(self):
        with patch.dict(os.environ,{"NEXTPLAN_JARVIS_TEST_MODE":"0"}):
            status,_,r=await self.call("/jarvis/v1/sync/state")
        self.assertEqual(status,503)
        self.assertEqual(r["error"],"jarvis_private_store_unavailable")

    async def test_missing_config_is_fail_closed(self):
        with patch.dict(os.environ,{"NEXTPLAN_JARVIS_ENABLED":"0"}):
            status,_,r=await self.call("/jarvis/v1/sync/state")
        self.assertEqual(status,503)
        self.assertEqual(r["error"],"jarvis_private_store_not_configured")


if __name__ == "__main__":
    unittest.main()
