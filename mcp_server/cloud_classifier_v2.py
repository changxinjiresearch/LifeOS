from __future__ import annotations

import re
from typing import Any

from . import cloud_classifier as legacy


PROJECT_REF_RE = re.compile(
    r"(?:这个|该|那个|当前|目前(?:这个)?)\s*项目|\b(?:this|that|current)\s+project\b|^这个$|^该$|^那个$",
    re.I,
)
TASK_REF_RE = re.compile(
    r"(?:这个|该|那个|当前|目前(?:这个)?)\s*(?:任务|步骤|milestone)|\b(?:this|that|current)\s+(?:task|milestone)\b",
    re.I,
)


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", legacy.normalize(value)))


def _overlap(a: Any, b: Any) -> float:
    aa, bb = _tokens(a), _tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, min(len(aa), len(bb)))


def _recent_project_bonus(project_id: str, state: dict[str, Any]) -> float:
    for idx, event in enumerate((state.get("events") or [])[:20]):
        if str(event.get("project_id", "")) == project_id:
            return max(0.05, 0.22 - idx * 0.012)
    return 0.0


def _is_project_reference(value: str) -> bool:
    cleaned = legacy.clean_name(value)
    return bool(PROJECT_REF_RE.search(cleaned) or cleaned in {"这个", "该", "那个", "当前", "目前"})


def _is_task_reference(value: str) -> bool:
    return bool(TASK_REF_RE.search(str(value or "")))


def _project_score(
    project: dict[str, Any],
    text: str,
    assistant: str,
    title: str,
    state: dict[str, Any],
) -> tuple[float, str]:
    name = str(project.get("name", ""))
    pid = str(project.get("id", ""))
    next_action = str(project.get("next_action", ""))
    ctext, cassistant, ctitle = legacy.compact(text), legacy.compact(assistant), legacy.compact(title)
    cname, cid = legacy.compact(name), legacy.compact(pid)

    if (cname and cname in ctext) or (cid and len(cid) >= 4 and cid in ctext):
        return 1.0, "user_exact"
    if (cname and cname in cassistant) or (cid and len(cid) >= 4 and cid in cassistant):
        return 0.93, "assistant_exact"
    if (cname and cname in ctitle) or (cid and len(cid) >= 4 and cid in ctitle):
        return 0.82, "title_exact"

    hay = f"{name} {next_action}"
    lexical = (
        0.44 * _overlap(text, hay)
        + 0.28 * _overlap(assistant, hay)
        + 0.14 * _overlap(title, name)
    )
    recency = _recent_project_bonus(pid, state)
    score = min(0.84, lexical + recency)
    method = "lexical+recent" if recency else "lexical"
    return score, method


def resolve_project(
    text: str,
    assistant: str,
    title: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for project in state.get("projects", []):
        score, method = _project_score(project, text, assistant, title, state)
        ranked.append((score, method, project))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 0.42:
        return None

    top_score, method, project = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = top_score - second
    auto = method == "user_exact" or (top_score >= 0.86 and margin >= 0.12)
    alternatives = [
        {"entity_id": p.get("id"), "entity_name": p.get("name"), "score": round(score, 3)}
        for score, _method, p in ranked[1:4]
        if score >= 0.30
    ]
    return {
        "entity_type": "project",
        "entity_id": project.get("id"),
        "entity_name": project.get("name"),
        "confidence": round(top_score, 3),
        "method": method,
        "margin": round(margin, 3),
        "requires_confirmation": not auto,
        "alternatives": alternatives,
        "project": project,
    }


def _task_score(
    project: dict[str, Any],
    task: dict[str, Any],
    text: str,
    assistant: str,
    title: str,
    state: dict[str, Any],
) -> tuple[float, str]:
    name = str(task.get("name", ""))
    tid = str(task.get("id", ""))
    ctext, cassistant, ctitle = legacy.compact(text), legacy.compact(assistant), legacy.compact(title)
    cname, cid = legacy.compact(name), legacy.compact(tid)
    if (cname and cname in ctext) or (cid and len(cid) >= 2 and cid in ctext):
        return 1.0, "user_exact"
    if (cname and cname in cassistant) or (cid and len(cid) >= 2 and cid in cassistant):
        return 0.92, "assistant_exact"
    if cname and cname in ctitle:
        return 0.80, "title_exact"

    project_score, _ = _project_score(project, text, assistant, title, state)
    lexical = 0.48 * _overlap(text, name) + 0.30 * _overlap(assistant, name) + 0.12 * _overlap(title, name)
    score = min(0.84, lexical + 0.22 * project_score)
    return score, "task_lexical+project_context"


def resolve_task(
    text: str,
    assistant: str,
    title: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    ranked: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
    for project in state.get("projects", []):
        for task in project.get("milestones", []):
            score, method = _task_score(project, task, text, assistant, title, state)
            ranked.append((score, method, project, task))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 0.44:
        return None

    top_score, method, project, task = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = top_score - second
    auto = method == "user_exact" or (top_score >= 0.86 and margin >= 0.12)
    alternatives = [
        {
            "entity_id": t.get("id"),
            "entity_name": t.get("name"),
            "project_id": p.get("id"),
            "project_name": p.get("name"),
            "score": round(score, 3),
        }
        for score, _method, p, t in ranked[1:4]
        if score >= 0.32
    ]
    return {
        "entity_type": "task",
        "entity_id": task.get("id"),
        "entity_name": task.get("name"),
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "confidence": round(top_score, 3),
        "method": method,
        "margin": round(margin, 3),
        "requires_confirmation": not auto,
        "alternatives": alternatives,
        "project": project,
        "task": task,
    }


def _public_resolution(resolution: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in resolution.items() if k not in {"project", "task"}}


def _candidate(
    *,
    kind: str,
    label: str,
    reason: str,
    action: dict[str, Any],
    resolution: dict[str, Any],
    destructive: bool = False,
) -> dict[str, Any]:
    requires = destructive or bool(resolution.get("requires_confirmation"))
    confidence = float(resolution.get("confidence", 0.0))
    return {
        "id": legacy._id(),
        "kind": kind,
        "confidence": confidence,
        "label": label,
        "reason": reason,
        "action": action,
        "resolution": _public_resolution(resolution),
        "destructive": destructive,
        "requiresConfirmation": requires,
    }


def _find_project_by_id(state: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    return next((p for p in state.get("projects", []) if str(p.get("id")) == str(project_id)), None)


def _augment_exact(candidate: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any] | None:
    if not candidate or not isinstance(candidate.get("action"), dict) or candidate.get("resolution"):
        return candidate
    action = candidate["action"]
    project_id = action.get("project_id")
    task_id = action.get("task_id") or action.get("milestone_id")
    if task_id and project_id:
        project = _find_project_by_id(state, str(project_id))
        task = next((m for m in (project or {}).get("milestones", []) if str(m.get("id")) == str(task_id)), None)
        if project and task:
            candidate["resolution"] = {
                "entity_type": "task",
                "entity_id": task.get("id"),
                "entity_name": task.get("name"),
                "project_id": project.get("id"),
                "project_name": project.get("name"),
                "confidence": 1.0,
                "method": "exact",
                "requires_confirmation": bool(candidate.get("requiresConfirmation")),
                "alternatives": [],
            }
    elif project_id:
        project = _find_project_by_id(state, str(project_id))
        if project:
            candidate["resolution"] = {
                "entity_type": "project",
                "entity_id": project.get("id"),
                "entity_name": project.get("name"),
                "confidence": 1.0,
                "method": "exact",
                "requires_confirmation": bool(candidate.get("requiresConfirmation")),
                "alternatives": [],
            }
    return candidate


def classify_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    client = client or {}
    text = str(turn.get("userText") or "").strip()
    assistant = str(turn.get("assistantText") or "").strip()
    title = str(turn.get("title") or "").strip()
    if not text or re.search(r"[?？]\s*$", text):
        return None

    # Referential project rename: never treat “这个/该/那个” as a literal project name.
    rename = legacy.extract_rename(text)
    if rename and _is_project_reference(rename[0]):
        new_name = rename[1]
        resolution = resolve_project(text, assistant, title, state)
        if not resolution:
            existing_target = legacy.find_project_exact(new_name, state)
            if existing_target:
                return {
                    "id": legacy._id(),
                    "kind": "project_rename_already_applied",
                    "confidence": 1.0,
                    "informational": True,
                    "label": f"已确认：项目已经是「{existing_target.get('name')}」",
                    "reason": "目标名称已存在；没有执行新的重命名",
                    "action": None,
                }
            return {
                "id": legacy._id(),
                "kind": "entity_resolution_needed",
                "confidence": 0.0,
                "informational": True,
                "label": "NextPlan · 需要明确要修改哪个项目",
                "reason": "无法从当前上下文可靠解析“这个项目”",
                "action": None,
            }
        project = resolution["project"]
        if legacy.normalize(project.get("name")) == legacy.normalize(new_name):
            return {
                "id": legacy._id(), "kind": "project_edit_already_applied", "confidence": 1.0,
                "informational": True, "label": f"已确认：{project.get('name')} 已经是目标名称",
                "reason": "无需再次写入", "action": None, "resolution": _public_resolution(resolution),
            }
        conflict = legacy.find_project_exact(new_name, state)
        if conflict and conflict.get("id") != project.get("id"):
            return {
                "id": legacy._id(), "kind": "rename_conflict", "confidence": resolution["confidence"],
                "informational": True, "label": f"NextPlan · 名称冲突：{new_name} 已存在",
                "reason": "为避免覆盖另一项目，本次未执行重命名", "action": None,
                "resolution": _public_resolution(resolution),
            }
        return _candidate(
            kind="contextual_project_rename",
            label=f"重命名项目：{project.get('name')} → {new_name}",
            reason="通过当前对话上下文解析了指代项目" + ("；需要确认" if resolution["requires_confirmation"] else ""),
            action={"action": "update_project_snapshot", "project_id": project["id"], "name": new_name},
            resolution=resolution,
        )

    # Referential current-step / next-action update.
    current = legacy.extract_current_step(text)
    nxt = legacy.extract_next_action(text)
    if (current or nxt) and not legacy.exact_project_mention(text, state) and (PROJECT_REF_RE.search(text) or "项目" in text):
        resolution = resolve_project(text, assistant, title, state)
        if resolution:
            project = resolution["project"]
            action: dict[str, Any] = {"action": "update_project_snapshot", "project_id": project["id"]}
            if current:
                action["current_step"] = current
                action["status"] = "active"
            if nxt:
                action["next_action"] = nxt
            return _candidate(
                kind="contextual_project_edit",
                label=f"更新项目：{project.get('name')}",
                reason="通过上下文解析了当前项目" + ("；需要确认" if resolution["requires_confirmation"] else ""),
                action=action,
                resolution=resolution,
            )

    # Referential area move.
    area = legacy.target_area(text)
    if area and re.search(r"放入|放到|放进|归入|归到|归类到|移动到|移到|分到|划到", text, re.I) and not legacy.exact_project_mention(text, state):
        resolution = resolve_project(text, assistant, title, state)
        if resolution:
            project = resolution["project"]
            return _candidate(
                kind="contextual_move_project_area",
                label=f"移动项目：{project.get('name')} → {area[1]}",
                reason="通过上下文解析了要移动的项目" + ("；需要确认" if resolution["requires_confirmation"] else ""),
                action={"action": "update_project_snapshot", "project_id": project["id"], "category": area[0]},
                resolution=resolution,
            )

    # Referential destructive actions.
    if re.search(r"删除|移除|去掉|删掉", text):
        exact_task = legacy.exact_task_mention(text, state)
        exact_project = legacy.exact_project_mention(text, state)
        if not exact_task and (TASK_REF_RE.search(text) or re.search(r"任务|task|milestone", text, re.I)):
            resolution = resolve_task(text, assistant, title, state)
            if resolution:
                return _candidate(
                    kind="contextual_delete_task",
                    label=f"删除任务：{resolution['entity_name']}",
                    reason="删除属于破坏性操作，必须确认",
                    action={"action": "delete_task", "project_id": resolution["project_id"], "task_id": resolution["entity_id"]},
                    resolution=resolution,
                    destructive=True,
                )
        if not exact_project and (PROJECT_REF_RE.search(text) or "项目" in text):
            resolution = resolve_project(text, assistant, title, state)
            if resolution:
                project = resolution["project"]
                return _candidate(
                    kind="contextual_delete_project",
                    label=f"删除项目：{project.get('name')}",
                    reason="删除属于破坏性操作，必须确认",
                    action={"action": "delete_project", "project_id": project["id"]},
                    resolution=resolution,
                    destructive=True,
                )

    # Referential task creation inside the current project.
    task_match = re.search(r"(?:新增|添加|新建|加)(?:一个)?(?:任务|task)\s*[：:]?\s*[“\"「『]?([^”\"」』，。\n]+)", text, re.I)
    if task_match and not legacy.exact_project_mention(text, state):
        resolution = resolve_project(text, assistant, title, state)
        name = legacy.clean_name(task_match.group(1))
        if resolution and name:
            project = resolution["project"]
            for old in project.get("milestones", []):
                if legacy.normalize(old.get("name")) == legacy.normalize(name):
                    return {
                        "id": legacy._id(), "kind": "task_exists", "confidence": 1.0, "informational": True,
                        "label": f"任务已存在：{old.get('name')}", "reason": "同名任务已经存在", "action": None,
                        "resolution": _public_resolution(resolution),
                    }
            return _candidate(
                kind="contextual_create_task",
                label=f"新增任务：{name} · {project.get('name')}",
                reason="通过上下文解析了任务所属项目" + ("；需要确认" if resolution["requires_confirmation"] else ""),
                action={"action": "create_task", "project_id": project["id"], "name": name},
                resolution=resolution,
            )

    # Referential task completion.
    if re.search(r"完成了|已完成|标记为完成|设为完成|完成$", text) and not legacy.exact_task_mention(text, state) and (_is_task_reference(text) or re.search(r"任务|步骤", text)):
        resolution = resolve_task(text, assistant, title, state)
        if resolution:
            task = resolution["task"]
            if task.get("status") == "completed":
                return {
                    "id": legacy._id(), "kind": "task_already_completed", "confidence": 1.0,
                    "informational": True, "label": f"已完成：{task.get('name')}", "reason": "任务已经是完成状态",
                    "action": None, "resolution": _public_resolution(resolution),
                }
            return _candidate(
                kind="contextual_complete_task",
                label=f"完成任务：{task.get('name')}",
                reason="通过上下文解析了任务" + ("；需要确认" if resolution["requires_confirmation"] else ""),
                action={"action": "complete_task", "project_id": resolution["project_id"], "task_id": resolution["entity_id"]},
                resolution=resolution,
            )

    candidate = legacy.classify_turn(turn, state, client)
    return _augment_exact(candidate, state)
