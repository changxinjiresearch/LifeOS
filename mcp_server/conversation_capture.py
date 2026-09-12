from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher
from typing import Any


# Conversational State Capture (Stage IV)
#
# Authority rule:
#   * user factual assertions may become canonical write candidates;
#   * assistant text is context only and MUST NOT create a canonical fact by itself;
#   * speculation, plans, questions, negation and destructive implications do not auto-write.

_UNCERTAIN_RE = re.compile(
    r"(?:可能|也许|大概|应该|或许|估计|似乎|看起来|感觉|我觉得|我想|希望|计划|打算|准备|"
    r"快要|快做完|差不多|maybe|probably|perhaps|might|could|should|hope|plan\s+to|want\s+to|going\s+to)",
    re.I,
)
_FUTURE_RE = re.compile(r"(?:明天|后天|今晚|稍后|等会|待会|之后|下周|下个月|将会|会去|准备去|later|tomorrow|next\s+week)", re.I)
_NEGATED_COMPLETION_RE = re.compile(
    r"(?:还没|没有|尚未|未|没)(?:有)?[^，。！？\n]{0,12}(?:完成|做完|做好|搞定|结束)|"
    r"(?:not\s+done|not\s+finished|unfinished|haven't\s+finished|hasn't\s+finished)",
    re.I,
)
_EXPLICIT_COMMAND_RE = re.compile(r"next\s*plan|帮我(?:记录|更新|修改|改|标记|写入)|(?:记录|写入|更新|修改).{0,12}next\s*plan", re.I)

_COMPLETION_PATTERNS = [
    re.compile(
        r"(?:我(?:们)?\s*)?(?:现在|刚刚|刚才|今天|终于)?\s*(?:已经\s*)?(?:把\s*)?"
        r"(?P<subject>[^，。！？\n]{1,48}?)\s*(?:现在|刚刚|刚才|已经|终于)?\s*(?:正式\s*)?"
        r"(?:做完了|完成了|做好了|搞定了|弄完了|结束了)(?:[。！!]|$)",
        re.I,
    ),
    re.compile(
        r"(?P<subject>[^，。！？\n]{1,48}?)\s*(?:is|are|has\s+been)?\s*(?:now\s+)?(?:officially\s+)?(?:done|finished|completed)(?:[.!]|$)",
        re.I,
    ),
]

_WAITING_PATTERNS = [
    re.compile(r"(?P<subject>[^，。！？\n]{1,48}?)\s*(?:现在)?\s*(?:正在|还在|在)?\s*(?:等待|等着|等)\s*(?:回复|结果|审批|决定|通知|反馈|response|result|decision)?(?:[。！!]|$)", re.I),
]

_BLOCKED_PATTERNS = [
    re.compile(r"(?P<subject>[^，。！？\n]{1,48}?)\s*(?:现在)?\s*(?:被[^，。！？\n]{0,20})?(?:卡住了|阻塞了|blocked)(?:[。！!]|$)", re.I),
]

_ACTIVE_PATTERNS = [
    re.compile(r"(?:我(?:们)?\s*)?(?:现在|已经)?\s*(?:开始|正在)\s*(?:做|处理|推进|进行)?\s*(?P<subject>[^，。！？\n]{1,48}?)(?:[。！!]|$)", re.I),
]

_GENERIC_WORDS = (
    "这个", "那个", "这项", "那项", "这一项", "这一步", "那一步", "任务", "步骤", "阶段", "项目",
    "帮", "帮助", "做", "制作", "进行", "处理", "推进", "开始", "完成", "更新", "准备", "搭建", "弄",
    "一下", "一下子", "已经", "现在", "刚刚", "刚才", "终于", "正式", "我", "我们", "把", "给",
)


def _id() -> str:
    return str(uuid.uuid4())


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(value or "").casefold())


def _salient(value: Any) -> str:
    text = _compact(value)
    # Remove generic action/function words but preserve domain nouns such as 宝宝/简历/导师/PCC.
    for word in sorted(_GENERIC_WORDS, key=len, reverse=True):
        text = text.replace(_compact(word), "")
    return text


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _similarity(a: Any, b: Any) -> float:
    aa = _salient(a)
    bb = _salient(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    if aa in bb or bb in aa:
        shorter = min(len(aa), len(bb))
        longer = max(len(aa), len(bb))
        return 0.90 + 0.10 * (shorter / max(1, longer))
    seq = SequenceMatcher(None, aa, bb).ratio()
    A, B = _bigrams(aa), _bigrams(bb)
    jac = len(A & B) / max(1, len(A | B))
    return max(seq, 0.55 * seq + 0.45 * jac)


def _clean_subject(raw: str) -> str:
    value = str(raw or "").strip(" \t\n，。！？!?:：;；'\"“”‘’「」『』")
    value = re.sub(r"^(?:我(?:们)?\s*)?(?:现在|刚刚|刚才|今天|终于)?\s*(?:已经\s*)?(?:把\s*)?", "", value, flags=re.I)
    value = re.sub(r"(?:这一步|这一项|这项任务|这个任务|这个项目)$", "", value, flags=re.I)
    return value.strip()


def _extract_fact(text: str) -> tuple[str, str] | None:
    if not text or re.search(r"[?？]\s*$", text):
        return None
    if _UNCERTAIN_RE.search(text) or _NEGATED_COMPLETION_RE.search(text):
        return None

    for pattern in _COMPLETION_PATTERNS:
        match = pattern.search(text)
        if match:
            subject = _clean_subject(match.group("subject"))
            if subject and not _FUTURE_RE.search(match.group(0)):
                return "completed", subject

    for status, patterns in (("waiting", _WAITING_PATTERNS), ("blocked", _BLOCKED_PATTERNS), ("active", _ACTIVE_PATTERNS)):
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                subject = _clean_subject(match.group("subject"))
                if subject and not _FUTURE_RE.search(match.group(0)):
                    return status, subject
    return None


def _rank_entities(subject: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for project in state.get("projects", []):
        p_score = _similarity(subject, project.get("name"))
        for milestone in project.get("milestones", []):
            m_score = _similarity(subject, milestone.get("name"))
            # Project context is only a weak bonus; milestone wording remains the main evidence.
            score = max(m_score, 0.82 * m_score + 0.18 * p_score)
            ranked.append({"kind": "milestone", "project": project, "milestone": milestone, "score": score})
        ranked.append({"kind": "project", "project": project, "score": p_score})
    ranked.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return ranked


def _candidate_for_match(status: str, subject: str, match: dict[str, Any], runner_up: float, user_text: str) -> dict[str, Any] | None:
    score = float(match.get("score", 0.0))
    margin = score - float(runner_up)
    if score < 0.58:
        return None

    # Strong unique matches may auto-sync. Lower-confidence matches are surfaced for confirmation.
    needs_confirmation = score < 0.78 or margin < 0.08
    confidence = min(0.99, 0.72 + 0.27 * score)

    provenance = {
        "conversationCapture": True,
        "sourceAuthority": "user_assertion",
        "assistantUsedAsEvidence": False,
        "evidenceText": user_text[:500],
        "matchedSubject": subject,
        "entityScore": round(score, 4),
        "entityMargin": round(margin, 4),
    }

    if match["kind"] == "milestone":
        project = match["project"]
        milestone = match["milestone"]
        current = str(milestone.get("status") or "")
        if current in {"done", "completed"} and status == "completed":
            return {
                "id": _id(),
                "kind": "conversation_fact_noop",
                "confidence": 0.99,
                "informational": True,
                "label": f"已是完成状态：{milestone.get('name')}",
                "reason": "用户确认了一个已存在于 canonical state 的完成事实",
                "action": None,
                "provenance": provenance,
            }
        if current == status:
            return {
                "id": _id(),
                "kind": "conversation_fact_noop",
                "confidence": 0.99,
                "informational": True,
                "label": f"状态已一致：{milestone.get('name')} · {status}",
                "reason": "用户陈述与 canonical state 已一致",
                "action": None,
                "provenance": provenance,
            }

        if status == "completed":
            action = {
                "action": "complete_task",
                "project_id": project["id"],
                "task_id": milestone["id"],
                "capture_source": "conversation_user_fact",
            }
        else:
            action = {
                "action": "update_milestone",
                "project_id": project["id"],
                "milestone_id": milestone["id"],
                "status": status,
                "capture_source": "conversation_user_fact",
            }
        return {
            "id": _id(),
            "kind": "conversation_fact",
            "confidence": confidence,
            "requiresConfirmation": needs_confirmation,
            "destructive": False,
            "label": f"对话状态同步：{milestone.get('name')} → {status}",
            "reason": "检测到用户对现实状态的明确事实陈述" + ("；实体匹配需确认" if needs_confirmation else "；实体匹配唯一且置信度高"),
            "action": action,
            "provenance": provenance,
        }

    # Whole-project status writes are more consequential than milestone writes.
    project = match["project"]
    current = str(project.get("status") or "")
    if (current in {"done", "completed"} and status == "completed") or current == status:
        return {
            "id": _id(),
            "kind": "conversation_project_fact_noop",
            "confidence": 0.99,
            "informational": True,
            "label": f"项目状态已一致：{project.get('name')} · {current}",
            "reason": "用户陈述与 canonical project state 已一致",
            "action": None,
            "provenance": provenance,
        }
    return {
        "id": _id(),
        "kind": "conversation_project_fact",
        "confidence": confidence,
        "requiresConfirmation": True,
        "destructive": False,
        "label": f"建议同步项目状态：{project.get('name')} → {status}",
        "reason": "识别到项目级事实变化；项目级状态变更默认要求确认",
        "action": {
            "action": "update_project",
            "project_id": project["id"],
            "status": status,
            "capture_source": "conversation_user_fact",
        },
        "provenance": provenance,
    }


def capture_conversational_fact(turn: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """Return a safe write candidate for an ordinary conversational fact.

    This intentionally ignores assistant-only assertions. The assistant may explain a
    result, but it cannot manufacture the evidence that makes the result canonical.
    """
    user_text = str(turn.get("userText") or "").strip()
    if not user_text:
        return None
    # Explicit commands continue through the existing command classifier so old
    # NextPlan behavior stays stable and deterministic.
    if _EXPLICIT_COMMAND_RE.search(user_text):
        return None

    fact = _extract_fact(user_text)
    if not fact:
        return None
    status, subject = fact
    ranked = _rank_entities(subject, state)
    if not ranked:
        return None

    best = ranked[0]
    # Compare against the next *different entity* to detect ambiguity.
    runner_up = 0.0
    best_key = (
        best.get("kind"),
        str(best.get("project", {}).get("id") or ""),
        str(best.get("milestone", {}).get("id") or ""),
    )
    for item in ranked[1:]:
        key = (
            item.get("kind"),
            str(item.get("project", {}).get("id") or ""),
            str(item.get("milestone", {}).get("id") or ""),
        )
        if key != best_key:
            runner_up = float(item.get("score", 0.0))
            break
    return _candidate_for_match(status, subject, best, runner_up, user_text)
