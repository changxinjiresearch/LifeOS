from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher
from typing import Any

_SPECULATIVE = ("可能", "也许", "或许", "以后有机会", "有时候想", "随便想想", "might", "maybe", "someday")
_COMMITMENT = ("我要", "我准备", "我打算", "我现在开始", "正式开始", "接下来要", "需要开始", "I'm going to", "I am going to", "I plan to")

_DOMAIN_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"找(?:工作|实习)|求职"), "找工作", "职业"),
    (re.compile(r"申请(?:博士|phd)", re.I), "PhD 申请", "PhD"),
    (re.compile(r"申请(?:研究生|硕士|master)", re.I), "研究生申请", "学校"),
    (re.compile(r"(?:毕业论文|thesis|dissertation)", re.I), "毕业论文", "科研"),
    (re.compile(r"搬(?:去|到|家).*?(?:悉尼|Sydney)", re.I), "搬去悉尼", "行政"),
]


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text).casefold()


def _similarity(a: str, b: str) -> float:
    ca, cb = _compact(a), _compact(b)
    if not ca or not cb:
        return 0.0
    if ca in cb or cb in ca:
        return 0.94
    return SequenceMatcher(None, ca, cb).ratio()


def _clean_step(raw: str) -> str:
    text = raw.strip(" ，。,.；;：:")
    text = re.sub(r"^(?:第一步|第二步|第三步|先|然后|再|之后|接着|最后)\s*", "", text)
    text = re.sub(r"^(?:我(?:要|需要|应该|得)|开始|把)\s*", "", text)
    text = re.sub(r"(?:做好|写好|完成|搞定)$", "", text)
    replacements = {
        "简历": "做简历",
        "申请职位": "申请职位",
        "投职位": "申请职位",
        "投岗位": "申请职位",
        "投简历": "申请职位",
        "准备一份coverletter": "准备 Cover Letter",
        "准备coverletter": "准备 Cover Letter",
    }
    key = _compact(text)
    if key in replacements:
        return replacements[key]
    if "简历" in text and len(text) <= 12:
        return "做简历"
    return text[:80].strip()


def _extract_steps(text: str) -> list[str]:
    normalized = text.replace("；", "，").replace(";", ",")
    pieces = re.split(r"(?:第一步|第二步|第三步|先|然后|之后|接着|再|最后)[：:\s]*", normalized)
    steps: list[str] = []
    for piece in pieces[1:]:
        piece = re.split(r"[，,。.]", piece, maxsplit=1)[0]
        step = _clean_step(piece)
        if step and len(step) >= 2 and step not in steps:
            steps.append(step)
    return steps[:8]


def _infer_project(text: str) -> tuple[str, str] | None:
    for pattern, name, category in _DOMAIN_PATTERNS:
        if pattern.search(text):
            return name, category
    # Conservative generic fallback only for explicit "项目" declarations.
    m = re.search(r"(?:项目叫|新项目(?:是|叫)?|建立项目)[：:\s]*([^，。,.]{2,30})", text)
    if m:
        return m.group(1).strip(), "其他"
    return None


def _match_project(state: dict[str, Any], name: str, text: str = "") -> tuple[dict[str, Any] | None, float]:
    best: tuple[dict[str, Any] | None, float] = (None, 0.0)
    for project in state.get("projects", []):
        score = _similarity(name, str(project.get("name") or ""))
        pname = str(project.get("name") or "")
        if pname and pname in text:
            score = max(score, 0.99)
        if score > best[1]:
            best = (project, score)
    return best


def _provenance(text: str, matched: str = "") -> dict[str, Any]:
    return {
        "conversationCapture": True,
        "sourceAuthority": "user_assertion",
        "assistantUsedAsEvidence": False,
        "evidenceText": text[:500],
        **({"matchedSubject": matched} if matched else {}),
    }


def _milestone_growth(text: str, state: dict[str, Any]) -> dict[str, Any] | None:
    growth_markers = ("还要", "还需要", "还应该", "加一个", "增加", "新增", "也要", "也需要")
    if not any(x in text for x in growth_markers):
        return None

    candidates: list[tuple[dict[str, Any], float]] = []
    for project in state.get("projects", []):
        name = str(project.get("name") or "")
        score = 0.0
        if name and name in text:
            score = 1.0
        elif any(k in text.casefold() for k in ("职位", "申请", "简历", "cover letter", "求职", "工作")) and any(k in name.casefold() for k in ("工作", "实习", "求职")):
            score = 0.90
        if score:
            candidates.append((project, score))
    candidates.sort(key=lambda x: x[1], reverse=True)
    if not candidates:
        return None
    if len(candidates) > 1 and abs(candidates[0][1] - candidates[1][1]) < 0.08:
        return None
    project = candidates[0][0]

    marker_pattern = "|".join(map(re.escape, growth_markers))
    m = re.search(rf"(?:{marker_pattern})[：:\s]*(.+)$", text, re.I)
    if not m:
        return None
    raw = re.split(r"[。.;；]", m.group(1), maxsplit=1)[0]
    step = _clean_step(raw)
    if not step:
        return None
    existing = max((_similarity(step, str(x.get("name") or "")) for x in project.get("milestones", [])), default=0.0)
    if existing >= 0.88:
        return {
            "id": f"local-info-{uuid.uuid4().hex[:10]}",
            "kind": "conversation_project_growth",
            "label": f"{step} 已在项目中",
            "confidence": 0.94,
            "informational": True,
            "requiresConfirmation": False,
            "destructive": False,
            "action": None,
            "provenance": _provenance(text, str(project.get("name") or "")),
        }
    return {
        "id": f"local-growth-{uuid.uuid4().hex[:10]}",
        "kind": "conversation_project_growth",
        "label": f"为 {project.get('name')} 增加步骤：{step}",
        "confidence": 0.90,
        "requiresConfirmation": True,
        "destructive": False,
        "action": {"action": "create_task", "project_id": project.get("id"), "name": step, "status": "planned"},
        "provenance": _provenance(text, str(project.get("name") or "")),
    }


def discover_project_change(turn: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    text = str(turn.get("userText") or "").strip()
    if not text or any(token.casefold() in text.casefold() for token in _SPECULATIVE):
        return None

    growth = _milestone_growth(text, state)
    if growth is not None:
        return growth

    if not any(token.casefold() in text.casefold() for token in _COMMITMENT):
        return None
    inferred = _infer_project(text)
    if not inferred:
        return None
    name, category = inferred
    existing, score = _match_project(state, name, text)
    steps = _extract_steps(text)

    if existing and score >= 0.88:
        # A commitment about an existing project is not a duplicate project.
        for step in steps:
            if max((_similarity(step, str(m.get("name") or "")) for m in existing.get("milestones", [])), default=0.0) < 0.86:
                return {
                    "id": f"local-growth-{uuid.uuid4().hex[:10]}",
                    "kind": "conversation_project_growth",
                    "label": f"为 {existing.get('name')} 增加步骤：{step}",
                    "confidence": 0.91,
                    "requiresConfirmation": True,
                    "destructive": False,
                    "action": {"action": "create_task", "project_id": existing.get("id"), "name": step, "status": "planned"},
                    "provenance": _provenance(text, str(existing.get("name") or "")),
                }
        return None

    milestones = []
    for index, step in enumerate(steps):
        milestones.append({"name": step, "status": "active" if index == 0 else "planned"})
    action: dict[str, Any] = {
        "action": "create_project_blueprint",
        "name": name,
        "category": category,
        "milestones": milestones,
        "next_action": milestones[0]["name"] if milestones else "",
    }
    return {
        "id": f"local-project-{uuid.uuid4().hex[:10]}",
        "kind": "conversation_project_discovery",
        "label": f"发现新项目：{name}",
        "confidence": 0.93 if milestones else 0.89,
        "requiresConfirmation": True,
        "destructive": False,
        "action": action,
        "projectDraft": {"name": name, "category": category, "milestones": milestones},
        "provenance": _provenance(text, name),
    }
