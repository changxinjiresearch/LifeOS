"""Web-first Jarvis P1-P4 private workspace.

Opt-in server-side SQLite. Never writes to LifeOS/state.json or a public repository.
This is a separate draft/sync lane until a canonical production migration is approved.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jarvis_p0_contracts import JarvisContractError, build_context_candidate, check_storage_policy, check_sync_intent

STATUSES = {"planned", "active", "waiting", "blocked", "completed"}
ALLOWED_PROJECT_FIELDS = {"status", "next_action", "priority", "name"}
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,127}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _required_str(value: Any, field: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise JarvisContractError(f"invalid {field}")
    return value.strip()


class JarvisWorkspace:
    """Transactional per-user *private* workspace; caller must authenticate first."""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists() and self.path.is_symlink():
            raise JarvisContractError("database symlink denied")
        if not self.path.exists():
            self.path.touch(mode=0o600)
        if os.name != "nt":
            os.chmod(self.path, 0o600)
        with self._connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, record_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                  id TEXT PRIMARY KEY, receipt_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS knowledge (
                  id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                  project_id TEXT NOT NULL, context_type TEXT NOT NULL, summary TEXT NOT NULL,
                  source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
                  epistemic_status TEXT NOT NULL, created_at TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata(name,value) VALUES ('revision','0');
            """)

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("PRAGMA journal_mode=WAL")
        return c

    @staticmethod
    def _rev(c: sqlite3.Connection) -> int:
        return int(c.execute("SELECT value FROM metadata WHERE name='revision'").fetchone()["value"])

    @staticmethod
    def _projects(c: sqlite3.Connection) -> list[dict[str, Any]]:
        return [json.loads(row["record_json"]) for row in c.execute("SELECT record_json FROM projects ORDER BY id")]

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as c:
            return {"revision": self._rev(c), "projects": self._projects(c), "scope": "private_jarvis_workspace",
                    "authority": "shadow_until_migrated", "source": "sqlite_private"}

    def bootstrap(self, items: list[dict[str, Any]], *, explicitly_confirmed: bool = False) -> dict[str, Any]:
        if not explicitly_confirmed:
            raise JarvisContractError("bootstrap requires explicit user confirmation")
        if not isinstance(items, list) or not 0 < len(items) <= 1000:
            raise JarvisContractError("invalid bootstrap project count")
        cleaned: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise JarvisContractError("invalid project record")
            project_id = _required_str(item.get("id"), "project_id", 128)
            if not NAME_RE.fullmatch(project_id):
                raise JarvisContractError("project id contains unsupported characters")
            name = _required_str(item.get("name"), "project name", 256)
            status = str(item.get("status") or "planned")
            if status not in STATUSES or project_id in seen:
                raise JarvisContractError("duplicate project or invalid status")
            seen.add(project_id)
            cleaned.append({"id": project_id, "name": name, "status": status,
                            "next_action": str(item.get("next_action") or "")[:1000],
                            "priority": max(1, min(5, int(item.get("priority") or 3)))})
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if self._rev(c) != 0 or c.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
                raise JarvisContractError("bootstrap is allowed once on an empty workspace")
            for item in cleaned:
                c.execute("INSERT INTO projects(id,record_json) VALUES (?,?)",
                          (item["id"], json.dumps(item, ensure_ascii=False)))
            c.execute("UPDATE metadata SET value='1' WHERE name='revision'")
            c.commit()
        return {"status": "bootstrapped", "revision": 1, "project_count": len(cleaned),
                "authority": "shadow_until_migrated"}

    def mutate(self, intent: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        """Atomic idempotency/revision check + allowlisted write. No destructive ops."""
        if not isinstance(intent, dict) or not isinstance(values, dict):
            raise JarvisContractError("invalid mutation payload")
        if intent.get("action") != "update_project" or intent.get("target", {}).get("entity_type") != "project":
            raise JarvisContractError("only safe project updates are supported")
        if not values or set(values) - ALLOWED_PROJECT_FIELDS:
            raise JarvisContractError("unsupported project update")
        payload = dict(values)
        if "status" in payload and payload["status"] not in STATUSES:
            raise JarvisContractError("invalid project status")
        if "name" in payload:
            payload["name"] = _required_str(payload["name"], "name", 256)
        if "priority" in payload:
            if type(payload["priority"]) is not int or payload["priority"] not in range(1, 6):
                raise JarvisContractError("invalid priority")
        if "next_action" in payload:
            if not isinstance(payload["next_action"], str) or len(payload["next_action"]) > 1000:
                raise JarvisContractError("invalid next action")
        op_id = _required_str(intent.get("operation_id"), "operation_id", 128)
        project_id = _required_str(intent.get("target", {}).get("entity_id"), "entity_id", 128)
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT receipt_json FROM operations WHERE id=?", (op_id,)).fetchone()
            if old:
                receipt = json.loads(old["receipt_json"])
                return {**receipt, "status": "already_applied", "original_status": receipt["status"]}
            revision = self._rev(c)
            check = check_sync_intent(intent, canonical_revision=revision, applied_operation_ids=[])
            if check["status"] == "conflict":
                return {"status": "conflict", "operation_id": op_id, "revision": revision}
            row = c.execute("SELECT record_json FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise JarvisContractError("unknown project id")
            record = json.loads(row["record_json"])
            changed = any(record.get(k) != v for k, v in payload.items())
            if changed:
                record.update(payload)
                c.execute("UPDATE projects SET record_json=? WHERE id=?",
                          (json.dumps(record, ensure_ascii=False), project_id))
                revision += 1
                c.execute("UPDATE metadata SET value=? WHERE name='revision'", (str(revision),))
            receipt = {"status": "applied" if changed else "no_change", "operation_id": op_id,
                       "revision": revision, "project_id": project_id, "verified": True,
                       "scope": "private_jarvis_workspace", "authority": "shadow_until_migrated"}
            c.execute("INSERT INTO operations(id,receipt_json,created_at) VALUES (?,?,?)",
                      (op_id, json.dumps(receipt), _now()))
            c.commit()
            return receipt

    def record_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Manual, explicitly confirmed text extraction, not automatic chat scraping."""
        if not isinstance(payload, dict):
            raise JarvisContractError("invalid context payload")
        if payload.get("source_kind") not in {"chatgpt_user_turn", "manual_import"}:
            raise JarvisContractError("tool receipts require server-side verification (not available here)")
        candidate = build_context_candidate(
            context_type=payload.get("context_type"), project_id=payload.get("project_id"),
            summary=payload.get("summary"), source_kind=payload.get("source_kind"),
            source_ref=payload.get("source_ref"), user_authorized=payload.get("user_authorized") is True,
            confirmed_by_user=payload.get("confirmed_by_user") is True)
        check_storage_policy(candidate, destination="private_authenticated_service")
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            existing = c.execute("SELECT id FROM knowledge WHERE fingerprint=?",
                                 (candidate["fingerprint"],)).fetchone()
            if existing:
                return {"status": "already_exists", "id": existing["id"],
                        "fingerprint": candidate["fingerprint"]}
            kid = "knowledge-" + uuid.uuid4().hex
            c.execute("""INSERT INTO knowledge
                      (id, fingerprint, project_id, context_type, summary, source_kind,
                       source_ref, epistemic_status, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                      (kid, candidate["fingerprint"], candidate["project_id"], candidate["context_type"],
                       candidate["summary"], candidate["source"]["kind"], candidate["source"]["ref"],
                       candidate["epistemic_status"], _now()))
            c.commit()
        return {"status": "recorded", "id": kid, "fingerprint": candidate["fingerprint"],
                "source": candidate["source"], "context_type": candidate["context_type"]}

    def search(self, query: str = "", project_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if not isinstance(query, str) or len(query) > 200 or not isinstance(project_id, str) or len(project_id) > 128:
            raise JarvisContractError("invalid search query")
        lim = max(1, min(50, int(limit)))
        sql = "SELECT * FROM knowledge WHERE 1=1"
        args: list[Any] = []
        if project_id:
            sql += " AND project_id=?"
            args.append(project_id)
        if query.strip():
            # Escape SQLite LIKE wildcards, preventing pattern abuse.
            clean = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND (summary LIKE ? ESCAPE '\\' OR context_type LIKE ? ESCAPE '\\')"
            args.extend(["%" + clean + "%"] * 2)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        args.append(lim)
        with self._connect() as c:
            return [dict(row) for row in c.execute(sql, args)]

    def delete_context(self, knowledge_id: str, *, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise JarvisContractError("delete requires explicit confirmation")
        kid = _required_str(knowledge_id, "knowledge_id", 128)
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute("DELETE FROM knowledge WHERE id=?", (kid,))
            c.commit()
            return {"status": "deleted" if cur.rowcount else "already_absent", "id": kid}

    def context_bundle(self, project_id: str = "") -> dict[str, Any]:
        """User-authorized export; no hidden model context and no raw chat history."""
        state = self.snapshot()
        if project_id:
            state["projects"] = [x for x in state["projects"] if x["id"] == project_id]
        items = self.search(project_id=project_id, limit=40)
        return {"format": "nextplan-jarvis-context-v1",
                "authority": "shadow_until_migrated",
                "projects": state["projects"],
                "knowledge": [{k: v for k, v in row.items() if k in {
                    "id", "project_id", "context_type", "summary", "source_kind", "source_ref",
                    "epistemic_status", "created_at"
                }} for row in items]}
