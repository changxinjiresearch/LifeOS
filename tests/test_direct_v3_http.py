"""HTTP-level tests: real ASGI request -> signed intake -> SQLite receipt."""
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mcp_server.direct_v3 import digest
from mcp_server import direct_v3_http as api

def request(path,method="GET",data=None,headers=None):
    raw=json.dumps(data,separators=(",",":")).encode() if data is not None else b""
    scope={"type":"http","path":path,"method":method,"headers":[
           (k.lower().encode(),v.encode()) for k,v in (headers or {}).items()]}
    out=[]
    async def receive():
        return {"type":"http.request","body":raw,"more_body":False}
    async def send(x):
        out.append(x)
    asyncio.run(api.handle(scope,receive,send))
    return out[0]["status"],json.loads(out[1]["body"])

class HttpAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        settings={
          "NEXTPLAN_DIRECT_ENABLED":"1","NEXTPLAN_DIRECT_TEST_MODE":"1",
          "NEXTPLAN_DIRECT_DB":str(Path(self.tmp.name)/"private.db"),
          "NEXTPLAN_DIRECT_ROOT":self.tmp.name,
          "NEXTPLAN_DIRECT_TOKEN":"a"*40,
          "NEXTPLAN_DIRECT_GITHUB_SECRET":"b"*40,
          "NEXTPLAN_DIRECT_GITHUB_REPO_ID":"123456",
          "NEXTPLAN_DIRECT_GITHUB_REPO":"testuser/nextplan-command-inbox",
          "NEXTPLAN_DIRECT_GITHUB_AUTHOR":"testuser"
        }
        self.env=patch.dict(os.environ,settings)
        self.env.start()
        api._store=None
        self.auth={"authorization":"Bearer "+"a"*40}
        self.doc={"projects":[{"id":"project-a","status":"active","name":"Test",
                                "milestones":[{"id":"milestone-1","status":"planned"}]}],
                  "events":[],"notes":[{"id":"one","content":"keep"}]}
        code,_=request(api.PREFIX+"/bootstrap","POST",
             {"state":self.doc,"confirmed":True,"sha256":digest(self.doc)},self.auth)
        self.assertEqual(code,200)

    def tearDown(self):
        api._store=None
        self.env.stop()
        self.tmp.cleanup()

    def test_auth_required(self):
        self.assertEqual(request(api.PREFIX+"/state")[0],401)
        with patch.dict(os.environ,{"NEXTPLAN_DIRECT_ENABLED":"0"}):
            self.assertEqual(request(api.PREFIX+"/status")[1]["status"],"disabled")

    def test_jarvis_direct_and_receipt(self):
        cmd={"version":3,"operation_id":"jarvis-00001","action":"update_project",
             "project_id":"project-a","changes":{"next_action":"Check evidence"}}
        code,out=request(api.PREFIX+"/command","POST",{"command":cmd},self.auth)
        self.assertEqual(code,200)
        self.assertEqual(out["status"],"applied")
        self.assertTrue(out["verified"])
        _,receipt=request(api.PREFIX+"/receipt/jarvis-00001",headers=self.auth)
        self.assertEqual(receipt["status"],"applied")
        _,snapshot=request(api.PREFIX+"/state",headers=self.auth)
        self.assertEqual(snapshot["state"]["projects"][0]["next_action"],"Check evidence")
        self.assertEqual(snapshot["state"]["notes"],self.doc["notes"])

    def test_signed_github_event_and_duplicate(self):
        issue={"action":"opened","repository":{"id":123456,"private":True,
                "name":"nextplan-command-inbox","owner":{"login":"testuser"}},
            "sender":{"login":"testuser"},"issue":{"number":10,
            "user":{"login":"testuser"},"body":json.dumps({
                "version":3,"operation_id":"chat-00001","action":"update_project",
                "project_id":"project-a","changes":{"status":"completed"}})}}
        sig="sha256="+hmac.new(("b"*40).encode(),
                       json.dumps(issue,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
        headers={"x-github-event":"issues","x-hub-signature-256":sig}
        self.assertEqual(request(api.PREFIX+"/github/webhook","POST",issue)[0],401)
        self.assertEqual(request(api.PREFIX+"/github/webhook","POST",issue,headers)[1]["status"],"applied")
        self.assertEqual(request(api.PREFIX+"/github/webhook","POST",issue,headers)[0],200)
        _,snapshot=request(api.PREFIX+"/state",headers=self.auth)
        self.assertEqual(snapshot["revision"],1)
        self.assertEqual(len(snapshot["state"]["events"]),1)

if __name__=="__main__":
    unittest.main()
