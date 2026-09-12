from __future__ import annotations

import re
from typing import Any

from . import cloud_classifier as legacy
from . import cloud_classifier_v2 as v2


def _calendar_or_deadline_candidate(text: str, state: dict[str, Any], client: dict[str, Any]) -> dict[str, Any] | None:
    wants_record = bool(re.search(r"next\s*plan|日历|calendar|记录|记一下|加入|添加|写入", text, re.I))
    if not wants_record:
        return None
    d = legacy.parse_date(text, client)
    if not d:
        return None
    parsed_time = legacy.parse_time(text)
    time_str = parsed_time[0] if parsed_time else ""
    tz = str(client.get("timezone") or "").strip()
    project = legacy.exact_project_mention(text, state)

    # Deadline is a due boundary, not a scheduled calendar event.
    if re.search(r"deadline|截止|到期|due\s+date", text, re.I):
        title = "Deadline"
        if project:
            title = f"{project.get('name')} Deadline"
        action: dict[str, Any] = {
            "action": "set_deadline",
            "title": title,
            "date": d.date().isoformat(),
        }
        if project:
            action["project_id"] = project.get("id")
        if time_str:
            action["time"] = time_str
        if tz:
            action["timezone"] = tz
        return {
            "id": legacy._id(),
            "kind": "deadline",
            "confidence": 0.99 if time_str else 0.97,
            "label": f"记录截止日期：{title} · {d.date().isoformat()}" + (f" {time_str}" if time_str else ""),
            "reason": "检测到明确截止日期和 NextPlan 记录意图",
            "action": action,
        }

    kind = None
    title = None
    category = "其他"
    if re.search(r"presentation|汇报|答辩|演示", text, re.I):
        kind, title, category = "presentation", "Presentation", "课程"
    elif re.search(r"meeting|会议|见面|会面", text, re.I):
        kind = "meeting"
        title = "与导师 Meeting" if "导师" in text else "Meeting"
        category = "课程" if "导师" in text else "其他"
    elif re.search(r"appointment|预约|约诊|看牙|看医生", text, re.I):
        kind, title = "appointment", "Appointment"
    elif re.search(r"reminder|提醒", text, re.I):
        kind, title = "reminder", "Reminder"
    elif re.search(r"日历|calendar", text, re.I):
        kind, title = "event", "Calendar Event"
    if not kind:
        return None

    action = {
        "action": "upsert_calendar_event",
        "title": title,
        "date": d.date().isoformat(),
        "kind": kind,
        "category": category,
    }
    if time_str:
        action["time"] = time_str
    if tz:
        action["timezone"] = tz
    if project:
        action["project_id"] = project.get("id")
    when = d.date().isoformat() + (f" {time_str}" if time_str else "")
    return {
        "id": legacy._id(),
        "kind": "calendar_event",
        "confidence": 0.99 if time_str else 0.96,
        "label": f"记录日历：{title} · {when}",
        "reason": f"检测到明确的 {kind} 日期/时间和日历记录意图",
        "action": action,
    }


def classify_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    client = client or {}
    text = str(turn.get("userText") or "").strip()
    if not text or re.search(r"[?？]\s*$", text):
        return None
    calendar = _calendar_or_deadline_candidate(text, state, client)
    if calendar:
        return calendar
    return v2.classify_turn(turn, state, client)
