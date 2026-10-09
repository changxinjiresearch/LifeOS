"""Safety regression tests for the actual Direct v3 module in this repository."""
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from mcp_server.direct_v3 import DirectStore,DirectError,validated,digest,valid_signature,parse_github_issue

def initial():
    return {"schema_version":2,"system":{"name":"NextPlan"},"events":[],"notes":[{"id":"note-1"}],
      "projects":[{"id":"project-a","name":"Research","status":"active","milestones":[{"id":"m-1","status":"active"}]},
                  {"id":"project-b","name":"Other","status":"planned"}]}

def cmd(op="write-0001",changes=None,project="project-a"):
    return {"version":3,"operation_id":op,"action":"update_project","project_id":project,
            "changes":{"status":"completed"} if changes is None else changes}

class DirectV3Safety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"state.db"
        self.s=DirectStore(self.db)
        self.s.bootstrap(initial(),True,digest(initial()))

    def tearDown(self):
        self.tmp.cleanup()

    def send(self,x):
        return self.s.enqueue(x,"jarvis_direct","jarvis:"+x["operation_id"])

    def test_migration_preserves_complete_document(self):
        self.assertEqual(self.s.snapshot()["state"],initial())
        with self.assertRaises(DirectError):
            self.s.bootstrap(initial(),True,digest(initial()))

    def test_invalid_hash_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            other=DirectStore(Path(d)/"a.sqlite")
            with self.assertRaises(DirectError):
                other.bootstrap(initial(),True,"wrong")

    def test_update_and_receipt(self):
        self.send(cmd())
        out=self.s.process("write-0001")
        self.assertEqual(out["status"],"applied")
        self.assertTrue(out["verified"])
        self.assertEqual(self.s.receipt("write-0001")["status"],"applied")
        new=self.s.snapshot()["state"]
        self.assertEqual(new["projects"][0]["status"],"completed")
        self.assertEqual(new["projects"][0]["milestones"],initial()["projects"][0]["milestones"])
        self.assertEqual(new["notes"],initial()["notes"])

    def test_duplicate_delivery_does_not_reapply(self):
        for _ in range(10):
            self.send(cmd())
            self.s.process("write-0001")
        self.assertEqual(self.s.snapshot()["revision"],1)
        self.assertEqual(len(self.s.snapshot()["state"]["events"]),1)

    def test_idempotency_collision_fails(self):
        self.send(cmd())
        with self.assertRaises(DirectError):
            self.send(cmd(changes={"status":"blocked"}))

    def test_unknown_target_does_not_change(self):
        self.send(cmd(project="missing"))
        self.assertEqual(self.s.process("write-0001")["status"],"rejected")
        self.assertEqual(self.s.snapshot()["revision"],0)

    def test_revision_conflict(self):
        a=cmd("write-0002",changes={"status":"blocked"})
        self.send(cmd())
        self.send(a)
        self.assertEqual(self.s.process("write-0001")["status"],"applied")
        self.assertEqual(self.s.process("write-0002")["status"],"conflict")
        self.assertEqual(self.s.snapshot()["state"]["projects"][0]["status"],"completed")

    def test_delete_requires_authenticated_second_confirmation(self):
        x={"version":3,"operation_id":"delete-0001","action":"delete_project","project_id":"project-a"}
        self.assertEqual(self.send(x)["status"],"needs_confirmation")
        self.assertEqual(self.s.process("delete-0001")["status"],"needs_confirmation")
        self.assertEqual(len(self.s.snapshot()["state"]["projects"]),2)
        self.assertEqual(self.s.process("delete-0001",True)["status"],"applied")
        self.assertEqual(len(self.s.snapshot()["state"]["projects"]),1)

    def test_restart_resumes_accepted_command(self):
        self.send(cmd())
        other=DirectStore(self.db)
        self.assertEqual(other.process_pending()[0]["status"],"applied")
        self.assertEqual(other.receipt("write-0001")["status"],"applied")

    def test_strict_schema(self):
        for change in ({"unsafe":"payload"},{"progress":True},{"progress":101},
                       {"priority":True},{"status":"unknown"},{"next_action":1}):
            with self.subTest(change=change),self.assertRaises(DirectError):
                validated(cmd(changes=change))

    def test_webhook_signature(self):
        data=b"private"
        secret="z"*40
        sig="sha256="+hmac.new(secret.encode(),data,hashlib.sha256).hexdigest()
        self.assertTrue(valid_signature(data,sig,secret))
        self.assertFalse(valid_signature(data+b"!",sig,secret))

    def test_git_hub_rejects_public_or_other_author(self):
        ev={"action":"opened","repository":{"id":123456,"private":True,
              "name":"nextplan-command-inbox","owner":{"login":"testuser"}},
            "sender":{"login":"testuser"},"issue":{"number":12,"user":{"login":"testuser"},
            "body":json.dumps(cmd())}}
        opts={"repo_id":123456,"owner":"testuser","name":"nextplan-command-inbox","author":"testuser"}
        result=parse_github_issue(ev,**opts)
        self.assertEqual(result[0]["operation_id"],"github:123456:12")
        ev["repository"]["private"]=False
        with self.assertRaises(DirectError):
            parse_github_issue(ev,**opts)
        ev["repository"]["private"]=True
        ev["sender"]["login"]="other"
        with self.assertRaises(DirectError):
            parse_github_issue(ev,**opts)
