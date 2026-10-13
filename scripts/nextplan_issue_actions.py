#!/usr/bin/env python3
"""No-hosting, durable GitHub Issues -> NextPlan state sync.

Runs in GitHub Actions inside the LifeOS repository, using the existing state
builder and one atomic Git commit for event files, receipts and canonical state.
GitHub's GITHUB_TOKEN writes stay within LifeOS; the inbox is PUBLIC and is
read-only to this program. Never execute Issue text.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import build_state as state_engine
from engine import build_state_v3

REPO = "changxinjiresearch/nextplan-command-inbox"
REPO_ID = 1417272601
AUTHOR = "changxinjiresearch"
EVENT_PREFIX = "evt-nextplan-gh-issue-"
IDS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
STATUSES = {"planned", "active", "waiting", "blocked", "completed"}
RECEIPTS = ROOT / "events" / "receipts"


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def request(url: str):
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"User-Agent": "NextPlan-Actions-Inbox/1.0",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25) as res:
        return json.load(res)


def list_issues():
    meta = request("https://api.github.com/repos/" + REPO)
    if (meta.get("id") != REPO_ID or meta.get("full_name") != REPO
            or meta.get("private") is not False):
        raise RuntimeError("inbox_repository_identity_mismatch")
    results = []
    for page in range(1, 11):
        url = (f"https://api.github.com/repos/{REPO}/issues"
               f"?state=all&per_page=100&page={page}&sort=created&direction=desc&creator={AUTHOR}")
        items = request(url)
        if not isinstance(items, list):
            raise RuntimeError("unexpected_issues_response")
        results.extend(items)
        if len(items) < 100:
            return sorted(results, key=lambda x: x.get("number", 0))
    raise RuntimeError("inbox_capacity_exceeded")


def _name(text, key, maximum=160):
    if not isinstance(text, str) or not text.strip() or len(text)>maximum:
        raise ValueError("invalid_" + key)
    return text.strip()


def _id(text, key):
    if not isinstance(text,str) or not IDS.fullmatch(text):
        raise ValueError("invalid_" + key)
    return text


def _date(value):
    if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):
        raise ValueError("invalid_date_format")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid_date") from exc
    return value


def parse_issue(issue):
    """Return (event, canonical Issue body digest), or None for non-command Issues."""
    if not isinstance(issue,dict) or "pull_request" in issue:
        return None
    if (issue.get("user") or {}).get("login") != AUTHOR:
        return None
    if not str(issue.get("title","")).startswith("[NextPlan]"):
        return None
    number = issue.get("number")
    if type(number) is not int or number < 1:
        raise ValueError("invalid_issue_number")
    raw = issue.get("body")
    if not isinstance(raw,str) or len(raw)>4096:
        raise ValueError("invalid_issue_body")
    try:
        cmd=json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(cmd,dict) or cmd.get("version")!=3:
        raise ValueError("invalid_command_version")
    action=cmd.get("action")
    eid=EVENT_PREFIX+str(number)
    project_id=_id(cmd.get("project_id"),"project_id")
    base={
        "id":eid, "at":issue.get("created_at") or iso_now(),
        "project_id":project_id,
        "summary":f"Verified NextPlan command #{number}",
        "source":{"kind":"github_issue","via":"nextplan-actions-inbox","issue_number":number,
                  "repository":REPO}
    }
    if action=="update_project":
        permitted={"version","operation_id","action","project_id","changes"}
        changes=cmd.get("changes")
        if not isinstance(changes,dict) or not changes or set(changes)-{"status","priority","next_action","progress"}:
            raise ValueError("invalid_changes")
        if "status" in changes and changes["status"] not in STATUSES:
            raise ValueError("invalid_status")
        if "priority" in changes and (type(changes["priority"]) is not int or not 1 <= changes["priority"] <= 5):
            raise ValueError("invalid_priority")
        if "next_action" in changes and (not isinstance(changes["next_action"],str) or len(changes["next_action"])>400):
            raise ValueError("invalid_next_action")
        if "progress" in changes and (type(changes["progress"]) not in (int,float)
            or not 0<=changes["progress"]<=100):
            raise ValueError("invalid_progress")
        event={"type":"project_updated","changes":changes}
    elif action=="create_task":
        permitted={"version","operation_id","action","project_id","name","task_id"}
        name=_name(cmd.get("name"),"task_name")
        task_id=_id(cmd.get("task_id") or "task-inbox-"+str(number),"task_id")
        event={"type":"task_created","task":{"id":task_id,"name":name,"status":"active"}}
    elif action=="complete_task":
        permitted={"version","operation_id","action","project_id","task_id"}
        event={"type":"task_completed","task_id":_id(cmd.get("task_id"),"task_id")}
    elif action=="update_milestone":
        permitted={"version","operation_id","action","project_id","milestone_id","status"}
        if cmd.get("status") not in STATUSES:
            raise ValueError("invalid_status")
        event={"type":"milestone_status_changed",
               "milestone_id":_id(cmd.get("milestone_id"),"milestone_id"),
               "status":cmd["status"]}
    elif action=="update_task":
        permitted={"version","operation_id","action","project_id","task_id","changes"}
        tid=_id(cmd.get("task_id"),"task_id")
        changes=cmd.get("changes")
        if not isinstance(changes,dict) or not changes or set(changes)-{"status","name","deadline","prep_days"}:
            raise ValueError("invalid_task_changes")
        payload={"type":"task_updated","task_id":tid}
        if "status" in changes:
            if changes["status"] not in STATUSES:
                raise ValueError("invalid_status")
            payload["status"]=changes["status"]
        if "name" in changes:
            payload["name"]=_name(changes["name"],"task_name")
        if "deadline" in changes:
            payload["deadline"]=_date(changes["deadline"])
        if "prep_days" in changes:
            if type(changes["prep_days"]) is not int or not 0<=changes["prep_days"]<=90:
                raise ValueError("invalid_prep_days")
            payload["prep_days"]=changes["prep_days"]
        event=payload
    elif action=="set_deadline":
        permitted={"version","operation_id","action","project_id","deadline_id","title","date","task_id"}
        did=_id(cmd.get("deadline_id") or "deadline-inbox-"+str(number),"deadline_id")
        title=_name(cmd.get("title"),"deadline_title")
        due=_date(cmd.get("date"))
        taskid=cmd.get("task_id")
        deadline={"id":did,"project_id":project_id,"title":title,"date":due}
        if taskid is not None:
            deadline["task_id"]=_id(taskid,"task_id")
        event={"type":"deadline_set","deadline":deadline}
    elif action=="remove_deadline":
        permitted={"version","operation_id","action","project_id","deadline_id"}
        event={"type":"deadline_removed","deadline_id":_id(cmd.get("deadline_id"),"deadline_id")}
    elif action in {"request_delete_project","request_delete_task"}:
        permitted={"version","operation_id","action","project_id","expected_name"}
        expected=_name(cmd.get("expected_name"),"expected_name")
        event={"type":"deletion_requested","expected_name":expected,
               "delete_kind":"project" if action=="request_delete_project" else "task"}
        if action=="request_delete_task":
            permitted.add("task_id")
            event["task_id"]=_id(cmd.get("task_id"),"task_id")
    elif action=="confirm_delete":
        permitted={"version","operation_id","action","project_id","request_issue",
                   "expected_name","confirmation","task_id"}
        ri=cmd.get("request_issue")
        if type(ri) is not int or ri<1 or ri>=number:
            raise ValueError("invalid_request_issue")
        expected=_name(cmd.get("expected_name"),"expected_name")
        phrase=cmd.get("confirmation")
        if phrase!=("CONFIRM DELETE "+str(ri)):
            raise ValueError("confirmation_phrase_mismatch")
        event={"type":"deletion_confirmation","request_issue":ri,"expected_name":expected,
               "confirmation":phrase}
        if "task_id" in cmd:
            event["task_id"]=_id(cmd["task_id"],"task_id")
    elif action=="create_project":
        permitted={"version","operation_id","action","project_id","name","category","next_action","priority"}
        name=_name(cmd.get("name"),"project_name")
        category=_name(cmd.get("category","其他"),"category",80)
        nxt=cmd.get("next_action","")
        if not isinstance(nxt,str) or len(nxt)>400:
            raise ValueError("invalid_next_action")
        priority=cmd.get("priority",3)
        if type(priority) is not int or priority not in range(1,6):
            raise ValueError("invalid_priority")
        event={"type":"project_created","project":{"id":project_id,"name":name,
                 "category":category,"status":"active","priority":priority,
                 "next_action":nxt,"milestones":[]}}
    else:
        raise ValueError("unsupported_action")
    if set(cmd)-permitted:
        raise ValueError("unsupported_keys")
    base.update(event)
    bodyhash=hashlib.sha256(raw.encode()).hexdigest()
    return base,bodyhash


def check_target(state,event):
    pid=event["project_id"]
    projects=[p for p in state.get("projects",[]) if p.get("id")==pid]
    if event["type"]=="project_created":
        if projects or any(p.get("name")==event["project"]["name"] for p in state.get("projects",[])):
            raise ValueError("project_already_exists")
        return
    if len(projects)!=1:
        raise ValueError("unknown_or_ambiguous_project")
    project=projects[0]
    if event["type"]=="deletion_requested":
        if event["delete_kind"]=="project":
            if project.get("name")!=event["expected_name"]:
                raise ValueError("project_name_mismatch")
        else:
            tasks=[m for m in project.get("milestones",[]) if m.get("id")==event["task_id"]]
            if len(tasks)!=1 or tasks[0].get("name")!=event["expected_name"]:
                raise ValueError("task_name_mismatch")
    if event["type"]=="project_deleted":
        if project.get("name")!=event["expected_name"]:
            raise ValueError("project_name_mismatch")
    if event["type"]=="task_deleted":
        tasks=[m for m in project.get("milestones",[]) if m.get("id")==event["task_id"]]
        if len(tasks)!=1 or tasks[0].get("name")!=event["expected_name"]:
            raise ValueError("task_name_mismatch")
    if event["type"] in {"task_completed","milestone_status_changed","task_updated"}:
        mid=event.get("task_id") or event.get("milestone_id")
        if not any(m.get("id")==mid for m in project.get("milestones",[])):
            raise ValueError("unknown_task")
    if event["type"]=="deadline_removed":
        if len([d for d in state.get("deadlines",[]) if d.get("id")==event["deadline_id"] and d.get("project_id")==pid])!=1:
            raise ValueError("unknown_or_ambiguous_deadline")
    if event["type"]=="deadline_set":
        dl=event["deadline"]
        if any(d.get("id")==dl["id"] and (d.get("project_id")!=pid or d.get("title")!=dl["title"])
               for d in state.get("deadlines",[])):
            raise ValueError("deadline_id_conflict")
        if "task_id" in dl and not any(m.get("id")==dl["task_id"] for m in project.get("milestones",[])):
            raise ValueError("unknown_deadline_task")
    if event["type"]=="task_created":
        item=event["task"]
        if any(m.get("id")==item["id"] or m.get("name")==item["name"]
               for m in project.get("milestones",[])):
            raise ValueError("task_already_exists")


def verify(state,event):
    events=set(state.get("system",{}).get("event_layer",{}).get("processed_event_ids",[]))
    if event["id"] not in events:
        return False
    kind=event["type"]
    project=next((p for p in state.get("projects",[])
                  if p.get("id")==event["project_id"]),None)
    if kind=="project_deleted":
        return project is None and not any(d.get("project_id")==event["project_id"]
                 for d in state.get("deadlines",[]))
    if project is None:
        return False
    if kind=="task_deleted":
        return not any(m.get("id")==event["task_id"] for m in project.get("milestones",[]))
    if kind=="project_updated":
        return all(project.get(k)==v for k,v in event["changes"].items())
    if kind=="project_created":
        return project.get("name")==event["project"]["name"]
    if kind=="task_created":
        return any(m.get("id")==event["task"]["id"] for m in project.get("milestones",[]))
    if kind=="deadline_set":
        return any(all(d.get(k)==v for k,v in event["deadline"].items()) for d in state.get("deadlines",[]))
    if kind=="deadline_removed":
        return not any(d.get("id")==event["deadline_id"] for d in state.get("deadlines",[]))
    if kind=="task_updated":
        return any(m.get("id")==event["task_id"] and all(
            m.get(k)==event[k] for k in ("status","name","deadline","prep_days") if k in event
        ) for m in project.get("milestones",[]))
    if kind in {"task_completed","milestone_status_changed"}:
        mid=event.get("task_id") or event.get("milestone_id")
        status="completed" if kind=="task_completed" else event.get("status")
        return any(m.get("id")==mid and m.get("status")==status
                   for m in project.get("milestones",[]))
    return False


def receipt_path(number):
    return RECEIPTS / f"issue-{number}.json"


def write_receipt(number, status, bodyhash, reason="", **extra):
    RECEIPTS.mkdir(parents=True,exist_ok=True)
    result={"issue_number":number,"status":status,"command_sha256":bodyhash,
            "checked_at":iso_now(),**extra}
    if reason:
        result["reason"]=reason
    state_engine.save_json(receipt_path(number),result)
    return result


def catch_up_existing_events():
    """Only run the state builder when some event actually needs applying.

    The legacy builder updates its last_build_at timestamp on every invocation.
    Running it on a schedule with no work would create a meaningless Git commit
    every five minutes.
    """
    state=state_engine.load_json(state_engine.STATE_PATH)
    processed=set(state.get("system",{}).get("event_layer",{}).get("processed_event_ids",[]))
    for path in sorted(state_engine.EVENT_DIR.glob("*.json")):
        event=state_engine.load_json(path)
        if event.get("id") not in processed:
            build_state_v3.main()
            return True
    return False


def apply_issues(issues):
    """Apply each new command through the actual production event builder."""
    results=[]
    catch_up_existing_events()
    for issue in issues:
        number=issue.get("number")
        if type(number) is not int:
            continue
        oldfile=receipt_path(number)
        try:
            parsed=parse_issue(issue)
        except (ValueError,TypeError) as exc:
            if str(issue.get("title","")).startswith("[NextPlan]") and (issue.get("user") or {}).get("login")==AUTHOR:
                bodyhash=hashlib.sha256(str(issue.get("body","")).encode()).hexdigest()
                if not oldfile.exists():
                    write_receipt(number,"rejected",bodyhash,reason=str(exc))
                results.append((number,"rejected"))
            continue
        if parsed is None:
            continue
        event, bodyhash=parsed
        if oldfile.exists():
            receipt=state_engine.load_json(oldfile)
            if receipt.get("command_sha256")!=bodyhash:
                # Do not replay edited commands. Existing receipt remains source of truth.
                print(f"issue #{number}: edited command ignored")
            results.append((number,receipt.get("status","unknown")))
            continue
        current=state_engine.load_json(state_engine.STATE_PATH)
        try:
            if event["type"]=="deletion_confirmation":
                source_number=event["request_issue"]
                request_file=receipt_path(source_number)
                if not request_file.exists():
                    raise ValueError("delete_request_not_processed")
                req=state_engine.load_json(request_file)
                if req.get("status")!="pending_confirmation":
                    raise ValueError("delete_request_not_pending")
                requested=req.get("deletion") or {}
                if requested.get("project_id")!=event["project_id"] or (
                    requested.get("expected_name")!=event["expected_name"]) or (
                    requested.get("task_id")!=event.get("task_id")):
                    raise ValueError("delete_confirmation_target_mismatch")
                event["type"]="project_deleted" if requested["delete_kind"]=="project" else "task_deleted"
                event.pop("request_issue",None)
                event.pop("confirmation",None)
            check_target(current,event)
            if event["type"]=="deletion_requested":
                write_receipt(number,"pending_confirmation",bodyhash,
                              deletion={k:event[k] for k in ("project_id","expected_name","delete_kind")
                                        if k in event} | ({"task_id":event["task_id"]}
                                        if "task_id" in event else {}))
                results.append((number,"pending_confirmation"))
                continue
        except ValueError as exc:
            write_receipt(number,"rejected",bodyhash,reason=str(exc))
            results.append((number,"rejected"))
            continue
        event_path=state_engine.EVENT_DIR / (event["id"]+".json")
        if event_path.exists():
            prior=state_engine.load_json(event_path)
            if prior!=event:
                raise RuntimeError("event_id_collision")
        else:
            event_path.parent.mkdir(parents=True,exist_ok=True)
            state_engine.save_json(event_path,event)
        build_state_v3.main()
        newstate=state_engine.load_json(state_engine.STATE_PATH)
        if not verify(newstate,event):
            raise RuntimeError("postcondition_mismatch")
        write_receipt(number,"verified",bodyhash,event_id=event["id"])
        results.append((number,"verified"))
        # Unexpected errors leave workflow failed so GitHub Actions retries on next
        # scheduled run. They are NOT falsely recorded as successful.
    return results


def main():
    issues=list_issues()
    results=apply_issues(issues)
    print(json.dumps({"total_issues_scanned":len(issues),"results":results},
                     ensure_ascii=False))


if __name__=="__main__":
    main()
