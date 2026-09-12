from __future__ import annotations

import re
from typing import Any

from . import cloud_classifier as legacy
from . import cloud_classifier_v4 as v4

_RULE_PATTERNS = [
    ("overdue-deadline", r"逾期|overdue"),
    ("preparation-window", r"准备窗口|准备提醒|preparation"),
    ("stale-active", r"停滞|长期没动|stale"),
    ("waiting-followup", r"等待.*(?:提醒|follow)|waiting.*follow"),
    ("blocked-project", r"阻塞|blocked"),
    ("missing-next-action", r"没有.*下一步|missing.*next"),
    ("weekly-review", r"每周复盘|weekly\s*review"),
]


def _automation_candidate(text: str) -> dict[str, Any] | None:
    if not re.search(r"自动|automation|规则|提醒", text, re.I):
        return None
    rule_id = next((rid for rid, pat in _RULE_PATTERNS if re.search(pat, text, re.I)), None)
    if not rule_id:
        return None
    disable = bool(re.search(r"关闭|禁用|停用|不要|disable|turn\s+off", text, re.I))
    enable = bool(re.search(r"开启|启用|打开|enable|turn\s+on", text, re.I))
    day_match = re.search(r"(\d{1,3})\s*(?:天|days?)", text, re.I)
    action: dict[str, Any] = {"action": "upsert_automation_rule", "rule_id": rule_id}
    if disable or enable:
        action["enabled"] = not disable
    if day_match and rule_id in {"preparation-window", "stale-active", "waiting-followup"}:
        action["threshold_days"] = max(1, min(365, int(day_match.group(1))))
    if len(action) == 2:
        return None
    return {
        "id": legacy._id(),
        "kind": "automation_rule",
        "confidence": 0.97,
        "label": f"更新自动化规则：{rule_id}",
        "reason": "检测到明确的 NextPlan 自动化规则变更",
        "action": action,
    }


def classify_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    client = client or {}
    text = str(turn.get("userText") or "").strip()
    if not text:
        return None
    automation = _automation_candidate(text)
    if automation:
        return automation
    return v4.classify_turn(turn, state, client)
