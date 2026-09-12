from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .local_projector import apply_event, ensure_local_defaults, new_local_state


class CanonicalStore(ABC):
    @abstractmethod
    def get_state(self) -> dict[str, Any]: ...

    @abstractmethod
    def append_event(self, event: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def list_events(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def bootstrap_state(self, state: dict[str, Any], events: Iterable[dict[str, Any]] = ()) -> None: ...

    @abstractmethod
    def list_activity(self, limit: int = 100) -> list[dict[str, Any]]: ...


class SQLiteCanonicalStore(CanonicalStore):
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    project_id TEXT,
                    payload_json TEXT NOT NULL,
                    source_json TEXT,
                    applied INTEGER NOT NULL DEFAULT 1 CHECK (applied IN (0,1))
                );
                CREATE INDEX IF NOT EXISTS idx_events_at ON events(at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id, at DESC);

                CREATE TABLE IF NOT EXISTS snapshots (
                    name TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS activity (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    at TEXT NOT NULL,
                    project_id TEXT,
                    type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_json TEXT,
                    FOREIGN KEY(event_id) REFERENCES events(id)
                );
                CREATE INDEX IF NOT EXISTS idx_activity_at ON activity(at DESC, seq DESC);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (self.SCHEMA_VERSION,),
            )
            if conn.execute("SELECT 1 FROM snapshots WHERE name='canonical'").fetchone() is None:
                state = new_local_state()
                conn.execute(
                    "INSERT INTO snapshots(name, state_json, updated_at) VALUES ('canonical', ?, ?)",
                    (json.dumps(state, ensure_ascii=False), state["system"]["last_updated"]),
                )

    def get_state(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT state_json FROM snapshots WHERE name='canonical'").fetchone()
        if row is None:
            return new_local_state()
        return ensure_local_defaults(json.loads(row["state_json"]))

    def bootstrap_state(self, state: dict[str, Any], events: Iterable[dict[str, Any]] = ()) -> None:
        """Bootstrap from the existing canonical snapshot.

        Imported repository events are stored as already-applied audit records.
        They are not replayed over the snapshot because the repository predates
        the complete event layer and the snapshot is the migration authority.
        """
        canonical = ensure_local_defaults(deepcopy(state))
        imported = list(events)
        updated_at = str(canonical.get("system", {}).get("last_updated") or "1970-01-01T00:00:00Z")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM activity")
            conn.execute("DELETE FROM events")
            for event in imported:
                self._insert_event_row(conn, event, applied=1)
                self._insert_activity_row(conn, event)
            conn.execute(
                "INSERT INTO snapshots(name, state_json, updated_at) VALUES ('canonical', ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
                (json.dumps(canonical, ensure_ascii=False), updated_at),
            )
            conn.execute(
                "INSERT INTO metadata(key, value) VALUES ('bootstrap_source', 'lifeos-state-json') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            conn.execute(
                "INSERT INTO metadata(key, value) VALUES ('bootstrap_event_count', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(len(imported)),),
            )
            conn.commit()

    def _insert_event_row(self, conn: sqlite3.Connection, event: dict[str, Any], *, applied: int = 1) -> None:
        eid = str(event.get("id") or "").strip()
        at = str(event.get("at") or "").strip()
        et = str(event.get("type") or "").strip()
        if not eid or not at or not et:
            raise ValueError("event requires id, at and type")
        source = event.get("source")
        conn.execute(
            "INSERT OR IGNORE INTO events(id, at, type, project_id, payload_json, source_json, applied) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eid,
                at,
                et,
                str(event.get("project_id") or "") or None,
                json.dumps(event, ensure_ascii=False),
                json.dumps(source, ensure_ascii=False) if source is not None else None,
                applied,
            ),
        )

    def _insert_activity_row(self, conn: sqlite3.Connection, event: dict[str, Any]) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO activity(event_id, at, project_id, type, summary, source_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(event.get("id")),
                str(event.get("at")),
                str(event.get("project_id") or "") or None,
                str(event.get("type")),
                str(event.get("summary") or event.get("title") or event.get("type")),
                json.dumps(event.get("source"), ensure_ascii=False) if event.get("source") is not None else None,
            ),
        )

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        eid = str(event.get("id") or "").strip()
        if not eid:
            raise ValueError("event requires id")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT payload_json FROM events WHERE id=?", (eid,)).fetchone()
            if existing is not None:
                conn.rollback()
                return {"status": "no_change", "event_id": eid, "state": self.get_state()}

            row = conn.execute("SELECT state_json FROM snapshots WHERE name='canonical'").fetchone()
            current = new_local_state() if row is None else json.loads(row["state_json"])
            projected = apply_event(current, event)
            self._insert_event_row(conn, event, applied=1)
            self._insert_activity_row(conn, event)
            updated_at = str(projected.get("system", {}).get("last_updated") or event.get("at"))
            conn.execute(
                "INSERT INTO snapshots(name, state_json, updated_at) VALUES ('canonical', ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
                (json.dumps(projected, ensure_ascii=False), updated_at),
            )
            conn.commit()
        return {"status": "applied", "event_id": eid, "state": projected}

    def list_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT payload_json FROM events ORDER BY at DESC, rowid DESC"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (max(0, int(limit)),)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def list_activity(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, event_id, at, project_id, type, summary, source_json FROM activity ORDER BY at DESC, seq DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["source"] = json.loads(item.pop("source_json")) if item.get("source_json") else None
            result.append(item)
        return result

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
