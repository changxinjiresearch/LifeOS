from __future__ import annotations

import re
import uuid
from typing import Any


_STATUS_MAP = {
    "active": "active",
    "进行中": "active",
    "正在进行": "active",
    "已开始": "active",
    "waiting": "waiting",
    "等待": "waiting",
    "待定": "waiting",
    "planned": "planned",
    "计划中": "planned",
    "未开始": "planned",
    "尚未开始": "planned",
    "completed": "completed",
    "done": "completed",
    "已完成": "completed",
    "完成": "completed",
    "blocked": "blocked",
    "阻塞": "blocked",
    "暂停": "blocked",
}

_STATUS_RE = re.compile(
    r'(?:把|将)\s*[“\"「『]?([^”\"」』，。]+?)[”\"」』]?\s*(?:项目)?\s*'
    r'(?:设置为|设为|改成|改为|标记为|设置成)\s*'
    r'(active|waiting|planned|completed|done|blocked|进行中|正在进行|已开始|等待|待定|计划中|未开始|尚未开始|已完成|完成|阻塞|暂停)',
    re.I,
)


def _clean_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[\s“”\"'「」『』【】]+|[\s“”\"'「」『』【】]+$", "", text)
    text = re.sub(r"\s*项目$", "", text, flags=re.I)
    return text.strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_name(value)).casefold()


def normalize_turn(turn: dict[str, Any]) -> dict[str, Any]:
    value = dict(turn)
    text = str(value.get("userText") or "")
    text = re.sub(r"next\s*plan\s*[：:]\s*", "NextPlan ", text, flags=re.I)
    text = re.sub(
        r"((?:新增|新建|创建|添加)\s*(?:一个)?\s*(?:新)?项目)(?=[^\s：:，。])",
        r"\1 ",
        text,
        flags=re.I,
    )
    value["userText"] = text.strip()
    return value


def classify_compat_command(turn: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    text = str(turn.get("userText") or "").strip()
    if not text or not re.search(r"next\s*plan", text, re.I):
        return None
    source = re.sub(r"^\s*next\s*plan\s*", "", text, flags=re.I).strip()
    match = _STATUS_RE.search(source)
    if not match:
        return None
    project_name = _clean_name(match.group(1))
    status = _STATUS_MAP.get(match.group(2).casefold()) or _STATUS_MAP.get(match.group(2))
    if not project_name or not status:
        return None
    project = next((p for p in state.get("projects", []) if _norm(p.get("name")) == _norm(project_name)), None)
    if not project:
        return None
    if str(project.get("status") or "") == status:
        return {
            "id": str(uuid.uuid4()),
            "kind": "project_status_already_applied",
            "confidence": 1.0,
            "informational": True,
            "label": f"项目状态已是 {status}：{project.get('name')}",
            "reason": "显式项目状态指令与 canonical state 已一致",
            "action": None,
        }
    return {
        "id": str(uuid.uuid4()),
        "kind": "direct_project_status",
        "confidence": 0.99,
        "label": f"更新项目状态：{project.get('name')} → {status}",
        "reason": "检测到明确的 NextPlan 项目状态设置指令",
        "action": {
            "action": "update_project",
            "project_id": project["id"],
            "status": status,
            "capture_source": "explicit_nextplan_command",
        },
    }
