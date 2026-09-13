from __future__ import annotations

import re
import uuid
from typing import Any

from .cloud_classifier import exact_project_mention
from .cloud_classifier_v6 import classify_turn as classify_existing_state
from .project_intelligence_v1 import discover_project_change


_STATUS_ALIASES = {
    "waiting": "waiting",
    "等待": "waiting",
    "待定": "waiting",
    "active": "active",
    "进行中": "active",
    "正在进行": "active",
    "已开始": "active",
    "blocked": "blocked",
    "阻塞": "blocked",
    "已阻塞": "blocked",
    "暂停": "blocked",
    "planned": "planned",
    "计划中": "planned",
    "待开始": "planned",
    "未开始": "planned",
    "completed": "completed",
    "done": "completed",
    "已完成": "completed",
    "完成": "completed",
}


def _attach_action_provenance(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    value = dict(candidate)
    action = value.get("action")
    if isinstance(action, dict):
        action = dict(action)
        cid = str(value.get("id") or "").strip()
        if cid:
            action.setdefault("operation_id", cid)
        provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
        if provenance.get("evidenceText"):
            action.setdefault("evidence_text", str(provenance["evidenceText"])[:500])
        value["action"] = action
    return value


def _normalize_nextplan_command_turn(turn: dict[str, Any]) -> dict[str, Any]:
    """Accept `NextPlan：...`, `NextPlan: ...`, and `NextPlan ...` equally."""
    normalized = dict(turn)
    user_text = str(turn.get("userText") or "")
    normalized["userText"] = re.sub(
        r"next\s*plan\s*[：:]\s*",
        "NextPlan ",
        user_text,
        flags=re.I,
    )
    return normalized


def _explicit_project_status(turn: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    text = str(turn.get("userText") or "").strip()
    if not text or not re.search(r"next\s*plan", text, re.I):
        return None
    # Leave task/milestone status commands to the existing task classifier.
    if re.search(r"任务|task", text, re.I):
        return None
    project = exact_project_mention(text, state)
    if not project:
        return None
    match = re.search(
        r"(?:项目\s*)?(?:状态\s*)?(?:设置为|设为|改为|改成|变为|置为)\s*"
        r"(waiting|active|blocked|planned|completed|done|等待|待定|进行中|正在进行|已开始|阻塞|已阻塞|暂停|计划中|待开始|未开始|已完成|完成)(?:\s|[，。！？!]|$)",
        text,
        re.I,
    )
    if not match:
        return None
    raw = match.group(1)
    status = _STATUS_ALIASES.get(raw.casefold()) or _STATUS_ALIASES.get(raw)
    if not status:
        return None
    current = str(project.get("status") or "")
    if current == "done":
        current = "completed"
    if current == status:
        return {
            "id": str(uuid.uuid4()),
            "kind": "project_status_already_applied",
            "confidence": 1.0,
            "informational": True,
            "label": f"项目状态已是：{project.get('name')} · {status}",
            "reason": "明确项目状态指令与 canonical state 已一致",
            "action": None,
        }
    return {
        "id": str(uuid.uuid4()),
        "kind": "direct_project_status",
        "confidence": 0.99,
        "label": f"更新项目状态：{project.get('name')} → {status}",
        "reason": "检测到明确的项目状态设置指令",
        "action": {
            "action": "update_project_snapshot",
            "project_id": project["id"],
            "status": status,
        },
    }


def classify_local_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Local conversational intelligence composition with explicit status support."""
    normalized_turn = _normalize_nextplan_command_turn(turn)

    direct_status = _explicit_project_status(normalized_turn, state)
    if direct_status is not None:
        return _attach_action_provenance(direct_status)

    existing = classify_existing_state(normalized_turn, state, client or {})
    if existing is not None:
        return _attach_action_provenance(existing)
    return _attach_action_provenance(discover_project_change(normalized_turn, state))
