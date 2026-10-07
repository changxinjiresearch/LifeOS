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

_STATUS_WORDS = (
    "active|waiting|planned|completed|done|blocked|进行中|正在进行|已开始|等待|待定|"
    "计划中|未开始|尚未开始|已完成|完成|阻塞|暂停"
)

_STATUS_RE = re.compile(
    rf'(?:把|将)\s*(?P<targets>.+?)\s*'
    rf'(?:(?:这|这些|这几个|\d+个|[一二三四五六七八九十两]+个)\s*)?'
    rf'(?:项目)?\s*(?:的)?\s*(?:状态)?\s*(?:全部|都)?\s*'
    rf'(?:更新为|更新成|设置为|设为|改成|改为|标记为|设置成)\s*'
    rf'(?P<status>{_STATUS_WORDS})',
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


def _target_names(raw: str) -> list[str]:
    source = str(raw or "").strip()
    quoted = [
        _clean_name(value)
        for value in re.findall(r'[“"「『]([^”"」』]+)[”"」』]', source)
    ]
    names = quoted if quoted else [
        _clean_name(value)
        for value in re.split(r"\s*(?:、|，|,|；|;|和|与|及)\s*", source)
    ]
    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = _norm(name)
        if name and key and key not in seen:
            result.append(name)
            seen.add(key)
    return result


def classify_compat_command(turn: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    text = str(turn.get("userText") or "").strip()
    if not text or not re.search(r"next\s*plan", text, re.I):
        return None
    source = re.sub(r"^\s*next\s*plan\s*", "", text, flags=re.I).strip()
    match = _STATUS_RE.search(source)
    if not match:
        return None

    status_raw = str(match.group("status") or "")
    status = _STATUS_MAP.get(status_raw.casefold()) or _STATUS_MAP.get(status_raw)
    names = _target_names(match.group("targets"))
    if not names or not status:
        return None

    projects_by_name = {_norm(p.get("name")): p for p in state.get("projects", [])}
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in names:
        project = projects_by_name.get(_norm(name))
        if project is None:
            missing.append(name)
        else:
            resolved.append(project)

    if missing:
        return {
            "id": str(uuid.uuid4()),
            "kind": "project_status_target_missing",
            "confidence": 1.0,
            "informational": True,
            "label": "未找到项目：" + "、".join(missing),
            "reason": "显式批量状态指令包含无法精确匹配的项目；为避免部分写入，整批未执行",
            "action": None,
        }

    changed = [p for p in resolved if str(p.get("status") or "") != status]
    if not changed:
        return {
            "id": str(uuid.uuid4()),
            "kind": "project_status_already_applied",
            "confidence": 1.0,
            "informational": True,
            "label": f"{len(resolved)} 个项目状态已是 {status}",
            "reason": "显式项目状态指令与 canonical state 已一致",
            "action": None,
        }

    return {
        "id": str(uuid.uuid4()),
        "kind": "batch_project_status" if len(resolved) > 1 else "direct_project_status",
        "confidence": 0.99,
        "label": f"更新 {len(changed)} 个项目状态 → {status}",
        "reason": "检测到明确的 NextPlan 项目状态设置指令；全部目标已精确匹配",
        "action": {
            "action": "batch_update_project_status",
            "updates": [
                {"project_id": p["id"], "status": status}
                for p in resolved
            ],
            "source_command": text[:1000],
            "capture_source": "explicit_nextplan_command",
        },
    }
