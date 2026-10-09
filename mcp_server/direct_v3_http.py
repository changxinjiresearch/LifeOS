"""Opt-in NextPlan Direct v3 ASGI gateway with private-store safety gates."""
from __future__ import annotations
import asyncio
import json
import os
import secrets
from pathlib import Path
from urllib.request import Request,urlopen
from .direct_v3 import DirectError,DirectStore,valid_signature,parse_github_issue

PREFIX="/direct/v3"
_store=None
health={"last_success":None,"last_error":None}

def configured():
    names=("NEXTPLAN_DIRECT_DB","NEXTPLAN_DIRECT_ROOT","NEXTPLAN_DIRECT_TOKEN",
           "NEXTPLAN_DIRECT_GITHUB_SECRET","NEXTPLAN_DIRECT_GITHUB_REPO_ID",
           "NEXTPLAN_DIRECT_GITHUB_REPO","NEXTPLAN_DIRECT_GITHUB_AUTHOR")
    return (os.getenv("NEXTPLAN_DIRECT_ENABLED")=="1" and all(os.getenv(k) for k in names)
       and len(os.getenv("NEXTPLAN_DIRECT_TOKEN",""))>=32
       and len(os.getenv("NEXTPLAN_DIRECT_GITHUB_SECRET",""))>=32)

def store():
    global _store
    if not configured():
        raise DirectError("not_configured")
    root=Path(os.environ["NEXTPLAN_DIRECT_ROOT"]).resolve(strict=True)
    file=Path(os.environ["NEXTPLAN_DIRECT_DB"]).expanduser().resolve()
    if not file.is_relative_to(root) or file==root:
        raise DirectError("unsafe_storage_path")
    if os.getenv("NEXTPLAN_DIRECT_TEST_MODE")!="1" and not os.path.ismount(root):
        raise DirectError("persistent_volume_required")
    if _store is None or _store.path!=file:
        _store=DirectStore(file)
    return _store

def options():
    repo=os.environ["NEXTPLAN_DIRECT_GITHUB_REPO"].split("/")
    if len(repo)!=2 or not all(repo):
        raise DirectError("invalid_repo_configuration")
    return {"repo_id":int(os.environ["NEXTPLAN_DIRECT_GITHUB_REPO_ID"]),
      "owner":repo[0],"name":repo[1],"author":os.environ["NEXTPLAN_DIRECT_GITHUB_AUTHOR"]}

async def reply(send,status,payload):
    await send({"type":"http.response.start","status":status,"headers":[
      (b"content-type",b"application/json"),(b"cache-control",b"no-store"),
      (b"x-content-type-options",b"nosniff")]})
    await send({"type":"http.response.body","body":json.dumps(payload,ensure_ascii=False).encode()})

async def read_body(receive):
    b=bytearray()
    while True:
        data=await receive()
        if data.get("type")=="http.disconnect":
            raise DirectError("disconnected")
        b+=data.get("body",b"")
        if len(b)>16384:
            raise DirectError("request_too_large")
        if not data.get("more_body"):
            return bytes(b)

def intake(st,event):
    parsed=parse_github_issue(event,**options())
    if not parsed:
        return {"status":"ignored"}
    cmd,op=parsed
    a=st.enqueue(cmd,"github_private_issue",op)
    return st.process(op) if a["status"]=="accepted" else a

async def handle(scope,receive,send):
    path=scope.get("path","")
    method=scope.get("method","GET")
    headers={k.decode("latin-1").lower():v.decode("latin-1") for k,v in scope.get("headers",[])}
    if path==PREFIX+"/status" and method=="GET":
        return await reply(send,200,{"status":"available" if configured() else "disabled",
          "canonical":"private_sqlite" if configured() else "legacy_untouched","reconciliation":health})
    if not configured():
        return await reply(send,503,{"error":"direct_v3_not_configured"})
    webhook=path==PREFIX+"/github/webhook" and method=="POST"
    if not webhook and not secrets.compare_digest(headers.get("authorization",""),
                                                   "Bearer "+os.environ["NEXTPLAN_DIRECT_TOKEN"]):
        return await reply(send,401,{"error":"unauthorized"})
    try:
        st=store()
        if webhook:
            raw=await read_body(receive)
            if not valid_signature(raw,headers.get("x-hub-signature-256",""),os.environ["NEXTPLAN_DIRECT_GITHUB_SECRET"]):
                return await reply(send,401,{"error":"invalid_signature"})
            data=json.loads(raw)
            result=intake(st,data) if headers.get("x-github-event")=="issues" else {"status":"ignored"}
        elif path==PREFIX+"/bootstrap" and method=="POST":
            body=json.loads(await read_body(receive))
            result=st.bootstrap(body.get("state"),body.get("confirmed"),body.get("sha256",""))
        elif path==PREFIX+"/state" and method=="GET":
            result=st.snapshot()
        elif path==PREFIX+"/command" and method=="POST":
            cmd=json.loads(await read_body(receive)).get("command")
            if not isinstance(cmd,dict):
                raise DirectError("command_missing")
            a=st.enqueue(cmd,"jarvis_direct","jarvis:"+str(cmd.get("operation_id","")))
            result=st.process(a["operation_id"]) if a["status"]=="accepted" else a
        elif path==PREFIX+"/confirm" and method=="POST":
            body=json.loads(await read_body(receive))
            if body.get("confirm") is not True:
                raise DirectError("confirmation_required")
            result=st.process(body.get("operation_id"),confirmed_delete=True)
        elif path==PREFIX+"/pending" and method=="POST":
            result={"results":st.process_pending()}
        elif path.startswith(PREFIX+"/receipt/") and method=="GET":
            result=st.receipt(path[len(PREFIX+"/receipt/"):])
        elif path==PREFIX+"/reconcile" and method=="POST":
            result=await asyncio.to_thread(reconcile,st)
        else:
            return await reply(send,404,{"error":"not_found"})
        return await reply(send,200,result)
    except DirectError as exc:
        return await reply(send,409 if exc.code in {"idempotency_conflict","already_initialized"} else 400,
                           {"error":exc.code})
    except (ValueError,TypeError,json.JSONDecodeError):
        return await reply(send,400,{"error":"invalid_request"})
    except (OSError,RuntimeError):
        return await reply(send,503,{"error":"storage_unavailable"})

def reconcile(st):
    """Periodic full scan; fail on overflow instead of silently losing commands."""
    from .direct_v3 import stamp
    token=os.getenv("NEXTPLAN_DIRECT_GITHUB_TOKEN","")
    repo=os.getenv("NEXTPLAN_DIRECT_GITHUB_REPO","")
    if len(token)<20 or "/" not in repo:
        raise DirectError("reconcile_token_required")
    count=0
    try:
        opts=options()
        for page in range(1,101):
            url=f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&page={page}&sort=created&direction=desc"
            req=Request(url,headers={"Authorization":"Bearer "+token,
                "Accept":"application/vnd.github+json","User-Agent":"NextPlan-Direct-v3"})
            with urlopen(req,timeout=15) as r:
                issues=json.load(r)
            if not isinstance(issues,list):
                raise DirectError("unexpected_github_reply")
            for issue in issues:
                if "pull_request" in issue:
                    continue
                event={"action":"opened","repository":{
                     "id":opts["repo_id"],"private":True,"owner":{"login":opts["owner"]},
                     "name":opts["name"]},"sender":{"login":(issue.get("user") or {}).get("login")},
                     "issue":issue}
                try:
                    intake(st,event)
                except DirectError as e:
                    if e.code not in {"actor_forbidden","invalid_issue_body","unsupported_action"}:
                        raise
                count+=1
            if len(issues)<100:
                health.update({"last_success":stamp(),"last_error":None})
                return {"status":"reconciled","scanned":count}
        raise DirectError("scan_limit_exceeded")
    except Exception as exc:
        health["last_error"]=type(exc).__name__
        raise

async def periodic_reconcile():
    while True:
        await asyncio.sleep(300)
        if configured():
            try:
                await asyncio.to_thread(reconcile,store())
            except Exception:
                pass
