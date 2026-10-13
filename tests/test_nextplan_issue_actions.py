"""GitHub Actions inbox: isolated integration tests against real NextPlan builder."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from engine import build_state as legacy
from scripts import nextplan_issue_actions as actions

def issue(n,body,title="[NextPlan] test",author="changxinjiresearch"):
    return {"number":n,"title":title,"user":{"login":author},
            "created_at":"2026-10-14T01:00:00Z","body":json.dumps(body,ensure_ascii=False)}

def cmd(action="update_project",**args):
    return {"version":3,"action":action,"project_id":"project-test",**args}

class ActionsInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.state=self.root/"state.json"
        self.events=self.root/"events"/"inbox"
        self.events.mkdir(parents=True)
        self.receipts=self.root/"events"/"receipts"
        self.state.write_text(json.dumps({"schema_version":2,"system":{"event_layer":{
            "processed_event_ids":[]}},"projects":[{"id":"project-test",
              "name":"Sandbox","status":"active","priority":2,
              "milestones":[{"id":"milestone-one","name":"First","status":"active"}]}],
              "events":[]},ensure_ascii=False),encoding="utf-8")
        self.p1=patch.object(legacy,"STATE_PATH",self.state)
        self.p2=patch.object(legacy,"EVENT_DIR",self.events)
        self.p3=patch.object(actions,"RECEIPTS",self.receipts)
        for p in (self.p1,self.p2,self.p3):p.start()

    def tearDown(self):
        for p in (self.p3,self.p2,self.p1):p.stop()
        self.temp.cleanup()

    def snapshot(self):
        return json.loads(self.state.read_text(encoding="utf-8"))


    def test_empty_schedule_does_not_touch_state(self):
        original=self.state.read_bytes()
        self.assertEqual(actions.apply_issues([]),[])
        self.assertEqual(self.state.read_bytes(),original)
        self.assertFalse(self.receipts.exists())

    def test_submit_update_and_duplicate_exactly_once(self):
        ev=issue(21,cmd(changes={"status":"completed"}))
        first=actions.apply_issues([ev])
        second=actions.apply_issues([ev])
        self.assertEqual(first,[(21,"verified")])
        self.assertEqual(second,[(21,"verified")])
        self.assertEqual(self.snapshot()["projects"][0]["status"],"completed")
        self.assertTrue((self.events/"evt-nextplan-gh-issue-21.json").exists())
        self.assertEqual(len(list(self.events.glob("evt-nextplan-gh-issue-21.json"))),1)

    def test_wrong_project_and_malformed_command_fail_closed(self):
        a=issue(22,{"version":3,"action":"update_project",
                       "project_id":"does-not-exist","changes":{"status":"completed"}})
        b=issue(23,{"version":3,"action":"delete_project","project_id":"project-test"})
        self.assertEqual(actions.apply_issues([a,b]),[(22,"rejected"),(23,"rejected")])
        self.assertEqual(self.snapshot()["projects"][0]["status"],"active")
        self.assertEqual(len(list(self.events.glob("evt-nextplan-gh-issue-*.json"))),0)

    def test_task_create_and_complete(self):
        add=issue(24,cmd("create_task",name="New milestone"))
        completed=issue(25,cmd("complete_task",task_id="task-inbox-24"))
        self.assertEqual(actions.apply_issues([add,completed]),[(24,"verified"),(25,"verified")])
        ms=self.snapshot()["projects"][0]["milestones"]
        self.assertEqual(next(x for x in ms if x["id"]=="task-inbox-24")["status"],"completed")

    def test_no_untrusted_author_or_unlabelled_issue(self):
        a=issue(26,cmd(changes={"status":"completed"}),author="stranger")
        b=issue(27,cmd(changes={"status":"completed"}),title="Random discussion")
        self.assertEqual(actions.apply_issues([a,b]),[])
        self.assertEqual(self.snapshot()["projects"][0]["status"],"active")

    def test_edits_after_receipt_do_not_reexecute(self):
        original=issue(28,cmd(changes={"status":"completed"}))
        changed=issue(28,cmd(changes={"status":"blocked"}))
        actions.apply_issues([original])
        self.assertEqual(actions.apply_issues([changed]),[(28,"verified")])
        self.assertEqual(self.snapshot()["projects"][0]["status"],"completed")

    def test_inbox_repo_identity_is_strict(self):
        with patch.object(actions,"request",side_effect=[
            {"id":999,"full_name":actions.REPO,"private":False}]):
            with self.assertRaises(RuntimeError):
                actions.list_issues()

    def test_project_create_never_overwrites_existing(self):
        first=issue(30,{"version":3,"action":"create_project","project_id":"project-created",
                       "name":"Created","category":"Work"})
        second=issue(31,{"version":3,"action":"create_project","project_id":"project-created",
                        "name":"Created","category":"Work"})
        self.assertEqual(actions.apply_issues([first,second]),[(30,"verified"),(31,"rejected")])
        self.assertEqual(len(self.snapshot()["projects"]),2)

if __name__=="__main__":
    unittest.main()
