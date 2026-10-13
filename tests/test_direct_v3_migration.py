"""Read-only migration rehearsal using the checked-in legacy snapshot.

No GitHub writes, no Railway writes, and never publishes migrated database files.
"""
import json
import tempfile
import unittest
from pathlib import Path

from mcp_server.direct_v3 import DirectStore,digest

ROOT=Path(__file__).resolve().parents[1]

class MigrationRehearsal(unittest.TestCase):
    def test_full_legacy_snapshot_roundtrip(self):
        original=json.loads((ROOT/"state.json").read_text(encoding="utf-8"))
        self.assertTrue(original["projects"])
        self.assertIsInstance(original["events"],list)
        before=digest(original)
        with tempfile.TemporaryDirectory() as tmp:
            store=DirectStore(Path(tmp)/"nextplan_test.sqlite3")
            receipt=store.bootstrap(original,confirmed=True,expected_hash=before)
            self.assertEqual(receipt["sha256"],before)
            snapshot=store.snapshot()
            self.assertEqual(snapshot["revision"],0)
            self.assertEqual(snapshot["state"],original)
            self.assertEqual(digest(snapshot["state"]),before)
            self.assertEqual(receipt["project_count"],len(original["projects"]))
            self.assertEqual(set(snapshot["state"]),set(original))
