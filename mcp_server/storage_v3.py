from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_v2 import SQLiteCanonicalStoreV2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class SQLiteCanonicalStoreV3(SQLiteCanonicalStoreV2):
    """Release-hardened local canonical store.

    Adds integrity checks, rotating recovery checkpoints, and sanitized ZIP
    backup/restore. Pairing credentials are intentionally excluded from user
    backups so restoring a backup always requires a fresh local pairing.
    """

    SCHEMA_VERSION = 3
    BACKUP_FORMAT = 1
    RECOVERY_KEEP = 3

    def __init__(self, path: str | Path):
        self.recovered_on_startup = False
        self.recovery_detail = ""
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if resolved.exists() and not self._database_ok(resolved):
            recovered = self._restore_latest_recovery_file(resolved)
            if not recovered:
                corrupt = resolved.with_name(f"{resolved.name}.corrupt-{_stamp()}")
                os.replace(resolved, corrupt)
                for suffix in ("-wal", "-shm"):
                    side = Path(str(resolved) + suffix)
                    if side.exists():
                        side.unlink(missing_ok=True)
                self.recovery_detail = f"Corrupt database quarantined as {corrupt.name}; started a new local database."
            else:
                self.recovered_on_startup = True
                self.recovery_detail = "Recovered canonical database from the latest verified recovery checkpoint."
        super().__init__(resolved)
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)")
        if not self.integrity_status()["ok"]:
            raise RuntimeError("NextPlan local database failed integrity check after initialization")

    @staticmethod
    def _database_ok(path: Path) -> bool:
        try:
            conn = sqlite3.connect(path, timeout=5.0)
            try:
                row = conn.execute("PRAGMA quick_check").fetchone()
                return bool(row and str(row[0]).lower() == "ok")
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return False

    @classmethod
    def _recovery_dir_for(cls, db_path: Path) -> Path:
        return db_path.parent / "recovery"

    @classmethod
    def _restore_latest_recovery_file(cls, db_path: Path) -> bool:
        recovery_dir = cls._recovery_dir_for(db_path)
        if not recovery_dir.exists():
            return False
        candidates = sorted(recovery_dir.glob("recovery-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in candidates:
            if not cls._database_ok(candidate):
                continue
            tmp = db_path.with_name(f".{db_path.name}.recovering")
            shutil.copy2(candidate, tmp)
            os.replace(tmp, db_path)
            for suffix in ("-wal", "-shm"):
                Path(str(db_path) + suffix).unlink(missing_ok=True)
            return True
        return False

    def integrity_status(self) -> dict[str, Any]:
        try:
            with self._connect() as conn:
                quick = conn.execute("PRAGMA quick_check").fetchone()
                migrations = [int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
                event_count = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
                snapshot_count = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
            ok = bool(quick and str(quick[0]).lower() == "ok" and snapshot_count >= 1)
            return {
                "ok": ok,
                "quick_check": str(quick[0]) if quick else "missing",
                "schema_version": max(migrations) if migrations else 0,
                "supported_schema_version": self.SCHEMA_VERSION,
                "event_count": event_count,
                "snapshot_count": snapshot_count,
                "recovered_on_startup": self.recovered_on_startup,
                "recovery_detail": self.recovery_detail,
            }
        except sqlite3.DatabaseError as exc:
            return {"ok": False, "quick_check": type(exc).__name__, "schema_version": 0, "supported_schema_version": self.SCHEMA_VERSION}

    def _sqlite_backup(self, destination: Path, *, sanitize_credentials: bool) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        src = sqlite3.connect(self.path, timeout=10.0)
        dst = sqlite3.connect(destination, timeout=10.0)
        try:
            src.backup(dst)
            if sanitize_credentials:
                dst.execute("DELETE FROM metadata WHERE key IN ('paired_extension_token','paired_extension_id')")
                dst.commit()
            row = dst.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise RuntimeError("backup database failed quick_check")
        finally:
            dst.close()
            src.close()

    def create_recovery_checkpoint(self) -> dict[str, Any]:
        recovery_dir = self._recovery_dir_for(self.path)
        recovery_dir.mkdir(parents=True, exist_ok=True)
        target = recovery_dir / f"recovery-{_stamp()}.db"
        self._sqlite_backup(target, sanitize_credentials=False)
        checkpoints = sorted(recovery_dir.glob("recovery-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in checkpoints[self.RECOVERY_KEEP:]:
            old.unlink(missing_ok=True)
        return {"status": "ok", "path": str(target), "sha256": _sha256(target)}

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        result = super().append_event(event)
        if result.get("status") == "applied":
            self.create_recovery_checkpoint()
        return result

    def export_backup(self, destination: str | Path | None = None) -> dict[str, Any]:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = Path(destination).expanduser().resolve() if destination else backup_dir / f"nextplan-backup-{_stamp()}.zip"
        if target.suffix.lower() != ".zip":
            raise ValueError("backup destination must end in .zip")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="nextplan-backup-") as td:
            td_path = Path(td)
            db_copy = td_path / "nextplan.db"
            self._sqlite_backup(db_copy, sanitize_credentials=True)
            manifest = {
                "format": "nextplan-local-backup",
                "format_version": self.BACKUP_FORMAT,
                "created_at": _now_iso(),
                "schema_version": self.SCHEMA_VERSION,
                "database_sha256": _sha256(db_copy),
                "credentials_included": False,
            }
            manifest_path = td_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_zip = target.with_name(f".{target.name}.tmp")
            with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(db_copy, "nextplan.db")
                zf.write(manifest_path, "manifest.json")
            os.replace(tmp_zip, target)
        return {"status": "ok", "path": str(target), "sha256": _sha256(target), "manifest": manifest}

    def restore_backup(self, source: str | Path) -> dict[str, Any]:
        archive = Path(source).expanduser().resolve()
        if not archive.is_file():
            raise ValueError("backup archive not found")
        with tempfile.TemporaryDirectory(prefix="nextplan-restore-") as td:
            td_path = Path(td)
            with zipfile.ZipFile(archive, "r") as zf:
                names = set(zf.namelist())
                if names != {"nextplan.db", "manifest.json"}:
                    raise ValueError("backup archive has unexpected contents")
                for info in zf.infolist():
                    if info.is_dir() or Path(info.filename).name != info.filename:
                        raise ValueError("unsafe backup archive")
                zf.extractall(td_path)
            manifest = json.loads((td_path / "manifest.json").read_text(encoding="utf-8"))
            incoming = td_path / "nextplan.db"
            if manifest.get("format") != "nextplan-local-backup" or int(manifest.get("format_version") or 0) != self.BACKUP_FORMAT:
                raise ValueError("unsupported NextPlan backup format")
            if int(manifest.get("schema_version") or 0) > self.SCHEMA_VERSION:
                raise ValueError("backup was created by a newer NextPlan schema")
            if manifest.get("database_sha256") != _sha256(incoming):
                raise ValueError("backup database hash mismatch")
            if not self._database_ok(incoming):
                raise ValueError("backup database failed integrity check")

            pre_dir = self.path.parent / "pre_restore"
            pre_dir.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                pre = pre_dir / f"pre-restore-{_stamp()}.db"
                self._sqlite_backup(pre, sanitize_credentials=False)
            replacement = self.path.with_name(f".{self.path.name}.restoring")
            shutil.copy2(incoming, replacement)
            os.replace(replacement, self.path)
            for suffix in ("-wal", "-shm"):
                Path(str(self.path) + suffix).unlink(missing_ok=True)

        # Bring older valid backups forward to the current schema and explicitly
        # require a fresh browser pairing after restore.
        self._init_schema()
        self._init_stage_v_schema()
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)")
            conn.execute("DELETE FROM metadata WHERE key IN ('paired_extension_token','paired_extension_id')")
        status = self.integrity_status()
        if not status.get("ok"):
            raise RuntimeError("restored database failed post-restore integrity check")
        self.create_recovery_checkpoint()
        return {"status": "restored", "path": str(archive), "integrity": status, "pairing_reset": True}
