"""P0 contracts: side-effect-free regression tests for state/context boundaries."""
from __future__ import annotations

import unittest

from mcp_server.jarvis_p0_contracts import (
    JarvisContractError,
    CONTRACT_VERSION,
    build_context_candidate,
    check_storage_policy,
    check_sync_intent,
    make_sync_intent,
)


class JarvisP0ContractsTests(unittest.TestCase):
    def sync(self, **overrides):
        params = {
            "operation_id": "op-001",
            "device_id": "mac-arm64",
            "entity_type": "project",
            "entity_id": "example-project",
            "action": "update_project",
            "expected_revision": 11,
        }
        params.update(overrides)
        return make_sync_intent(**params)

    def context(self, **overrides):
        params = {
            "context_type": "decision",
            "project_id": "example-project",
            "summary": "Use experiment B because experiment A leaked labels.",
            "source_kind": "chatgpt_user_turn",
            "source_ref": "chatgpt://conversation/abc#turn-8",
            "user_authorized": True,
            "confirmed_by_user": True,
        }
        params.update(overrides)
        return build_context_candidate(**params)

    def test_sync_envelope_is_proposed_not_applied(self):
        intent = self.sync()
        self.assertEqual(intent["protocol_version"], CONTRACT_VERSION)
        self.assertEqual(intent["status"], "proposed")
        self.assertEqual(intent["expected_revision"], 11)

    def test_sync_ready_requires_matching_revision(self):
        self.assertEqual(
            check_sync_intent(self.sync(), canonical_revision=11, applied_operation_ids=[])["status"],
            "ready_for_policy_check",
        )

    def test_sync_version_conflict_is_explicit(self):
        receipt = check_sync_intent(self.sync(), canonical_revision=12, applied_operation_ids=[])
        self.assertEqual(receipt["status"], "conflict")
        self.assertEqual(receipt["canonical_revision"], 12)

    def test_repeated_operation_is_idempotent_even_with_stale_revision(self):
        receipt = check_sync_intent(self.sync(), canonical_revision=14, applied_operation_ids=["op-001"])
        self.assertEqual(receipt["status"], "already_applied")

    def test_cannot_claim_user_authority_from_assistant(self):
        with self.assertRaises(JarvisContractError):
            self.sync(authority="assistant_text")

    def test_invalid_revision_rejected(self):
        for revision in [-1, True, "5"]:
            with self.subTest(revision=revision), self.assertRaises(JarvisContractError):
                self.sync(expected_revision=revision)

    def test_tampered_envelope_cannot_be_applied(self):
        intent = self.sync()
        intent["authority"] = "assistant_text"
        with self.assertRaises(JarvisContractError):
            check_sync_intent(intent, canonical_revision=11, applied_operation_ids=[])

    def test_chat_context_requires_user_authorization(self):
        with self.assertRaises(JarvisContractError):
            self.context(user_authorized=False)

    def test_chat_summary_requires_user_confirmation(self):
        with self.assertRaises(JarvisContractError):
            self.context(confirmed_by_user=False)

    def test_context_provenance_fingerprint_stable(self):
        a = self.context()
        b = self.context()
        self.assertEqual(a["fingerprint"], b["fingerprint"])
        self.assertEqual(a["privacy"], "private")
        self.assertEqual(a["storage_status"], "not_persisted")
        self.assertEqual(a["source"]["kind"], "chatgpt_user_turn")

    def test_unverified_jarvis_action_is_not_completed_handoff(self):
        with self.assertRaises(JarvisContractError):
            self.context(context_type="handoff", source_kind="jarvis_verified_receipt",
                         confirmed_by_user=False, verified_receipt={"status": "accepted"})

    def test_jarvis_handoff_requires_postcondition(self):
        with self.assertRaises(JarvisContractError):
            self.context(context_type="handoff", source_kind="jarvis_verified_receipt",
                         confirmed_by_user=False, verified_receipt={
                             "status": "verified", "verification": {"status": "failed"}
                         })

    def test_verified_jarvis_handoff_is_candidate_not_execution(self):
        result = self.context(context_type="handoff", source_kind="jarvis_verified_receipt",
                              confirmed_by_user=False, verified_receipt={
                                  "status": "verified", "verification": {"status": "verified"}
                              })
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["storage_status"], "not_persisted")

    def test_never_allow_public_github_for_context(self):
        item = self.context()
        for destination in ("public_repo", "public_web", "github_public", "telemetry"):
            with self.subTest(destination=destination), self.assertRaises(JarvisContractError):
                check_storage_policy(item, destination=destination)

    def test_private_storage_possible_but_not_persisted(self):
        status = check_storage_policy(self.context(), destination="local_encrypted")
        self.assertEqual(status["status"], "approved_for_private_storage")

    def test_token_like_content_rejected(self):
        examples = ["Bearer abcdefghijklmnop123", "api_key=abcdef123456", "password=supersecret123"]
        for secret in examples:
            with self.subTest(secret_type=secret.split(" ")[0][:8]), self.assertRaises(JarvisContractError):
                self.context(summary="User data " + secret)

    def test_unapproved_source_does_not_create_context(self):
        with self.assertRaises(JarvisContractError):
            self.context(source_kind="assistant_summary")

    def test_no_raw_chat_transcript_is_in_minimal_record(self):
        record = self.context()
        self.assertEqual(
            set(record.keys()),
            {"protocol_version", "record_type", "context_type", "project_id",
             "summary", "source", "confirmed", "privacy", "storage_status", "fingerprint"},
        )


if __name__ == "__main__":
    unittest.main()
