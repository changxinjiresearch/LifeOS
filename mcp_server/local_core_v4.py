from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import local_core_v3 as local_core_v3_module
from .local_actions_v4 import execute_action as execute_action_v4
from .local_core_v3 import LocalCoreAppV3, _origin, _read_json, _send_json
from .local_execution_v1 import LocalExecutionGateway
from .local_pairing_v1 import LocalPairingManager
from .storage_v3 import SQLiteCanonicalStoreV3

# LocalCoreAppV3 resolves execute_action from its defining module at request time.
# Patch that single action seam so the hardened v4 runtime exposes the complete
# local action surface while preserving the stable v3 HTTP routing contract.
local_core_v3_module.execute_action = execute_action_v4


class LocalCoreAppV4(LocalCoreAppV3):
    """Stage 9/10 hardened local runtime.

    The v4 runtime keeps the v3 API stable while adding integrity reporting,
    sanitized backup/restore, recovery visibility, and extension-origin binding.
    """

    def __init__(self, db_path: str | Path, bootstrap_token: str | None = None, *, execution_dry_run: bool = False):
        self.store = SQLiteCanonicalStoreV3(db_path)
        self.db_path = str(Path(db_path).expanduser().resolve())
        self.bootstrap_token = bootstrap_token
        self.pairing = LocalPairingManager()
        self.execution = LocalExecutionGateway(self.store, dry_run=execution_dry_run)

    def _authorized(self, scope) -> bool:
        if not super()._authorized(scope):
            return False
        origin = _origin(scope)
        if origin.startswith("chrome-extension://"):
            paired_id = self.store.get_metadata("paired_extension_id") or ""
            if paired_id and origin != f"chrome-extension://{paired_id}":
                return False
        return True

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await _send_json(send, 404, {"error": "not_found"})
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        origin = _origin(scope)

        if path == "/healthz" and method == "GET":
            integrity = self.store.integrity_status()
            state = self.store.get_state() if integrity.get("ok") else {"projects": []}
            return await _send_json(send, 200 if integrity.get("ok") else 503, {
                "status": "ok" if integrity.get("ok") else "unhealthy",
                "runtime": "nextplan-local-core-v4",
                "canonical_store": "sqlite-local",
                "schema_version": self.store.SCHEMA_VERSION,
                "project_count": len(state.get("projects", [])),
                "paired": bool(self._paired_token()),
                "integrity": integrity,
            }, origin)

        if path in {"/maintenance/status", "/backup/export", "/backup/restore", "/pairing/reset"}:
            if not self._authorized(scope):
                return await _send_json(send, 401, {"error": "unauthorized"}, origin)
            try:
                if path == "/maintenance/status" and method == "GET":
                    backups = sorted((Path(self.db_path).parent / "backups").glob("nextplan-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
                    recovery = sorted((Path(self.db_path).parent / "recovery").glob("recovery-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
                    return await _send_json(send, 200, {
                        "status": "ok",
                        "integrity": self.store.integrity_status(),
                        "latest_backup": str(backups[0]) if backups else None,
                        "recovery_checkpoints": len(recovery),
                        "data_dir": str(Path(self.db_path).parent),
                    }, origin)
                if path == "/backup/export" and method == "POST":
                    payload = await _read_json(receive)
                    destination = str(payload.get("path") or "").strip() or None
                    return await _send_json(send, 200, self.store.export_backup(destination), origin)
                if path == "/backup/restore" and method == "POST":
                    payload = await _read_json(receive)
                    source = str(payload.get("path") or "").strip()
                    if not source:
                        raise ValueError("backup path is required")
                    return await _send_json(send, 200, self.store.restore_backup(source), origin)
                if path == "/pairing/reset" and method == "POST":
                    with self.store._connect() as conn:
                        conn.execute("DELETE FROM metadata WHERE key IN ('paired_extension_token','paired_extension_id')")
                    return await _send_json(send, 200, {"status": "ok", "paired": False}, origin)
            except (ValueError, FileNotFoundError) as exc:
                return await _send_json(send, 400, {"error": "invalid_request", "detail": str(exc)}, origin)
            except Exception as exc:
                return await _send_json(send, 500, {"error": "maintenance_failed", "detail": type(exc).__name__}, origin)

        return await super().__call__(scope, receive, send)


def create_local_app(db_path: str | Path, bootstrap_token: str | None = None, *, execution_dry_run: bool = False) -> LocalCoreAppV4:
    return LocalCoreAppV4(db_path, bootstrap_token=bootstrap_token, execution_dry_run=execution_dry_run)


_DEFAULT_DB = Path(os.getenv("NEXTPLAN_LOCAL_DB", str(Path.home() / ".nextplan" / "nextplan.db")))
app = create_local_app(_DEFAULT_DB, bootstrap_token=os.getenv("NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN") or None)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("NEXTPLAN_LOCAL_PORT", "47123"))
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False, access_log=False)
