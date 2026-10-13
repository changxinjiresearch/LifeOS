"""Deterministic Issue inbox relay tests; no network writes."""
import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock,patch
from mcp_server import inbox_relay_v1 as relay

def issue(n=10,body=None):
    return {"number":n,"title":"[NextPlan] Update status",
            "user":{"login":"changxinjiresearch"},
            "created_at":"2026-10-14T00:00:00Z",
            "body":json.dumps(body or {"version":3,"action":"update_project","project_id":"project-a",
                   "changes":{"status":"completed"}})}

def state(status="active",processed=None):
    return {"projects":[{"id":"project-a","status":status,"milestones":[{"id":"task-a","name":"Task","status":"active"}]}],
            "system":{"event_layer":{"processed_event_ids":processed or []}}}

class InboxRelay(unittest.TestCase):
    def test_valid_project_status(self):
        e=relay.verify_issue(issue())
        self.assertEqual(e["type"],"project_updated")
        self.assertEqual(e["changes"]["status"],"completed")

    def test_ignore_other_author(self):
        x=issue()
        x["user"]["login"]="malicious"
        self.assertIsNone(relay.verify_issue(x))

    def test_invalid_and_destructive_rejected(self):
        for bad in [
            {"version":3,"action":"delete_project","project_id":"project-a"},
            {"version":3,"action":"update_project","project_id":"project-a",
             "changes":{"token":"secret"}},
            {"version":3,"action":"update_project","project_id":"project-a",
             "changes":{"status":"unverified"}},
            {"version":3,"action":"create_task","project_id":"project-a","name":""},
        ]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                relay.verify_issue(issue(body=bad))

    def test_task_commands(self):
        x={"version":3,"action":"create_task","project_id":"project-a","name":"New task"}
        e=relay.verify_issue(issue(5,x))
        self.assertEqual(e["task"]["id"],"task-inbox-5")
        x={"version":3,"action":"complete_task","project_id":"project-a","task_id":"task-a"}
        self.assertEqual(relay.verify_issue(issue(5,x))["type"],"task_completed")
        x={"version":3,"action":"update_milestone","project_id":"project-a","milestone_id":"task-a","status":"waiting"}
        self.assertEqual(relay.verify_issue(issue(5,x))["status"],"waiting")

    def test_exactly_once_event_key_when_issues_repeated(self):
        async def run():
            with patch.object(relay,"read_event",new_callable=AsyncMock,side_effect=[None,
                    {"type":"project_updated","project_id":"project-a","changes":{"status":"completed"}}]), \
                 patch.object(relay.legacy,"_state",new_callable=AsyncMock,
                              side_effect=[state(),state("completed",[relay.event_id(10)])]), \
                 patch.object(relay.legacy,"_github_create_text",new_callable=AsyncMock) as create:
                self.assertEqual(await relay.deliver(issue()),"submitted")
                self.assertEqual(await relay.deliver(issue()),"verified")
                self.assertEqual(create.await_count,1)
                self.assertTrue(relay.event_id(10) in create.await_args.args[0])
        asyncio.run(run())

    def test_duplicate_edited_issue_does_not_replay(self):
        async def run():
            with patch.object(relay,"read_event",new_callable=AsyncMock,
                  return_value={"type":"project_updated","project_id":"project-a",
                                "changes":{"status":"completed"}}),\
                 patch.object(relay.legacy,"_github_create_text",new_callable=AsyncMock) as create:
                x=issue(body={"version":3,"action":"update_project","project_id":"project-a",
                              "changes":{"status":"blocked"}})
                self.assertEqual(await relay.deliver(x),"conflict")
                self.assertEqual(create.await_count,0)
        asyncio.run(run())

    def test_no_wrong_project_mutation(self):
        async def run():
            with patch.object(relay,"read_event",new_callable=AsyncMock,return_value=None),\
                 patch.object(relay.legacy,"_state",new_callable=AsyncMock,return_value=state()),\
                 patch.object(relay.legacy,"_github_create_text",new_callable=AsyncMock) as create:
                x=issue(body={"version":3,"action":"update_project","project_id":"wrong-id",
                              "changes":{"status":"completed"}})
                self.assertEqual(await relay.deliver(x),"rejected_unknown_project")
                self.assertEqual(create.await_count,0)
        asyncio.run(run())

if __name__=="__main__":
    unittest.main()
