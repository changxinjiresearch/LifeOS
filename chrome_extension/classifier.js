function normalize(text) {
  return String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function compact(text) {
  return normalize(text).replace(/[^a-z0-9\u3400-\u9fff]+/g, "");
}

function overlap(a, b) {
  const A = new Set(normalize(a).split(/[^a-z0-9\u3400-\u9fff]+/).filter(Boolean));
  const B = new Set(normalize(b).split(/[^a-z0-9\u3400-\u9fff]+/).filter(Boolean));
  if (!A.size || !B.size) return 0;
  let hit = 0;
  for (const x of A) if (B.has(x)) hit++;
  return hit / Math.max(1, Math.min(A.size, B.size));
}

function bestProject(text, title, state) {
  let best = null;
  for (const p of state.projects || []) {
    const score = 0.75 * overlap(text, `${p.name} ${p.next_action || ""}`) + 0.25 * overlap(title, p.name);
    if (!best || score > best.score) best = {project: p, score};
  }
  return best;
}

function bestMilestone(text, title, state) {
  let best = null;
  for (const p of state.projects || []) {
    for (const m of p.milestones || []) {
      if (["completed", "done"].includes(m.status)) continue;
      let score = 0.7 * overlap(text, m.name) + 0.2 * overlap(text, p.name) + 0.1 * overlap(title, p.name);
      if (normalize(text).includes(normalize(m.name))) score = 1;
      if (!best || score > best.score) best = {project: p, milestone: m, score};
    }
  }
  return best;
}

function exactProjectMention(text, state) {
  const ctext = compact(text);
  let best = null;
  for (const p of state.projects || []) {
    const name = compact(p.name);
    const id = compact(p.id);
    const hit = (name && ctext.includes(name)) || (id && id.length >= 4 && ctext.includes(id));
    if (!hit) continue;
    const score = Math.max(name.length, id.length);
    if (!best || score > best.score) best = {project: p, score};
  }
  return best?.project || null;
}

function deletionTarget(text, title, state) {
  const ctext = compact(text);
  let bestProjectHit = null;
  let bestTaskHit = null;

  for (const p of state.projects || []) {
    const pname = compact(p.name);
    const pid = compact(p.id);
    let pscore = 0.65 * overlap(text, p.name) + 0.15 * overlap(title, p.name);
    if ((pname && ctext.includes(pname)) || (pid && ctext.includes(pid))) pscore = 1;
    if (!bestProjectHit || pscore > bestProjectHit.score) bestProjectHit = {project: p, score: pscore};

    for (const m of p.milestones || []) {
      const mname = compact(m.name);
      const mid = compact(m.id);
      let mscore = 0.7 * overlap(text, m.name) + 0.2 * overlap(text, p.name) + 0.1 * overlap(title, p.name);
      if ((mname && ctext.includes(mname)) || (mid && ctext.includes(mid))) mscore = 1;
      if (!bestTaskHit || mscore > bestTaskHit.score) bestTaskHit = {project: p, milestone: m, score: mscore};
    }
  }

  const taskHint = /(任务|task)/i.test(text);
  const projectHint = /(项目|project)/i.test(text);

  if (taskHint && bestTaskHit?.score >= 0.55) return {kind: "task", ...bestTaskHit};
  if (projectHint && bestProjectHit?.score >= 0.55) return {kind: "project", ...bestProjectHit};
  if (bestProjectHit?.score >= 0.9 && (!bestTaskHit || bestTaskHit.score < 0.9)) return {kind: "project", ...bestProjectHit};
  if (bestTaskHit?.score >= 0.9) return {kind: "task", ...bestTaskHit};
  return null;
}

function extractNewProjectName(text) {
  const patterns = [
    /(?:给|向|在)?\s*NextPlan\s*(?:写入|加入|添加|新增|新建|创建)?\s*(?:一个)?\s*(?:新)?项目\s*[：:]\s*([^，。\n]+)/i,
    /(?:给|向|在)?\s*NextPlan\s*(?:写入|加入|添加|新增|新建|创建)\s*(?:一个)?\s*(?:新)?项目\s+([^，。\n]+)/i,
    /(?:新增|新建|创建|添加)\s*(?:一个)?\s*(?:新)?项目\s*[：:]?\s*([^，。\n]+?)\s*(?:到|进|加入|写入)\s*NextPlan/i,
    /(?:把|将)\s*([^，。\n]+?)\s*(?:作为|设为)?\s*(?:一个)?\s*(?:新)?项目\s*(?:加到|加入|写入|放到)\s*NextPlan/i
  ];
  for (const re of patterns) {
    const m = text.match(re);
    if (m?.[1]) return m[1].trim().replace(/["'“”‘’]/g, "").slice(0, 90);
  }
  return "";
}

function inferCategory(name) {
  const n = normalize(name);
  if (/(phd|博士|套磁|导师)/i.test(n)) return "PhD";
  if (/(论文|研究|实验|pcc|research)/i.test(n)) return "科研";
  if (/(课程|作业|presentation|proposal|学习)/i.test(n)) return "课程";
  if (/(签证|coe|usyd|学校|入学)/i.test(n)) return "学校";
  if (/(实习|工作|求职|简历|career|job)/i.test(n)) return "职业";
  return "其他";
}

const AREA_DEFS = [
  {category: "行政", label: "Life & Admin", re: /life\s*(?:&|and)\s*admin|life\s*admin|生活\s*(?:与|和)?\s*行政|行政\s*(?:与|和)?\s*生活/i},
  {category: "科研", label: "Research", re: /\bresearch\b|科研/i},
  {category: "PhD", label: "PhD Application", re: /phd\s*application|phd\s*申请|博士\s*申请/i},
  {category: "学校", label: "School", re: /\bschool\b|学校/i},
  {category: "课程", label: "Coursework", re: /\bcoursework\b|课程/i}
];

function targetArea(text) {
  return AREA_DEFS.find(x => x.re.test(text)) || null;
}

function extractMoveProjectName(text, area) {
  if (!area) return "";
  const move = "(?:放入|放到|放进|归入|归到|归类到|移动到|移到|分到|划到)";
  const re = new RegExp(`(?:把|将)?\\s*(?:这个|该)?\\s*([^，。\\n]+?)\\s*(?:项目)?\\s*${move}\\s*`, "i");
  const m = text.match(re);
  if (!m?.[1]) return "";
  return m[1].trim().replace(/^(?:这个|该)\s*/, "").replace(/["'“”‘’]/g, "").slice(0, 90);
}

function stateSyncRequested(text) {
  return /next\s*plan/i.test(text) && /(更新|同步|刷新|写入|记录|调整)/i.test(text) && /(状态|进度|当前|项目|里|中)/i.test(text);
}

function findProjectForSync(source, title, state) {
  const exact = exactProjectMention(source, state);
  if (exact) return exact;
  const hit = bestProject(source, title, state);
  return hit?.score >= 0.34 ? hit.project : null;
}

function extractNextAction(source) {
  const focusPatterns = [
    /任务焦点[^\n。]*?(?:切换为|改为|变为)\s*[“\"]([^”\"\n]+)[”\"]/i,
    /(?:下一步|next\s*step)\s*[：:]\s*([^\n。]+)/i,
    /(?:next[_\s-]*action|下一步动作)\s*[：:]\s*([^\n。]+)/i
  ];
  for (const re of focusPatterns) {
    const m = source.match(re);
    if (m?.[1]) return m[1].trim().replace(/^[-–—]\s*/, "").slice(0, 220);
  }
  return "";
}

function lineMentionsMilestone(line, milestone) {
  const ln = normalize(line);
  const full = normalize(milestone.name);
  if (full && ln.includes(full)) return true;
  const id = String(milestone.id || "").trim();
  if (/^[a-z]+\d+$/i.test(id) || /^r\d+[a-z]?$/i.test(id)) {
    return new RegExp(`(^|[^a-z0-9])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z0-9]|$)`, "i").test(line);
  }
  const prefix = String(milestone.name || "").match(/^([A-Za-z]+\d+[A-Za-z]?)/)?.[1];
  if (prefix) return new RegExp(`(^|[^a-z0-9])${prefix}([^a-z0-9]|$)`, "i").test(line);
  return false;
}

function statusFromLine(line) {
  const t = normalize(line);
  if (/(started\s*[:=]?\s*false|尚未开始|未开始|not\s+started|planned|计划中|待开始)/i.test(t)) return "planned";
  if (/(blocked|阻塞|被阻塞|暂停)/i.test(t)) return "blocked";
  if (/(waiting|等待|待定)/i.test(t)) return "waiting";
  if (/(completed_for|completed|\bdone\b|已完成|完成$|完成\s*[\/；;])/i.test(t)) return "completed";
  if (/(started\s*[:=]?\s*true|active|进行中|正在进行|正在执行|已开始)/i.test(t)) return "active";
  return "";
}

function extractMilestoneStatuses(source, project) {
  const updates = {};
  const lines = String(source || "").split(/\n+/).map(x => x.trim()).filter(Boolean);
  for (const m of project.milestones || []) {
    for (const line of lines) {
      if (!lineMentionsMilestone(line, m)) continue;
      const status = statusFromLine(line);
      if (status) updates[m.id] = status;
    }
  }
  return updates;
}

function buildStateSyncCandidate(turn, state) {
  const text = String(turn.userText || "").trim();
  if (!stateSyncRequested(text)) return null;
  const assistant = String(turn.assistantText || "").trim();
  const source = `${text}\n${assistant}`;
  const project = findProjectForSync(source, turn.title || "", state);
  if (!project) return null;

  const nextAction = extractNextAction(assistant || text);
  const milestoneStatuses = extractMilestoneStatuses(assistant || text, project);
  const changedStatuses = {};
  for (const [id, status] of Object.entries(milestoneStatuses)) {
    const cur = (project.milestones || []).find(m => m.id === id);
    if (cur && cur.status !== status) changedStatuses[id] = status;
  }

  const action = {action: "update_project_snapshot", project_id: project.id};
  let changeCount = 0;
  if (nextAction && normalize(nextAction) !== normalize(project.next_action || "")) {
    action.next_action = nextAction;
    changeCount++;
  }
  if (Object.keys(changedStatuses).length) {
    action.milestone_statuses = changedStatuses;
    changeCount += Object.keys(changedStatuses).length;
  }
  if (!changeCount) {
    return {
      id: crypto.randomUUID(),
      kind: "state_sync_noop",
      confidence: 0.96,
      label: `状态已是最新：${project.name}`,
      reason: "没有检测到与当前 NextPlan 状态不同的明确变更",
      action: null,
      informational: true
    };
  }
  return {
    id: crypto.randomUUID(),
    kind: "state_sync",
    confidence: 0.96,
    label: `更新项目状态：${project.name}`,
    reason: `识别到 ${changeCount} 项明确状态变化`,
    action
  };
}

export function classifyTurn(turn, state) {
  const text = String(turn.userText || "").trim();
  if (!text || /[?？]\s*$/.test(text)) return null;

  const area = targetArea(text);
  if (area && /(放入|放到|放进|归入|归到|归类到|移动到|移到|分到|划到)/i.test(text)) {
    let project = exactProjectMention(text, state);
    let name = project?.name || extractMoveProjectName(text, area);
    if (project) {
      return {
        id: crypto.randomUUID(),
        kind: "move_project_area",
        confidence: 0.98,
        label: `移动项目：${project.name} → ${area.label}`,
        reason: "检测到明确的项目区域调整",
        action: {action: "update_project_snapshot", project_id: project.id, category: area.category}
      };
    }
    if (name) {
      return {
        id: crypto.randomUUID(),
        kind: "create_project_in_area",
        confidence: 0.95,
        label: `新增并归类：${name} → ${area.label}`,
        reason: "未找到同名项目；按明确指令创建并归入目标区域",
        action: {action: "create_project", name, category: area.category, priority: 2, next_action: ""}
      };
    }
  }

  const newProjectName = /next\s*plan/i.test(text) ? extractNewProjectName(text) : "";
  if (newProjectName) {
    const exists = (state.projects || []).find(p => normalize(p.name) === normalize(newProjectName));
    if (exists) {
      return {
        id: crypto.randomUUID(),
        kind: "project_exists",
        confidence: 0.99,
        label: `项目已存在：${exists.name}`,
        reason: "NextPlan 中已有同名项目",
        action: null,
        informational: true
      };
    }
    return {
      id: crypto.randomUUID(),
      kind: "create_project",
      confidence: 0.98,
      label: `新增项目：${newProjectName}`,
      reason: "检测到明确的 NextPlan 新项目指令",
      action: {
        action: "create_project",
        name: newProjectName,
        category: inferCategory(newProjectName),
        priority: 2,
        next_action: ""
      }
    };
  }

  const stateSync = buildStateSyncCandidate(turn, state);
  if (stateSync) return stateSync;

  const deleteIntent = /(删除|删掉|移除|去掉|清除|delete|remove)/i.test(text) && /next\s*plan/i.test(text);
  if (deleteIntent) {
    const hit = deletionTarget(text, turn.title || "", state);
    if (hit?.kind === "project") {
      return {
        id: crypto.randomUUID(),
        kind: "delete_project",
        destructive: true,
        requiresConfirmation: true,
        confidence: 0.97,
        label: `删除项目：${hit.project.name}`,
        reason: "删除操作始终需要手动确认",
        action: {action: "delete_project", project_id: hit.project.id}
      };
    }
    if (hit?.kind === "task") {
      return {
        id: crypto.randomUUID(),
        kind: "delete_task",
        destructive: true,
        requiresConfirmation: true,
        confidence: 0.97,
        label: `删除任务：${hit.milestone.name}`,
        reason: `匹配到 ${hit.project.name}；删除操作始终需要手动确认`,
        action: {action: "delete_task", project_id: hit.project.id, task_id: hit.milestone.id}
      };
    }
  }

  const completion = /(完成了|做完了|提交了|发送了|保存好了|创建好了|部署好了|通过了|已经完成|已经提交|已经发送)/.test(text);
  if (completion) {
    const hit = bestMilestone(text, turn.title || "", state);
    if (hit && hit.score >= 0.35) {
      const confidence = Math.min(0.99, 0.62 + hit.score * 0.37);
      return {
        id: crypto.randomUUID(),
        kind: "completion",
        confidence,
        label: `完成：${hit.milestone.name}`,
        reason: `匹配到 ${hit.project.name}`,
        action: {action: "complete_task", project_id: hit.project.id, task_id: hit.milestone.id}
      };
    }
  }

  const explicitAdd = /(加到|加入|记录到|放到)\s*NextPlan/i.test(text);
  if (explicitAdd) {
    const hit = bestProject(text, turn.title || "", state);
    if (hit && hit.score >= 0.25) {
      const name = text.replace(/(加到|加入|记录到|放到)\s*NextPlan.*$/i, "").trim().slice(0, 90);
      if (name) {
        return {
          id: crypto.randomUUID(),
          kind: "new_task",
          confidence: Math.min(0.96, 0.78 + hit.score * 0.18),
          label: `新增任务：${name}`,
          reason: `匹配到 ${hit.project.name}`,
          action: {action: "create_task", project_id: hit.project.id, name}
        };
      }
    }
  }

  return null;
}
