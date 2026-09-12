from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


AREA_DEFS = [
    ("行政", "Life & Admin", re.compile(r"life\s*(?:&|and)\s*admin|life\s*admin|生活\s*(?:与|和)?\s*行政|行政\s*(?:与|和)?\s*生活", re.I)),
    ("科研", "Research", re.compile(r"\bresearch\b|科研", re.I)),
    ("PhD", "PhD Application", re.compile(r"phd\s*application|phd\s*申请|博士\s*申请", re.I)),
    ("学校", "School", re.compile(r"\bschool\b|学校", re.I)),
    ("课程", "Coursework", re.compile(r"\bcoursework\b|课程", re.I)),
]

STATUS_WORDS = [
    ("blocked", re.compile(r"blocked|阻塞|被阻塞|暂停", re.I)),
    ("waiting", re.compile(r"waiting|等待|待定", re.I)),
    ("completed", re.compile(r"completed_for|completed|\bdone\b|已完成|完成$", re.I)),
    ("active", re.compile(r"started\s*[:=]?\s*true|active|进行中|正在进行|正在执行|已开始", re.I)),
    ("planned", re.compile(r"started\s*[:=]?\s*false|尚未开始|未开始|not\s+started|planned|计划中|待开始", re.I)),
]

CN_NUM = {"零":0,"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,"十一":11,"十二":12}
WEEKDAY = {"一":0,"二":1,"三":2,"四":3,"五":4,"六":5,"日":6,"天":6}


def _id() -> str:
    return str(uuid.uuid4())


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def compact(text: Any) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", normalize(text))


def clean_name(value: Any) -> str:
    s = str(value or "").strip()
    s = re.sub(r'^[\s"\'“”‘’「」『』【】]+|[\s"\'“”‘’「」『』【】]+$', "", s)
    s = re.sub(r"^项目\s*", "", s, flags=re.I)
    s = re.sub(r"\s*项目$", "", s, flags=re.I)
    return s.strip()


def find_project_exact(name: str, state: dict[str, Any]) -> dict[str, Any] | None:
    target = normalize(clean_name(name))
    if not target:
        return None
    for p in state.get("projects", []):
        if normalize(p.get("name")) == target or normalize(p.get("id")) == target:
            return p
    return None


def exact_project_mention(text: str, state: dict[str, Any]) -> dict[str, Any] | None:
    ctext = compact(text)
    best = None
    for p in state.get("projects", []):
        pn = compact(p.get("name"))
        pid = compact(p.get("id"))
        hit = (pn and pn in ctext) or (pid and len(pid) >= 4 and pid in ctext)
        if hit:
            score = max(len(pn), len(pid))
            if best is None or score > best[0]:
                best = (score, p)
    return best[1] if best else None


def exact_task_mention(text: str, state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    ctext = compact(text)
    best = None
    for p in state.get("projects", []):
        for m in p.get("milestones", []):
            mn = compact(m.get("name"))
            mid = compact(m.get("id"))
            hit = (mn and mn in ctext) or (mid and len(mid) >= 2 and mid in ctext)
            if hit:
                score = max(len(mn), len(mid))
                if best is None or score > best[0]:
                    best = (score, p, m)
    return (best[1], best[2]) if best else None


def infer_category(name: str) -> str:
    n = normalize(name)
    if re.search(r"phd|博士|套磁|导师", n, re.I):
        return "PhD"
    if re.search(r"论文|研究|实验|pcc|research", n, re.I):
        return "科研"
    if re.search(r"课程|作业|presentation|proposal|学习", n, re.I):
        return "课程"
    if re.search(r"签证|coe|usyd|学校|入学", n, re.I):
        return "学校"
    if re.search(r"实习|工作|求职|简历|career|job", n, re.I):
        return "职业"
    return "其他"


def target_area(text: str) -> tuple[str, str] | None:
    for category, label, rx in AREA_DEFS:
        if rx.search(text):
            return category, label
    return None


def extract_new_project(text: str) -> str:
    patterns = [
        r"(?:给|向|在)?\s*NextPlan\s*(?:写入|加入|添加|新增|新建|创建)?\s*(?:一个)?\s*(?:新)?项目\s*[：:]\s*([^，。\n]+)",
        r"(?:给|向|在)?\s*NextPlan\s*(?:写入|加入|添加|新增|新建|创建)\s*(?:一个)?\s*(?:新)?项目\s+([^，。\n]+)",
        r"(?:新增|新建|创建|添加)\s*(?:一个)?\s*(?:新)?项目\s*[：:]?\s*([^，。\n]+?)\s*(?:到|进|加入|写入)\s*NextPlan",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return clean_name(m.group(1))[:90]
    return ""


def extract_rename(text: str) -> tuple[str, str] | None:
    pats = [
        r"(?:把|将)\s*(?:NextPlan\s*系统中\s*)?(?:名称(?:为|是)|名为)\s*([^，。；;\n]+?)\s*的\s*项目\s*(?:改成|改为|改名为|更名为|重命名为)\s*([^，。；;\n]+)",
        r"(?:把|将)\s*(?:NextPlan\s*系统中\s*)?项目\s*([^，。；;\n]+?)\s*(?:改成|改为|改名为|更名为|重命名为)\s*([^，。；;\n]+)",
        r"(?:把|将)\s*(?:NextPlan\s*系统中\s*)?([^，。；;\n]+?)\s*项目\s*(?:改成|改为|改名为|更名为|重命名为)\s*([^，。；;\n]+)",
    ]
    for pat in pats:
        m = re.search(pat, text, re.I)
        if m:
            a, b = clean_name(m.group(1)), clean_name(m.group(2))
            if a and b:
                return a, b[:90]
    return None


def extract_current_step(text: str) -> str:
    pats = [
        r"(?:现在|目前|当前)(?:是)?\s*(?:正在|在)?\s*(?:做|进行|处理)\s*[“\"「『]?([^”\"」』，。；;\n]+?)[”\"」』]?(?:这一步|这项任务|这一项|阶段)?(?=[，。；;\n]|下一步|$)",
        r"(?:当前进度|当前步骤|现在进度|目前进度)\s*(?:是|为|[:：])\s*[“\"「『]?([^”\"」』，。；;\n]+)[”\"」』]?",
    ]
    for pat in pats:
        m = re.search(pat, text, re.I)
        if m:
            return clean_name(re.sub(r"(?:这一步|这项任务|这一项|阶段)$", "", m.group(1), flags=re.I))[:120]
    return ""


def extract_next_action(text: str) -> str:
    pats = [
        r"(?:下一步|next\s*step)\s*(?:是|为|[:：])\s*[“\"「『]?([^”\"」』\n。；;]+)[”\"」』]?",
        r"(?:next[_\s-]*action|下一步动作)\s*(?:是|为|[:：])\s*[“\"「『]?([^”\"」』\n。；;]+)[”\"」』]?",
    ]
    for pat in pats:
        m = re.search(pat, text, re.I)
        if m:
            return clean_name(m.group(1))[:220]
    return ""


def status_from_line(line: str) -> str:
    for status, rx in STATUS_WORDS:
        if rx.search(line):
            return status
    return ""


def state_sync_candidate(text: str, assistant: str, title: str, state: dict[str, Any]) -> dict[str, Any] | None:
    if not (re.search(r"next\s*plan", text, re.I) and re.search(r"更新|同步|刷新|写入|记录|调整", text) and re.search(r"状态|进度|当前|项目|里|中", text)):
        return None
    source = f"{text}\n{assistant}"
    project = exact_project_mention(source, state)
    if not project:
        return None

    action: dict[str, Any] = {"action": "update_project_snapshot", "project_id": project["id"]}
    changes = 0
    nxt = extract_next_action(assistant or text)
    if nxt and normalize(nxt) != normalize(project.get("next_action")):
        action["next_action"] = nxt
        changes += 1

    statuses: dict[str, str] = {}
    lines = [x.strip() for x in (assistant or text).splitlines() if x.strip()]
    for m in project.get("milestones", []):
        names = [normalize(m.get("name")), normalize(m.get("id"))]
        for line in lines:
            ln = normalize(line)
            if not any(n and n in ln for n in names):
                continue
            st = status_from_line(line)
            if st and st != m.get("status"):
                statuses[str(m.get("id"))] = st
                break
    if statuses:
        action["milestone_statuses"] = statuses
        changes += len(statuses)

    if not changes:
        return {
            "id": _id(), "kind": "state_sync_noop", "confidence": 0.97,
            "label": f"状态已是最新：{project.get('name')}", "reason": "没有检测到不同于当前状态的明确变更",
            "action": None, "informational": True,
        }
    return {
        "id": _id(), "kind": "state_sync", "confidence": 0.97,
        "label": f"更新项目状态：{project.get('name')}", "reason": f"识别到 {changes} 项明确状态变化",
        "action": action,
    }


def local_now(client: dict[str, Any]) -> datetime:
    now_raw = str(client.get("now") or "").strip()
    tz_name = str(client.get("timezone") or "").strip()
    try:
        z = ZoneInfo(tz_name) if tz_name else timezone.utc
    except Exception:
        z = timezone.utc
    if now_raw:
        try:
            dt = datetime.fromisoformat(now_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(z)
        except Exception:
            pass
    return datetime.now(timezone.utc).astimezone(z)


def parse_date(text: str, client: dict[str, Any]) -> datetime | None:
    now = local_now(client)
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=now.tzinfo)
        except ValueError:
            return None
    m = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", text)
    if m:
        y = now.year
        try:
            d = datetime(y, int(m.group(1)), int(m.group(2)), tzinfo=now.tzinfo)
            if d.date() < now.date() - timedelta(days=1):
                d = d.replace(year=y + 1)
            return d
        except ValueError:
            return None
    if "今天" in text:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "明天" in text:
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if "后天" in text:
        return (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.search(r"(下周|本周|这周)?\s*(?:周|星期)([一二三四五六日天])", text)
    if m:
        prefix = m.group(1) or ""
        wd = WEEKDAY[m.group(2)]
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        if prefix == "下周":
            return monday + timedelta(days=7 + wd)
        if prefix in {"本周", "这周"}:
            return monday + timedelta(days=wd)
        candidate = monday + timedelta(days=wd)
        if candidate.date() < now.date():
            candidate += timedelta(days=7)
        return candidate
    return None


def _cn_hour(raw: str) -> int | None:
    raw = raw.strip()
    if raw.isdigit():
        n = int(raw)
        return n if 0 <= n <= 23 else None
    return CN_NUM.get(raw)


def parse_time(text: str) -> tuple[str, str] | None:
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*(am|pm)?\b", text, re.I)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        ap = (m.group(3) or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return f"{h:02d}:{minute:02d}", m.group(0)
    m = re.search(r"(上午|早上|中午|下午|晚上|傍晚)?\s*([零一二两三四五六七八九十]{1,3}|\d{1,2})点(半|([0-5]?\d)分?)?", text)
    if not m:
        return None
    period, rawh, half, mins = m.group(1) or "", m.group(2), m.group(3), m.group(4)
    h = _cn_hour(rawh)
    if h is None:
        return None
    minute = 30 if half == "半" else int(mins or 0)
    if period in {"下午", "晚上", "傍晚"} and h < 12:
        h += 12
    elif period == "中午" and 1 <= h < 11:
        h += 12
    elif period in {"上午", "早上"} and h == 12:
        h = 0
    return f"{h:02d}:{minute:02d}", m.group(0)


def calendar_candidate(text: str, state: dict[str, Any], client: dict[str, Any]) -> dict[str, Any] | None:
    wants_record = bool(re.search(r"next\s*plan|日历|calendar|记录|记一下|加入|添加", text, re.I))
    calendarish = bool(re.search(r"meeting|会议|约会|appointment|presentation|截止|deadline|汇报|见面", text, re.I))
    if not (wants_record and calendarish):
        return None
    d = parse_date(text, client)
    if not d:
        return None
    t = parse_time(text)
    time_str = t[0] if t else ""
    if re.search(r"导师", text) and re.search(r"meeting|会议|见面", text, re.I):
        title = "与导师 Meeting"
        category = "课程"
    elif re.search(r"presentation|汇报", text, re.I):
        title = "Presentation"
        category = "课程"
    elif re.search(r"deadline|截止", text, re.I):
        title = "Deadline"
        category = "其他"
    else:
        title = "Meeting"
        category = "其他"
    ctext = compact(text)
    project = None
    best_len = 0
    for candidate in state.get("projects", []):
        pname = compact(candidate.get("name"))
        if pname and pname in ctext and len(pname) > best_len:
            project = candidate
            best_len = len(pname)
    action = {"action": "upsert_calendar_event", "title": title, "date": d.date().isoformat(), "category": category, "kind": "event"}
    if time_str:
        action["time"] = time_str
    tz = str(client.get("timezone") or "").strip()
    if tz:
        action["timezone"] = tz
    if project:
        action["project_id"] = project.get("id")
    when = d.date().isoformat() + (f" {time_str}" if time_str else "")
    return {"id": _id(), "kind": "calendar_event", "confidence": 0.98 if time_str else 0.95, "label": f"记录日历：{title} · {when}", "reason": "检测到明确的日期/时间和日历记录意图", "action": action}


def classify_turn(turn: dict[str, Any], state: dict[str, Any], client: dict[str, Any] | None = None) -> dict[str, Any] | None:
    client = client or {}
    text = str(turn.get("userText") or "").strip()
    assistant = str(turn.get("assistantText") or "").strip()
    title = str(turn.get("title") or "").strip()
    if not text or re.search(r"[?？]\s*$", text):
        return None

    cal = calendar_candidate(text, state, client)
    if cal:
        return cal

    rename = extract_rename(text)
    current = extract_current_step(text)
    nxt = extract_next_action(text)
    if rename or current or nxt:
        project = find_project_exact(rename[0], state) if rename else exact_project_mention(text, state)
        if rename and not project:
            target = find_project_exact(rename[1], state)
            if target:
                return {"id": _id(), "kind": "project_rename_already_applied", "confidence": 1.0, "informational": True, "alreadyApplied": True, "label": f"已确认：项目已经是「{target.get('name')}」", "reason": f"重命名 {rename[0]} → {rename[1]} 已经写入 NextPlan", "action": None}
        if project:
            action: dict[str, Any] = {"action": "update_project_snapshot", "project_id": project["id"]}
            count = 0
            if rename and normalize(rename[1]) != normalize(project.get("name")):
                action["name"] = rename[1]
                count += 1
            if current:
                action["current_step"] = current
                action["status"] = "active"
                count += 1
            if nxt and normalize(nxt) != normalize(project.get("next_action")):
                action["next_action"] = nxt
                count += 1
            if count:
                return {"id": _id(), "kind": "direct_project_edit", "confidence": 0.99, "label": f"更新项目：{project.get('name')}" + (f" → {action['name']}" if action.get("name") else ""), "reason": f"识别到 {count} 项明确项目变更", "action": action}
            return {"id": _id(), "kind": "project_edit_already_applied", "confidence": 1.0, "informational": True, "label": f"已确认：{project.get('name')} 已经是目标状态", "reason": "这条项目更新已经写入 NextPlan", "action": None}

    area = target_area(text)
    if area and re.search(r"放入|放到|放进|归入|归到|归类到|移动到|移到|分到|划到", text, re.I):
        project = exact_project_mention(text, state)
        if project:
            return {"id": _id(), "kind": "move_project_area", "confidence": 0.99, "label": f"移动项目：{project.get('name')} → {area[1]}", "reason": "检测到明确的项目区域调整", "action": {"action": "update_project_snapshot", "project_id": project["id"], "category": area[0]}}

    if re.search(r"next\s*plan", text, re.I):
        new_name = extract_new_project(text)
        if new_name:
            existing = find_project_exact(new_name, state)
            if existing:
                return {"id": _id(), "kind": "project_exists", "confidence": 1.0, "informational": True, "label": f"项目已存在：{existing.get('name')}", "reason": "NextPlan 中已有同名项目", "action": None}
            return {"id": _id(), "kind": "create_project", "confidence": 0.99, "label": f"新增项目：{new_name}", "reason": "检测到明确的 NextPlan 新项目指令", "action": {"action": "create_project", "name": new_name, "category": infer_category(new_name), "priority": 2, "next_action": ""}}

    if re.search(r"删除|移除|去掉|删掉", text):
        task_hit = exact_task_mention(text, state)
        project = exact_project_mention(text, state)
        if re.search(r"任务|task", text, re.I) and task_hit:
            p, m = task_hit
            return {"id": _id(), "kind": "delete_task", "confidence": 0.99, "destructive": True, "requiresConfirmation": True, "label": f"删除任务：{m.get('name')}", "reason": "破坏性操作必须确认", "action": {"action": "delete_task", "project_id": p["id"], "task_id": m["id"]}}
        if project:
            return {"id": _id(), "kind": "delete_project", "confidence": 0.99, "destructive": True, "requiresConfirmation": True, "label": f"删除项目：{project.get('name')}", "reason": "破坏性操作必须确认", "action": {"action": "delete_project", "project_id": project["id"]}}

    project = exact_project_mention(text, state)
    if project:
        m = re.search(r"(?:新增|添加|新建|加)(?:一个)?(?:任务|task)\s*[：:]?\s*[“\"「『]?([^”\"」』，。\n]+)", text, re.I)
        if m:
            name = clean_name(m.group(1))
            if name:
                for old in project.get("milestones", []):
                    if normalize(old.get("name")) == normalize(name):
                        return {"id": _id(), "kind": "task_exists", "confidence": 1.0, "informational": True, "label": f"任务已存在：{old.get('name')}", "reason": "同名任务已经存在", "action": None}
                return {"id": _id(), "kind": "create_task", "confidence": 0.98, "label": f"新增任务：{name}", "reason": "检测到明确的新任务指令", "action": {"action": "create_task", "project_id": project["id"], "name": name}}

    task_hit = exact_task_mention(text, state)
    if task_hit and re.search(r"完成了|已完成|标记为完成|设为完成|完成$", text):
        p, m = task_hit
        if m.get("status") == "completed":
            return {"id": _id(), "kind": "task_already_completed", "confidence": 1.0, "informational": True, "label": f"已完成：{m.get('name')}", "reason": "任务已经是完成状态", "action": None}
        return {"id": _id(), "kind": "complete_task", "confidence": 0.99, "label": f"完成任务：{m.get('name')}", "reason": "检测到明确完成确认", "action": {"action": "complete_task", "project_id": p["id"], "task_id": m["id"]}}

    sync = state_sync_candidate(text, assistant, title, state)
    if sync:
        return sync
    return None
