from mcp_server.cloud_classifier_v6 import classify_turn
from mcp_server.conversation_capture import capture_conversational_fact


def _state(resume_status="active"):
    return {
        "projects": [
            {
                "id": "internship",
                "name": "帮助宝宝找实习",
                "status": "active",
                "next_action": "做简历",
                "milestones": [
                    {"id": "resume", "name": "做简历", "status": resume_status},
                    {"id": "auto-apply", "name": "搭建自动投简历工作流", "status": "planned"},
                ],
            },
            {
                "id": "paper",
                "name": "论文投稿",
                "status": "active",
                "next_action": "等待编辑回复",
                "milestones": [
                    {"id": "editor", "name": "编辑回复", "status": "active"},
                    {"id": "review", "name": "外审流程", "status": "planned"},
                ],
            },
        ]
    }


def _turn(user, assistant=""):
    return {"userText": user, "assistantText": assistant, "title": "ChatGPT"}


def test_ordinary_completion_fact_matches_fuzzy_milestone_and_autosyncs():
    candidate = capture_conversational_fact(_turn("我现在已经把宝宝简历做完了。"), _state())
    assert candidate is not None
    assert candidate["kind"] == "conversation_fact"
    assert candidate["requiresConfirmation"] is False
    assert candidate["confidence"] >= 0.88
    assert candidate["action"]["action"] == "complete_task"
    assert candidate["action"]["project_id"] == "internship"
    assert candidate["action"]["task_id"] == "resume"
    assert candidate["provenance"]["sourceAuthority"] == "user_assertion"
    assert candidate["provenance"]["assistantUsedAsEvidence"] is False


def test_speculation_does_not_write():
    assert capture_conversational_fact(_turn("宝宝简历可能快做完了。"), _state()) is None


def test_negated_completion_does_not_write():
    assert capture_conversational_fact(_turn("宝宝简历还没做完。"), _state()) is None


def test_assistant_only_claim_cannot_create_canonical_fact():
    candidate = capture_conversational_fact(
        _turn("好的。", "宝宝简历现在已经正式完成。"),
        _state(),
    )
    assert candidate is None


def test_already_completed_is_informational_noop():
    candidate = capture_conversational_fact(_turn("宝宝简历已经做完了。"), _state("completed"))
    assert candidate is not None
    assert candidate["informational"] is True
    assert candidate["action"] is None


def test_explicit_nextplan_command_falls_through_to_legacy_classifier():
    state = _state()
    assert capture_conversational_fact(_turn("NextPlan：把做简历标记为完成。"), state) is None
    candidate = classify_turn(_turn("NextPlan：把做简历标记为完成。"), state, {})
    assert candidate is not None
    assert candidate["action"]["action"] == "complete_task"


def test_waiting_fact_is_captured():
    candidate = capture_conversational_fact(_turn("编辑回复现在还在等待结果。"), _state())
    assert candidate is not None
    assert candidate["action"]["action"] == "update_milestone"
    assert candidate["action"]["project_id"] == "paper"
    assert candidate["action"]["milestone_id"] == "editor"
    assert candidate["action"]["status"] == "waiting"


def test_blocked_fact_is_captured_without_destructive_action():
    candidate = capture_conversational_fact(_turn("搭建自动投简历工作流现在被权限卡住了。"), _state())
    assert candidate is not None
    assert candidate["action"]["action"] == "update_milestone"
    assert candidate["action"]["status"] == "blocked"
    assert candidate["destructive"] is False


def test_project_level_status_change_requires_confirmation():
    candidate = capture_conversational_fact(_turn("论文投稿完成了。"), _state())
    assert candidate is not None
    assert candidate["kind"] == "conversation_project_fact"
    assert candidate["requiresConfirmation"] is True
    assert candidate["action"]["action"] == "update_project"


def test_ambiguous_milestone_match_requires_confirmation():
    state = {
        "projects": [
            {"id": "a", "name": "A", "status": "active", "milestones": [{"id": "x", "name": "准备简历", "status": "active"}]},
            {"id": "b", "name": "B", "status": "active", "milestones": [{"id": "y", "name": "修改简历", "status": "active"}]},
        ]
    }
    candidate = capture_conversational_fact(_turn("简历做完了。"), state)
    assert candidate is not None
    assert candidate["requiresConfirmation"] is True
