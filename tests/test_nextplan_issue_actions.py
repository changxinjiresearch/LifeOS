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


    def test_progress_and_task_updates(self):
        commands=[
            issue(110,cmd(changes={"progress":65,"priority":4})),
            issue(111,cmd("update_task",task_id="milestone-one",
                          changes={"status":"waiting","name":"Renamed","deadline":"2026-11-30","prep_days":7}))
        ]
        self.assertEqual(actions.apply_issues(commands),[(110,"verified"),(111,"verified")])
        p=self.snapshot()["projects"][0]
        self.assertEqual(p["progress"],65)
        self.assertEqual(p["milestones"][0]["name"],"Renamed")
        self.assertEqual(p["milestones"][0]["deadline"],"2026-11-30")

    def test_deadline_create_and_removal(self):
        create=issue(112,cmd("set_deadline",title="Safe testing",date="2026-12-31"))
        remove=issue(113,cmd("remove_deadline",deadline_id="deadline-inbox-112"))
        self.assertEqual(actions.apply_issues([create,remove]),[(112,"verified"),(113,"verified")])
        self.assertFalse(any(d.get("id")=="deadline-inbox-112" for d in self.snapshot()["deadlines"]))

    def test_reject_invalid_date_invalid_task_and_invalid_progress(self):
        examples=[
            cmd("set_deadline",title="Wrong",date="2026-02-31"),
            cmd("remove_deadline",deadline_id="missing"),
            cmd("update_task",task_id="missing",changes={"status":"completed"}),
            cmd(changes={"progress":True}),
            cmd(changes={"progress":101}),
            cmd("update_task",task_id="milestone-one",changes={"prep_days":True})
        ]
        results=actions.apply_issues([issue(120+i,c) for i,c in enumerate(examples)])
        self.assertEqual([x[1] for x in results],["rejected"]*len(examples))
        self.assertEqual(self.snapshot()["projects"][0]["status"],"active")

    def test_two_issue_task_deletion_cannot_execute_without_confirmation(self):
        request=issue(130,cmd("request_delete_task",task_id="milestone-one",expected_name="First"))
        self.assertEqual(actions.apply_issues([request]),[(130,"pending_confirmation")])
        self.assertEqual(len(self.snapshot()["projects"][0]["milestones"]),1)
        wrong=issue(131,cmd("confirm_delete",request_issue=130,task_id="milestone-one",
                             expected_name="Wrong",confirmation="CONFIRM DELETE 130"))
        self.assertEqual(actions.apply_issues([wrong]),[(131,"rejected")])
        self.assertEqual(len(self.snapshot()["projects"][0]["milestones"]),1)
        correct=issue(132,cmd("confirm_delete",request_issue=130,task_id="milestone-one",
                             expected_name="First",confirmation="CONFIRM DELETE 130"))
        self.assertEqual(actions.apply_issues([correct]),[(132,"verified")])
        self.assertEqual(len(self.snapshot()["projects"][0]["milestones"]),0)
        self.assertEqual(actions.apply_issues([correct]),[(132,"verified")])

    def test_two_issue_project_delete_only_sandbox(self):
        create=issue(133,{"version":3,"action":"create_project","project_id":"tmp-demo-133",
                          "name":"Sandbox 133","category":"Test"})
        ask=issue(134,{"version":3,"action":"request_delete_project",
                       "project_id":"tmp-demo-133","expected_name":"Sandbox 133"})
        confirm=issue(135,{"version":3,"action":"confirm_delete",
                           "project_id":"tmp-demo-133","request_issue":134,
                           "expected_name":"Sandbox 133",
                           "confirmation":"CONFIRM DELETE 134"})
        self.assertEqual(actions.apply_issues([create,ask,confirm]),
                         [(133,"verified"),(134,"pending_confirmation"),(135,"verified")])
        self.assertEqual(len(self.snapshot()["projects"]),1)

    def test_confirmation_request_must_preexist_and_match(self):
        premature=issue(140,{"version":3,"action":"confirm_delete",
                             "project_id":"project-test","request_issue":139,
                             "expected_name":"Sandbox","confirmation":"CONFIRM DELETE 139"})
        self.assertEqual(actions.apply_issues([premature]),[(140,"rejected")])
        self.assertEqual(len(self.snapshot()["projects"]),1)

    def test_large_batch_deduplication_and_restart(self):
        commands=[issue(200+i,cmd(changes={"priority":i%5+1})) for i in range(100)]
        res=actions.apply_issues(commands)
        self.assertEqual(len(res),100)
        self.assertTrue(all(x[1]=="verified" for x in res))
        before=self.snapshot()
        self.assertEqual(actions.apply_issues(commands),res)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(len(list(self.events.glob("evt-nextplan-gh-issue-*.json"))),100)
        self.assertEqual(len(list(self.receipts.glob("issue-*.json"))),100)

    def test_builder_failure_never_gives_verified_receipt(self):
        from unittest.mock import patch as p
        command=issue(400,cmd(changes={"status":"completed"}))
        with p.object(actions.build_state_v3,"main",side_effect=RuntimeError("simulated disk error")):
            with self.assertRaises(RuntimeError):
                actions.apply_issues([command])
        self.assertFalse(actions.receipt_path(400).exists())
        self.assertEqual(self.snapshot()["projects"][0]["status"],"active")
        self.assertEqual(actions.apply_issues([command]),[(400,"verified")])


if __name__=="__main__":
    unittest.main()
