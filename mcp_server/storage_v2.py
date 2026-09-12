from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_v1 import SQLiteCanonicalStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class SQLiteCanonicalStoreV2(SQLiteCanonicalStore):
    """Stage V Local store extension.

    Canonical truth remains append-only events + snapshot. Pending confirmations are
    deliberately kept outside canonical truth because a proposal is not yet a fact.
    """

    SCHEMA_VERSION = 2

    def __init__(self, path: str | Path):
        super().__init__(path)
        self._init_stage_v_schema()

    def _init_stage_v_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_candidates (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    source_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','applied','ignored','expired','failed')),
                    resolved_at TEXT,
                    resolution_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pending_status_created
                    ON pending_candidates(status, created_at DESC);
                """
            )
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)")
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")

    def queue_candidate(self, candidate: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
        cid = str(candidate.get("id") or "").strip()
        if not cid:
            raise ValueError("candidate requires id")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pending_candidates(id,created_at,candidate_json,source_json,status) VALUES (?,?,?,?, 'pending') "
                "ON CONFLICT(id) DO UPDATE SET candidate_json=excluded.candidate_json, source_json=excluded.source_json "
                "WHERE pending_candidates.status='pending'",
                (
                    cid,
                    _now_iso(),
                    json.dumps(candidate, ensure_ascii=False),
                    json.dumps(source, ensure_ascii=False) if source is not None else None,
                ),
            )
        return {"status": "queued", "id": cid}

    def get_pending_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT candidate_json, source_json FROM pending_candidates WHERE id=? AND status='pending'",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row["candidate_json"])
        value["source"] = json.loads(row["source_json"]) if row["source_json"] else None
        return value

    def list_pending_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT candidate_json, source_json, created_at FROM pending_candidates "
                "WHERE status='pending' ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = json.loads(row["candidate_json"])
            item["source"] = json.loads(row["source_json"]) if row["source_json"] else None
            item["queued_at"] = row["created_at"]
            result.append(item)
        return result

    def resolve_candidate(self, candidate_id: str, status: str, resolution: dict[str, Any] | None = None) -> dict[str, Any]:
        if status not in {"applied", "ignored", "expired", "failed"}:
            raise ValueError("invalid pending candidate resolution")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE pending_candidates SET status=?, resolved_at=?, resolution_json=? "
                "WHERE id=? AND status='pending'",
                (
                    status,
                    _now_iso(),
                    json.dumps(resolution, ensure_ascii=False) if resolution is not None else None,
                    candidate_id,
                ),
            )
        return {"status": status if cur.rowcount else "already_resolved", "id": candidate_id}
