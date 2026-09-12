from __future__ import annotations

import re
from typing import Any

from . import cloud_classifier as legacy
from . import cloud_classifier_v3 as v3


def _clean_title(text: str, fallback: str) -> str:
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"^(next\s*plan\s*[:：]?\s*)", "", text, flags=re.I)
    text = re.sub(r"^(帮我|请|麻烦)?\s*(记录|记一下|记下来|保存|添加|加入|写入|存一下)\s*", "", text, flags=re.I)
    text = re.sub(r"(为|成|作为)?\s*(一条)?\s*(笔记|note|资源|resource)\s*", "", text, flags=re.I)
    text = text.strip(" ：:，,。.!！")
    if not text:
        return fallback
    return text[:42] + ("…" if len(text) > 42 else "")


def _explicit_note_candidate(text: str, state: dict[str, Any]) -> dict[str, Any] | None:
    wants_note = bool(re.search(r"(记下来|记个笔记|记一条笔记|保存为笔记|作为笔记|加入笔记|添加笔记|save\s+(?:this\s+)?(?:as\s+)?note|note\s+this)", text, re.I))
    if not wants_note:
        return None
    if re.search(r"[?？]\s*$", text):
        return None
    body = text.strip()
    project = legacy.exact_project_mention(text, state)
    title_match = re.search(r"(?:标题|title)\s*[:：]\s*([^\n,，。]+)", text, re.I)
    title = title_match.group(1).strip() if title_match else _clean_title(text, "对话笔记")
    action: dict[str, Any] = {
        "action": "add_note",
        "title": title,
        "body": body,
        "category": project.get("category") if project else "Note",
    }
    if project:
        action["project_id"] = project.get("id")
    return {
        "id": legacy._id(),
        "kind": "note",
        "confidence": 0.98,
        "label": f"保存笔记：{title}",
        "reason": "检测到明确的保存笔记意图",
        "action": action,
    }


def _explicit_resource_candidate(text: str, state: dict[str, Any]) -> dict[str, Any] | None:
    wants_resource = bool(re.search(r"(保存为资源|作为资源|加入资源|添加资源|资源索引|save\s+(?:this\s+)?(?:as\s+)?resource|add\s+(?:this\s+)?resource)", text, re.I))
    if not wants_resource:
        return None
    if re.search(r"[?？]\s*$", text):
        return None
    match = re.search(r"https?://[^\s<>\]\)）]+", text, re.I)
    if not match:
        # The cloud layer intentionally refuses to invent a resource location.
        return None
    location = match.group(0).rstrip(".,，。")
    project = legacy.exact_project_mention(text, state)
    title_match = re.search(r"(?:标题|title)\s*[:：]\s*([^\n,，。]+)", text, re.I)
    title = title_match.group(1).strip() if title_match else _clean_title(text, "资源")
    action: dict[str, Any] = {
        "action": "add_resource",
        "title": title,
        "location": location,
        "description": text.strip(),
        "resource_type": "link",
    }
    if project:
        action["project_id"] = project.get("id")
    return {
        "id": legacy._id(),
        "kind": "resource",
        "confidence": 0.99,
        "label": f"保存资源：{title}",
        "reason": "检测到明确的资源保存意图和可验证链接",
        "action": action,
    }


def classify_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    client = client or {}
    text = str(turn.get("userText") or "").strip()
    if not text:
        return None
    resource = _explicit_resource_candidate(text, state)
    if resource:
        return resource
    note = _explicit_note_candidate(text, state)
    if note:
        return note
    return v3.classify_turn(turn, state, client)
