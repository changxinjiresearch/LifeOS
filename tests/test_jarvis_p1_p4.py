from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_server.jarvis_p0_contracts import JarvisContractError, make_sync_intent
from mcp_server.jarvis_workspace_v1 import JarvisWorkspace
from mcp_server.jarvis_brain_v1 import JarvisBrain


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JarvisWorkspace(Path(self.tmp.name) / "secure" / "jarvis.db")

    def seed(self):
        return self.store.bootstrap([
            {"id": "project-one", "name": "Experiment B", "status": "active",
             "next_action": "run checks", "priority": 2},
            {"id": "project-two", "name": "Write report", "status": "planned"}],
            explicitly_confirmed=True)

    def intent(self, op="op-one", revision=1, project="project-one"):
        return make_sync_intent(
            operation_id=op, device_id="chromeos-web", entity_type="project",
            entity_id=project, action="update_project",
            expected_revision=revision)

    def record(self, summary="We selected design B", source="manual_import"):
        return self.store.record_context({
            "context_type": "decision", "project_id": "project-one",
            "summary": summary, "source_kind": source, "source_ref": "manual://sample",
            "user_authorized": True, "confirmed_by_user": True})

    def test_empty_store_has_revision_zero(self):
        self.assertEqual(self.store.snapshot()["revision"], 0)

    def test_confirmed_bootstrap_once(self):
        self.seed()
        self.assertEqual(len(self.store.snapshot()["projects"]), 2)
        with self.assertRaises(JarvisContractError):
            self.seed()

    def test_bootstrap_requires_confirmation(self):
        with self.assertRaises(JarvisContractError):
            self.store.bootstrap([{"id": "p-01", "name": "test"}])

    def test_bootstrap_rejects_duplicates_without_partial_writes(self):
        with self.assertRaises(JarvisContractError):
            self.store.bootstrap([
                {"id": "project-one", "name": "First"},
                {"id": "project-one", "name": "Second"}], explicitly_confirmed=True)
        self.assertEqual(self.store.snapshot()["revision"], 0)

    def test_bootstrap_rejects_bad_status(self):
        with self.assertRaises(JarvisContractError):
            self.store.bootstrap([{"id":"project-one","name":"One","status":"trashed"}], explicitly_confirmed=True)

    def test_project_update_has_verified_receipt(self):
        self.seed()
        r = self.store.mutate(self.intent(), {"status": "completed"})
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["revision"], 2)
        self.assertTrue(r["verified"])
        self.assertEqual(self.store.snapshot()["projects"][0]["status"], "completed")

    def test_repeated_operation_is_idempotent(self):
        self.seed()
        a = self.store.mutate(self.intent(), {"status": "completed"})
        b = self.store.mutate(self.intent(), {"status": "waiting"})
        self.assertEqual(a["revision"], 2)
        self.assertEqual(b["status"], "already_applied")
        self.assertEqual(self.store.snapshot()["revision"], 2)
        self.assertEqual(self.store.snapshot()["projects"][0]["status"], "completed")

    def test_conflict_does_not_overwrite(self):
        self.seed()
        r = self.store.mutate(self.intent(revision=0), {"status": "completed"})
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(self.store.snapshot()["revision"], 1)

    def test_unmodified_value_is_no_change(self):
        self.seed()
        r = self.store.mutate(self.intent(), {"status": "active"})
        self.assertEqual(r["status"], "no_change")
        self.assertEqual(r["revision"], 1)

    def test_disallow_unknown_action_and_fields(self):
        self.seed()
        for values in [{"delete": True}, {"status": "deleted"}, {"priority": 100}]:
            with self.subTest(values=values), self.assertRaises(JarvisContractError):
                self.store.mutate(self.intent(), values)

    def test_unknown_project_is_rejected(self):
        self.seed()
        with self.assertRaises(JarvisContractError):
            self.store.mutate(self.intent(project="not-found"), {"status": "completed"})

    def test_store_survives_reopen(self):
        self.seed()
        second = JarvisWorkspace(self.store.path)
        self.assertEqual(second.snapshot()["revision"], 1)
        self.assertEqual(len(second.snapshot()["projects"]), 2)

    def test_knowledge_requires_explicit_consent(self):
        with self.assertRaises(JarvisContractError):
            self.store.record_context({
                "context_type":"decision", "project_id":"project-one",
                "summary":"Choice B","source_kind":"manual_import",
                "source_ref":"manual://item","user_authorized":False,
                "confirmed_by_user":True})

    def test_knowledge_receipt_must_be_verified_server_side(self):
        with self.assertRaises(JarvisContractError):
            self.store.record_context({
                "context_type":"handoff", "project_id":"project-one",
                "summary":"Executed external action","source_kind":"jarvis_verified_receipt",
                "source_ref":"receipt://client-claimed","user_authorized":True,
                "confirmed_by_user":True})

    def test_knowledge_deduplicated(self):
        a = self.record()
        b = self.record()
        self.assertEqual(a["status"], "recorded")
        self.assertEqual(b["status"], "already_exists")
        self.assertEqual(a["id"], b["id"])

    def test_query_filters_and_source(self):
        self.record()
        self.store.record_context({
            "context_type":"observation","project_id":"project-two",
            "summary":"Other project only","source_kind":"manual_import",
            "source_ref":"manual://other","user_authorized":True,
            "confirmed_by_user":True})
        r = self.store.search(query="design",project_id="project-one")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["source_ref"], "manual://sample")
        self.assertEqual(self.store.search(query="unknown"), [])

    def test_search_literal_wildcards(self):
        self.record("Project uses 70% allocation")
        self.assertEqual(len(self.store.search(query="70%")), 1)
        self.assertEqual(self.store.search(query="70_"), [])

    def test_user_can_delete_knowledge(self):
        r = self.record()
        with self.assertRaises(JarvisContractError):
            self.store.delete_context(r["id"], confirmed=False)
        self.assertEqual(self.store.delete_context(r["id"], confirmed=True)["status"], "deleted")
        self.assertEqual(self.store.search(), [])

    def test_export_only_selected_project(self):
        self.seed()
        self.record()
        export = self.store.context_bundle("project-one")
        self.assertEqual(export["format"], "nextplan-jarvis-context-v1")
        self.assertEqual(len(export["projects"]), 1)
        self.assertEqual(len(export["knowledge"]), 1)

    def test_private_db_permissions(self):
        if os.name != "nt":
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)


class BrainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JarvisWorkspace(Path(self.tmp.name) / "jarvis.db")
        self.store.bootstrap([{"id":"project-one","name":"Research RP","status":"active",
                               "next_action":"Run P2 experiment"}], explicitly_confirmed=True)

    async def test_brain_read_only_state_grounding(self):
        with patch.dict(os.environ, {"NEXTPLAN_JARVIS_MODEL_URL": "", "NEXTPLAN_JARVIS_MODEL_NAME": ""}):
            r = await JarvisBrain(self.store).ask("Research RP 进度")
        self.assertIn("Research RP", r["answer"])
        self.assertEqual(r["executed_actions"], 0)
        self.assertEqual(r["mode"], "deterministic_grounded_fallback")

    async def test_missing_chat_history_is_not_invented(self):
        r = await JarvisBrain(self.store).ask("Why did I choose experiment Z?")
        self.assertNotEqual(r["status"], "failed")
        self.assertEqual(r["sources"], [])

    async def test_model_adapter_refuses_unapproved_remote_host(self):
        with patch.dict(os.environ, {"NEXTPLAN_JARVIS_MODEL_URL":"http://169.254.169.254",
                                     "NEXTPLAN_JARVIS_MODEL_NAME":"test-model", "NEXTPLAN_JARVIS_MODEL_HOSTS":""}):
            with self.assertRaises(JarvisContractError):
                JarvisBrain._model_url()

    async def test_capabilities_deny_any_automatic_computer_actions(self):
        cap = JarvisBrain(self.store).capabilities()
        self.assertFalse(cap["can_execute_computer_actions"])
        self.assertFalse(cap["can_read_chatgpt_internal_memory"])


if __name__ == "__main__":
    unittest.main()
