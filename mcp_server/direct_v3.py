"""NextPlan Direct v3: browser-independent durable project operations.
Opt-in and private-storage-only. Legacy NextPlan is unaffected until cutover.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

STATUSES={"planned","active","waiting","blocked","completed"}
FIELDS={"status","priority","next_action","progress"}
PID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
OID=re.compile(r"^[A-Za-z0-9:_-]{5,160}$")

class DirectError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def encoded(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def digest(x):
    return hashlib.sha256(encoded(x).encode()).hexdigest()

def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def validated(x):
    if not isinstance(x,dict) or x.get("version")!=3:
        raise DirectError("invalid_protocol")
    if set(x)-{"version","operation_id","action","project_id","changes","expected_revision"}:
        raise DirectError("unsupported_parameter")
    op=x.get("operation_id")
    pid=x.get("project_id")
    if not isinstance(op,str) or not OID.fullmatch(op):
        raise DirectError("invalid_operation_id")
    if not isinstance(pid,str) or not PID.fullmatch(pid):
        raise DirectError("invalid_project_id")
    action=x.get("action")
    if action not in ("update_project","delete_project"):
        raise DirectError("unsupported_action")
    ch=x.get("changes",{})
    if not isinstance(ch,dict):
        raise DirectError("invalid_changes")
    if action=="delete_project":
        if ch:
            raise DirectError("invalid_delete_changes")
    else:
        if not ch or set(ch)-FIELDS:
            raise DirectError("invalid_changes")
        if "status" in ch and ch["status"] not in STATUSES:
            raise DirectError("invalid_status")
        if "priority" in ch and (type(ch["priority"]) is not int or not 1<=ch["priority"]<=5):
            raise DirectError("invalid_priority")
        if "progress" in ch and (type(ch["progress"]) not in (int,float) or not 0<=ch["progress"]<=100):
            raise DirectError("invalid_progress")
        if "next_action" in ch and (not isinstance(ch["next_action"],str) or len(ch["next_action"])>1000):
            raise DirectError("invalid_next_action")
    rev=x.get("expected_revision")
    if rev is not None and (type(rev) is not int or rev<0):
        raise DirectError("invalid_revision")
    return {"version":3,"operation_id":op,"action":action,"project_id":pid,
            "changes":ch,"expected_revision":rev}

class DirectStore:
    """One transactional source of truth: full legacy document + operation receipts."""
    def __init__(self,path):
        p=Path(path).expanduser()
        if p.is_symlink():
            raise DirectError("database_symlink_forbidden")
        self.path=p.resolve()
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS canonical(
              id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(
              id TEXT PRIMARY KEY,source TEXT NOT NULL,source_ref TEXT NOT NULL UNIQUE,
              payload_hash TEXT NOT NULL,command TEXT NOT NULL,revision_at_intake INTEGER NOT NULL,
              status TEXT NOT NULL,receipt TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT,op TEXT NOT NULL,event TEXT NOT NULL,at TEXT NOT NULL);
            """)
        if os.name!="nt":
            os.chmod(self.path,0o600)

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=15,isolation_level=None)
        try:
            c.row_factory=sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=15000")
            yield c
        finally:
            c.close()

    def bootstrap(self,state,confirmed=False,expected_hash=""):
        if confirmed is not True or not isinstance(state,dict) or digest(state)!=expected_hash:
            raise DirectError("bootstrap_not_confirmed_or_hash_mismatch")
        if not isinstance(state.get("projects"),list) or not isinstance(state.get("events"),list):
            raise DirectError("incomplete_legacy_document")
        ids=[p.get("id") for p in state["projects"] if isinstance(p,dict)]
        if len(ids)!=len(state["projects"]) or len(ids)!=len(set(ids)) or any(
          not isinstance(i,str) or not PID.fullmatch(i) for i in ids):
            raise DirectError("invalid_project_set")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM canonical").fetchone():
                raise DirectError("already_initialized")
            c.execute("INSERT INTO canonical(id,revision,document) VALUES(1,0,?)",(encoded(state),))
            c.commit()
        return {"status":"bootstrapped","project_count":len(ids),"revision":0,"sha256":expected_hash}

    def snapshot(self):
        with self.db() as c:
            row=c.execute("SELECT revision,document FROM canonical WHERE id=1").fetchone()
            if not row:
                raise DirectError("not_bootstrapped")
            return {"revision":row["revision"],"state":json.loads(row["document"]),
                    "authority":"private_sqlite"}

    def enqueue(self,raw,source,source_ref):
        cmd=validated(raw)
        if source not in ("github_private_issue","jarvis_direct"):
            raise DirectError("untrusted_source")
        if not isinstance(source_ref,str) or not 1<=len(source_ref)<=256:
            raise DirectError("invalid_source_ref")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            existing=c.execute("SELECT * FROM operations WHERE id=? OR source_ref=?",
                               (cmd["operation_id"],source_ref)).fetchone()
            if existing:
                if existing["source_ref"]!=source_ref or existing["payload_hash"]!=digest(cmd):
                    raise DirectError("idempotency_conflict")
                return {"status":existing["status"],"operation_id":existing["id"],"duplicate":True}
            row=c.execute("SELECT revision FROM canonical WHERE id=1").fetchone()
            if not row:
                raise DirectError("not_bootstrapped")
            status="needs_confirmation" if cmd["action"]=="delete_project" else "accepted"
            t=stamp()
            c.execute("""INSERT INTO operations(id,source,source_ref,payload_hash,command,
                         revision_at_intake,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?)""",
                      (cmd["operation_id"],source,source_ref,digest(cmd),encoded(cmd),
                       row["revision"],status,t,t))
            c.execute("INSERT INTO audit(op,event,at) VALUES(?,?,?)",(cmd["operation_id"],status,t))
            c.commit()
        return {"status":status,"operation_id":cmd["operation_id"],"duplicate":False}

    def receipt(self,op):
        with self.db() as c:
            row=c.execute("SELECT status,receipt,source_ref FROM operations WHERE id=?",(op,)).fetchone()
            return ({"status":row["status"],"operation_id":op,"source_ref":row["source_ref"],
                     "receipt":json.loads(row["receipt"]) if row["receipt"] else None}
                    if row else {"status":"not_found","operation_id":op})

    @staticmethod
    def _finish(c,op,status,meta):
        receipt={"operation_id":op,"status":status,**meta}
        t=stamp()
        c.execute("UPDATE operations SET status=?,receipt=?,updated=? WHERE id=?",
                  (status,encoded(receipt),t,op))
        c.execute("INSERT INTO audit(op,event,at) VALUES(?,?,?)",(op,status,t))
        c.commit()
        return receipt

    def process(self,op,confirmed_delete=False):
        if not isinstance(op,str) or not OID.fullmatch(op):
            raise DirectError("invalid_operation_id")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM operations WHERE id=?",(op,)).fetchone()
            if not row:
                raise DirectError("unknown_operation")
            if row["status"] in ("applied","no_change","conflict","rejected"):
                return {"status":row["status"],"operation_id":op,"duplicate":True}
            cmd=json.loads(row["command"])
            if cmd["action"]=="delete_project" and confirmed_delete is not True:
                return {"status":"needs_confirmation","operation_id":op}
            state_row=c.execute("SELECT revision,document FROM canonical WHERE id=1").fetchone()
            revision=state_row["revision"]
            expected=cmd["expected_revision"] if cmd["expected_revision"] is not None else row["revision_at_intake"]
            if expected!=revision:
                return self._finish(c,op,"conflict",{"revision":revision,"reason":"stale_revision"})
            state=json.loads(state_row["document"])
            matches=[p for p in state["projects"] if p.get("id")==cmd["project_id"]]
            if len(matches)!=1:
                return self._finish(c,op,"rejected",{"reason":"unknown_or_ambiguous_project"})
            before=json.loads(encoded(matches[0]))
            if cmd["action"]=="delete_project":
                state["projects"]=[p for p in state["projects"] if p.get("id")!=cmd["project_id"]]
                after=None
                changed=True
            else:
                changed=any(matches[0].get(k)!=v for k,v in cmd["changes"].items())
                if changed:
                    matches[0].update(cmd["changes"])
                after=matches[0]
            if changed:
                revision+=1
                state["events"].append({"id":"direct-"+op,"at":stamp(),"project_id":cmd["project_id"],
                   "type":"project_deleted" if cmd["action"]=="delete_project" else "project_updated",
                   "summary":"NextPlan Direct verified change","source":"nextplan-direct-v3",
                   "changes":cmd["changes"] if after is not None else {}})
                c.execute("UPDATE canonical SET revision=?,document=? WHERE id=1",(revision,encoded(state)))
            return self._finish(c,op,"applied" if changed else "no_change",{
                 "revision":revision,"project_id":cmd["project_id"],"before":before,
                 "after":after,"verified":True})

    def process_pending(self,limit=50):
        with self.db() as c:
            ops=[r[0] for r in c.execute("SELECT id FROM operations WHERE status='accepted' ORDER BY created,id LIMIT ?",
                                         (max(1,min(limit,100)),))]
        return [self.process(op) for op in ops]

def valid_signature(raw,signature,secret):
    if not isinstance(secret,str) or len(secret)<32 or not isinstance(signature,str) or not re.fullmatch(r"sha256=[0-9a-f]{64}",signature):
        return False
    expected="sha256="+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)

def parse_github_issue(event,repo_id,owner,name,author):
    if not isinstance(event,dict) or event.get("action")!="opened":
        return None
    repo=event.get("repository") or {}
    issue=event.get("issue") or {}
    if repo.get("private") is not True or repo.get("id")!=repo_id or repo.get("name")!=name or (repo.get("owner") or {}).get("login")!=owner:
        raise DirectError("private_repository_required")
    if (event.get("sender") or {}).get("login")!=author or (issue.get("user") or {}).get("login")!=author:
        raise DirectError("actor_forbidden")
    number=issue.get("number")
    if type(number) is not int or number<1 or "pull_request" in issue:
        raise DirectError("invalid_issue")
    body=issue.get("body")
    if not isinstance(body,str) or len(body)>16384:
        raise DirectError("invalid_issue_body")
    try:
        cmd=validated(json.loads(body))
    except (ValueError,TypeError):
        raise DirectError("invalid_issue_body")
    op=f"github:{repo_id}:{number}"
    cmd["operation_id"]=op
    return cmd,op
