from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mcp_server.local_core_v4 import create_local_app
from mcp_server.storage_v3 import SQLiteCanonicalStoreV3


def test_sanitized_backup_restore_and_pairing_reset(tmp_path):
    db = tmp_path / "nextplan.db"
    store = SQLiteCanonicalStoreV3(db)
    store.set_metadata("test_marker", "before")
    store.set_metadata("paired_extension_token", "must-not-leave-machine")
    store.set_metadata("paired_extension_id", "abc")

    backup = store.export_backup()
    archive = Path(backup["path"])
    assert archive.is_file()
    assert backup["manifest"]["credentials_included"] is False

    store.set_metadata("test_marker", "after")
    restored = store.restore_backup(archive)
    assert restored["status"] == "restored"
    assert restored["pairing_reset"] is True
    assert store.get_metadata("test_marker") == "before"
    assert store.get_metadata("paired_extension_token") is None
    assert store.get_metadata("paired_extension_id") is None
    assert store.integrity_status()["ok"] is True


def test_corrupt_database_recovers_from_verified_checkpoint(tmp_path):
    db = tmp_path / "nextplan.db"
    store = SQLiteCanonicalStoreV3(db)
    store.set_metadata("recovery_marker", "safe")
    checkpoint = store.create_recovery_checkpoint()
    assert Path(checkpoint["path"]).is_file()

    db.write_bytes(b"not-a-sqlite-database")
    recovered = SQLiteCanonicalStoreV3(db)
    assert recovered.recovered_on_startup is True
    assert recovered.get_metadata("recovery_marker") == "safe"
    assert recovered.integrity_status()["ok"] is True


@pytest.mark.asyncio
async def test_v4_health_backup_endpoints_and_extension_origin_binding(tmp_path):
    app = create_local_app(tmp_path / "core.db", bootstrap_token="desktop-token", execution_dry_run=True)
    desktop = {"Authorization": "Bearer desktop-token"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["runtime"] == "nextplan-local-core-v4"
        assert health.json()["schema_version"] == 3
        assert health.json()["integrity"]["ok"] is True

        maintenance = await client.get("/maintenance/status", headers=desktop)
        assert maintenance.status_code == 200
        assert maintenance.json()["integrity"]["ok"] is True

        backup = await client.post("/backup/export", headers=desktop, json={})
        assert backup.status_code == 200
        backup_path = backup.json()["path"]
        assert Path(backup_path).is_file()

        code = (await client.post("/pairing/code", headers=desktop, json={})).json()["code"]
        paired = await client.post(
            "/pairing/complete",
            headers={"Origin": "chrome-extension://abc"},
            json={"code": code, "extension_id": "abc"},
        )
        assert paired.status_code == 200
        token = paired.json()["token"]
        good = await client.get("/state", headers={"Authorization": f"Bearer {token}", "Origin": "chrome-extension://abc"})
        assert good.status_code == 200
        evil = await client.get("/state", headers={"Authorization": f"Bearer {token}", "Origin": "chrome-extension://evil"})
        assert evil.status_code == 401

        restored = await client.post("/backup/restore", headers=desktop, json={"path": backup_path})
        assert restored.status_code == 200
        assert restored.json()["pairing_reset"] is True
        old_extension = await client.get("/state", headers={"Authorization": f"Bearer {token}", "Origin": "chrome-extension://abc"})
        assert old_extension.status_code == 401
