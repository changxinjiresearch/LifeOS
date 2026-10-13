"""Browser-free NextPlan Issue inbox relay.

Uses existing LifeOS GitHub event builder and canonical state. This prevents a
risky dual-authority cutover during the v3 database migration.

Issue writes come only from the explicitly verified public inbox owner;
events use stable IDs so retries never create a second state mutation.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from . import server as legacy

REPO="changxinjiresearch/nextplan-command-inbox"
REPO_ID=1417272601
OWNER="changxinjiresearch"
EVENT_PREFIX="evt-nextplan-inbox-1417272601-"
VALID_STATUS={"planned","active","waiting","blocked","completed"}
SAFE_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
health={"state":"disabled","last_scan":None,"last_error":None,"scanned":0,
        "submitted":0,"verified":0,"pending":0}

def enabled():
    return os.getenv("NEXTPLAN_INBOX_RELAY_ENABLED","0")=="1"

def verify_issue(issue):
    if not isinstance(issue,dict) or issue.get("user",{}).get("login")!=OWNER:
        return None
    if "pull_request" in issue or type(issue.get("number")) is not int:
        return None
    if not str(issue.get("title","")).startswith("[NextPlan]"):
        return None
    if not isinstance(issue.get("body"),str) or len(issue["body"])>4096:
        raise ValueError("invalid_body")
    try:
        cmd=json.loads(issue["body"])
    except json.JSONDecodeError as e:
        raise ValueError("body_must_be_json") from e
    if not isinstance(cmd,dict) or cmd.get("version")!=3:
        raise ValueError("invalid_version")
    action=cmd.get("action")
    pid=cmd.get("project_id")
    if not isinstance(pid,str) or not SAFE_ID.fullmatch(pid):
        raise ValueError("invalid_project_id")
    if action=="update_project":
        if set(cmd)-{"version","operation_id","action","project_id","changes"}:
            raise ValueError("unsupported_keys")
        changes=cmd.get("changes")
        if not isinstance(changes,dict) or not changes or set(changes)-{"status","priority","next_action"}:
            raise ValueError("invalid_changes")
        if "status" in changes and changes["status"] not in VALID_STATUS:
            raise ValueError("invalid_status")
        if "priority" in changes and (type(changes["priority"]) is not int or changes["priority"] not in range(1,6)):
            raise ValueError("invalid_priority")
        if "next_action" in changes and (not isinstance(changes["next_action"],str) or len(changes["next_action"])>400):
            raise ValueError("invalid_next_action")
        return {"type":"project_updated","project_id":pid,"changes":changes}
    if action in {"complete_task","update_milestone"}:
        if set(cmd)-{"version","operation_id","action","project_id","task_id","milestone_id","status"}:
            raise ValueError("unsupported_keys")
        tid=cmd.get("task_id") or cmd.get("milestone_id")
        if not isinstance(tid,str) or not SAFE_ID.fullmatch(tid):
            raise ValueError("invalid_task_id")
        if action=="update_milestone":
            if cmd.get("status") not in VALID_STATUS:
                raise ValueError("invalid_status")
            return {"type":"milestone_status_changed","project_id":pid,
                    "milestone_id":tid,"status":cmd["status"]}
        return {"type":"task_completed","project_id":pid,"task_id":tid}
    if action=="create_task":
        if set(cmd)-{"version","operation_id","action","project_id","name","task_id"}:
            raise ValueError("unsupported_keys")
        name=cmd.get("name")
        if not isinstance(name,str) or not name.strip() or len(name)>160:
            raise ValueError("invalid_task_name")
        tid=cmd.get("task_id") or "task-inbox-"+str(issue["number"])
        if not isinstance(tid,str) or not SAFE_ID.fullmatch(tid):
            raise ValueError("invalid_task_id")
        return {"type":"task_created","project_id":pid,"task":{
                  "id":tid,"name":name.strip(),"status":"active"}}
    raise ValueError("unsupported_action")

def event_id(number):
    if type(number) is not int or number<=0:
        raise ValueError("invalid_issue_number")
    return EVENT_PREFIX+str(number)

async def github_issues():
    if not legacy.GITHUB_TOKEN:
        raise RuntimeError("legacy_github_token_missing")
    headers={"Authorization":"Bearer "+legacy.GITHUB_TOKEN,
             "Accept":"application/vnd.github+json",
             "X-GitHub-Api-Version":"2022-11-28",
             "User-Agent":"NextPlan-Issue-Relay/1.0"}
    out=[]
    async with httpx.AsyncClient(timeout=20) as client:
        repo=await client.get("https://api.github.com/repos/"+REPO,headers=headers)
        repo.raise_for_status()
        meta=repo.json()
        if meta.get("id")!=REPO_ID or meta.get("private") is not False or meta.get("full_name")!=REPO:
            raise RuntimeError("wrong_inbox_repository")
        for page in range(1,11):
            res=await client.get("https://api.github.com/repos/"+REPO+"/issues",
                  headers=headers,params={"state":"all","sort":"created","direction":"desc",
                                         "per_page":100,"page":page,"creator":OWNER})
            res.raise_for_status()
            rows=res.json()
            if not isinstance(rows,list):
                raise RuntimeError("bad_issues_response")
            out.extend(rows)
            if len(rows)<100:
                return list(reversed(out))
    raise RuntimeError("issue_scan_limit_reached")

async def read_event(eid):
    path=f"{legacy.EVENT_DIR}/{eid}.json"
    try:
        return await legacy._github_get_json(path)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code==404:
            return None
        raise

async def deliver(issue):
    event=verify_issue(issue)
    if event is None:
        return "ignored"
    eid=event_id(issue["number"])
    event.update({"id":eid,"at":issue.get("created_at") or datetime.now(timezone.utc).isoformat(),
                  "source":{"kind":"github_issue","via":"nextplan-direct-issue",
                            "repo_id":REPO_ID,"issue_number":issue["number"]},
                  "summary":"NextPlan Issue command "+str(issue["number"])})
    prior=await read_event(eid)
    if prior is not None:
        # Once submitted, an Issue edit must never change the original operation.
        if prior.get("type")!=event.get("type") or prior.get("project_id")!=event.get("project_id") or (
                prior.get("changes",prior.get("task",{}))!=event.get("changes",event.get("task",{}))):
            return "conflict"
        state=await legacy._state()
        if eid in state.get("system",{}).get("event_layer",{}).get("processed_event_ids",[]):
            return "verified"
        return "pending"
    state=await legacy._state()
    project=next((p for p in state.get("projects",[]) if p.get("id")==event["project_id"]),None)
    if not project:
        return "rejected_unknown_project"
    if event["type"] in {"task_completed","milestone_status_changed"}:
        mid=event.get("task_id",event.get("milestone_id"))
        if not any(m.get("id")==mid for m in project.get("milestones",[])):
            return "rejected_unknown_task"
    if event["type"]=="task_created":
        t=event["task"]
        if any(m.get("id")==t["id"] for m in project.get("milestones",[])):
            return "rejected_duplicate_task"
    try:
        await legacy._github_create_text(f"{legacy.EVENT_DIR}/{eid}.json",
                    json.dumps(event,ensure_ascii=False,indent=2)+"\n",
                    "NextPlan inbox: issue "+str(issue["number"]))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code!=422:
            raise
        prior=await read_event(eid)
        if prior is None or prior.get("project_id")!=event["project_id"] or prior.get("type")!=event["type"]:
            return "conflict"
    return "submitted"

async def scan_once():
    if not enabled():
        health["state"]="disabled"
        return dict(health)
    try:
        issues=await github_issues()
        counts={}
        for issue in issues:
            try:
                status=await deliver(issue)
            except (ValueError,TypeError) as exc:
                status="invalid"
            counts[status]=counts.get(status,0)+1
        health.update({"state":"ok","last_scan":datetime.now(timezone.utc).isoformat(),
            "last_error":None,"scanned":len(issues),
            "submitted":counts.get("submitted",0),
            "verified":counts.get("verified",0),
            "pending":counts.get("pending",0),
            "invalid":counts.get("invalid",0),
            "rejected":sum(v for k,v in counts.items() if k.startswith("rejected")),
            "conflicts":counts.get("conflict",0)})
    except Exception as exc:
        health.update({"state":"error","last_error":type(exc).__name__})
    return dict(health)

async def poll_loop():
    while True:
        if enabled():
            await scan_once()
        await asyncio.sleep(90)

async def receipt(number):
    eid=event_id(number)
    ev=await read_event(eid)
    if ev is None:
        return {"operation_id":eid,"status":"not_submitted"}
    state=await legacy._state()
    if eid in state.get("system",{}).get("event_layer",{}).get("processed_event_ids",[]):
        project=next((p for p in state.get("projects",[]) if p.get("id")==ev.get("project_id")),None)
        if not project:
            return {"operation_id":eid,"status":"unknown_target"}
        if ev["type"]=="project_updated":
            success=all(project.get(k)==v for k,v in ev.get("changes",{}).items())
        elif ev["type"]=="task_completed":
            success=any(t.get("id")==ev.get("task_id") and t.get("status")=="completed"
                        for t in project.get("milestones",[]))
        elif ev["type"]=="milestone_status_changed":
            success=any(t.get("id")==ev.get("milestone_id") and t.get("status")==ev.get("status")
                        for t in project.get("milestones",[]))
        elif ev["type"]=="task_created":
            success=any(t.get("id")==ev["task"]["id"] for t in project.get("milestones",[]))
        else:
            success=False
        return {"operation_id":eid,"status":"verified" if success else "postcondition_mismatch"}
    return {"operation_id":eid,"status":"submitted_unverified"}
