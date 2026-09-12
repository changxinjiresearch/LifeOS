from __future__ import annotations

import unittest

from mcp_server import cloud_classifier_v2 as classifier
from mcp_server import server_v6


class PhaseAContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "projects": [
                {
                    "id": "pcc-v2",
                    "name": "PCC v2-R2",
                    "category": "科研",
                    "status": "active",
                    "priority": 3,
                    "next_action": "R4 Main Training",
                    "milestones": [
                        {"id": "r4", "name": "R4 Main Training", "status": "active"}
                    ],
                },
                {
                    "id": "pcc-v1",
                    "name": "PCC 第一篇论文",
                    "category": "科研",
                    "status": "waiting",
                    "priority": 3,
                    "next_action": "等待编辑",
                    "milestones": [
                        {"id": "editorial", "name": "编辑流程", "status": "waiting"}
                    ],
                },
                {
                    "id": "nextplan",
                    "name": "NextPlan开发",
                    "category": "其他",
                    "status": "active",
                    "priority": 2,
                    "next_action": "NextPlan Sync Command Protocol",
                    "milestones": [
                        {"id": "sync", "name": "NextPlan Sync Command Protocol", "status": "active"}
                    ],
                },
            ],
            "events": [
                {"project_id": "nextplan"},
                {"project_id": "pcc-v2"},
                {"project_id": "pcc-v1"},
            ],
        }

    def test_exact_project_resolution_is_safe_for_auto_resolution(self) -> None:
        resolved = classifier.resolve_project(
            "更新 NextPlan开发 的下一步",
            "",
            "",
            self.state,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["entity_id"], "nextplan")
        self.assertEqual(resolved["method"], "user_exact")
        self.assertFalse(resolved["requires_confirmation"])

    def test_referential_rename_never_treats_this_project_as_literal_name(self) -> None:
        candidate = classifier.classify_turn(
            {
                "userText": "把这个项目改成 NextPlan开发新版",
                "assistantText": "当前我们正在继续开发 NextPlan开发。",
                "title": "NextPlan开发",
            },
            self.state,
            {},
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["kind"], "contextual_project_rename")
        self.assertEqual(candidate["action"]["project_id"], "nextplan")
        self.assertEqual(candidate["action"]["name"], "NextPlan开发新版")
        self.assertNotEqual(candidate["action"]["name"], "这个")

    def test_ambiguous_project_reference_requires_confirmation(self) -> None:
        resolved = classifier.resolve_project(
            "PCC这个项目下一步继续实验",
            "",
            "PCC",
            self.state,
        )
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved["requires_confirmation"])
        self.assertGreaterEqual(len(resolved["alternatives"]), 1)

    def test_destructive_contextual_delete_always_requires_confirmation(self) -> None:
        candidate = classifier.classify_turn(
            {
                "userText": "把PCC这个项目删除",
                "assistantText": "",
                "title": "PCC",
            },
            self.state,
            {},
        )
        self.assertIsNotNone(candidate)
        self.assertTrue(candidate["destructive"])
        self.assertTrue(candidate["requiresConfirmation"])

    def test_protocol_normalization_adds_operation_id_and_confirmation_contract(self) -> None:
        raw = {
            "id": "candidate-12345678",
            "kind": "direct_project_edit",
            "confidence": 0.99,
            "label": "更新项目",
            "reason": "明确变更",
            "action": {"action": "update_project_snapshot", "project_id": "nextplan"},
        }
        normalized = server_v6._normalize_candidate(raw)
        self.assertEqual(normalized["protocol_version"], "1.0")
        self.assertEqual(normalized["action"]["operation_id"], "candidate-12345678")
        self.assertFalse(normalized["confirmation"]["required"])
        self.assertEqual(normalized["target"]["entity_type"], "project")
        self.assertEqual(normalized["target"]["entity_id"], "nextplan")

    def test_receipt_contract_is_normalized(self) -> None:
        action = {
            "operation_id": "candidate-12345678",
            "action": "update_project_snapshot",
            "project_id": "nextplan",
        }
        result = {
            "status": "applied",
            "event_id": "evt-123",
            "commit_sha": "abc123",
        }
        receipt = server_v6._receipt(action, result)
        self.assertEqual(receipt["receipt_version"], "1.0")
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(receipt["operation_id"], "candidate-12345678")
        self.assertEqual(receipt["operation"], "update_project_snapshot")
        self.assertEqual(receipt["entity_type"], "project")
        self.assertEqual(receipt["entity_id"], "nextplan")
        self.assertEqual(receipt["event_id"], "evt-123")
        self.assertEqual(receipt["commit_sha"], "abc123")


if __name__ == "__main__":
    unittest.main()
