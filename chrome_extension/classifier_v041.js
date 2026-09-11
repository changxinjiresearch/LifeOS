import { classifyTurn as classifyBase } from "./classifier.js";

function normalize(text) {
  return String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function compact(text) {
  return normalize(text).replace(/[^a-z0-9\u3400-\u9fff]+/g, "");
}

function cleanEntityName(value) {
  return String(value || "")
    .trim()
    .replace(/^[\s"'“”‘’「」『』【】]+|[\s"'“”‘’「」『』【】]+$/g, "")
    .replace(/^项目\s*/i, "")
    .replace(/\s*项目$/i, "")
    .trim();
}

function findProjectByExactName(name, state) {
  const target = normalize(cleanEntityName(name));
  if (!target) return null;
  return (state.projects || []).find(p => normalize(p.name) === target) || null;
}

function findExactProject(text, state) {
  const ctext = compact(text);
  let best = null;
  for (const p of state.projects || []) {
    const n = compact(p.name);
    const id = compact(p.id);
    if ((n && ctext.includes(n)) || (id && id.length >= 4 && ctext.includes(id))) {
      const score = Math.max(n.length, id.length);
      if (!best || score > best.score) best = {project: p, score};
    }
  }
  return best?.project || null;
}

function extractRenameTarget(text) {
  const raw = String(text || "").trim();
  const patterns = [
    // 将 NextPlan 系统中名称为「这个」的项目重命名为「NextPlan开发」
    /(?:把|将)\s*(?:NextPlan\s*系统中\s*)?(?:名称(?:为|是)|名为)\s*([^，。；;\n]+?)\s*的\s*项目\s*(?:改成|改为|改名为|更名为|重命名为)\s*([^，。；;\n]+)/i,
    // 把项目「这个」重命名为「NextPlan开发」
    /(?:把|将)\s*(?:NextPlan\s*系统中\s*)?项目\s*([^，。；;\n]+?)\s*(?:改成|改为|改名为|更名为|重命名为)\s*([^，。；;\n]+)/i,
    // 把「这个」项目重命名为「NextPlan开发」
    /(?:把|将)\s*(?:NextPlan\s*系统中\s*)?([^，。；;\n]+?)\s*项目\s*(?:改成|改为|改名为|更名为|重命名为)\s*([^，。；;\n]+)/i,
    // 「这个」项目重命名为「NextPlan开发」
    /([^，。；;\n]+?)\s*项目\s*(?:改成|改为|改名为|更名为|重命名为)\s*([^，。；;\n]+)/i
  ];

  for (const re of patterns) {
    const m = raw.match(re);
    if (!m?.[2]) continue;
    const from = cleanEntityName(m[1]);
    const to = cleanEntityName(m[2]).slice(0, 90);
    if (from && to) return {from, to};
  }
  return null;
}

function extractCurrentStep(text) {
  const patterns = [
    /(?:现在|目前|当前)(?:是)?\s*(?:正在|在)?\s*(?:做|进行|处理)\s*[“\"「『]??([^”\"」』，。；;\n]+?)[”\"」』]?(?:这一步|这项任务|这一项|阶段)?(?=[，。；;\n]|下一步|$)/i,
    /(?:当前进度|当前步骤|现在进度|目前进度)\s*(?:是|为|[:：])\s*[“\"「『]?([^”\"」』，。；;\n]+)[”\"」』]?/i
  ];
  for (const re of patterns) {
    const m = String(text || "").match(re);
    if (m?.[1]) return cleanEntityName(m[1].replace(/(?:这一步|这项任务|这一项|阶段)$/i, "")).slice(0, 120);
  }
  return "";
}

function extractNextAction(text) {
  const patterns = [
    /(?:下一步|next\s*step)\s*(?:是|为|[:：])\s*[“\"「『]?([^”\"」』\n。；;]+)[”\"」』]?/i,
    /(?:next[_\s-]*action|下一步动作)\s*(?:是|为|[:：])\s*[“\"「『]?([^”\"」』\n。；;]+)[”\"」』]?/i
  ];
  for (const re of patterns) {
    const m = String(text || "").match(re);
    if (m?.[1]) return cleanEntityName(m[1]).slice(0, 220);
  }
  return "";
}

function directProjectEdit(turn, state) {
  const text = String(turn.userText || "").trim();
  const rename = extractRenameTarget(text);
  const currentStep = extractCurrentStep(text);
  const nextAction = extractNextAction(text);
  if (!rename && !currentStep && !nextAction) return null;

  // If a rename command explicitly names the source project, exact-name resolution wins.
  // This prevents the target name or surrounding words from stealing the match.
  let project = rename?.from ? findProjectByExactName(rename.from, state) : null;
  if (!project) project = findExactProject(text, state);
  if (!project) return null;

  const action = {action: "update_project_snapshot", project_id: project.id};
  let count = 0;
  if (rename?.to && normalize(rename.to) !== normalize(project.name)) {
    action.name = rename.to;
    count++;
  }
  if (currentStep) {
    action.current_step = currentStep;
    action.status = "active";
    count++;
  }
  if (nextAction && normalize(nextAction) !== normalize(project.next_action || "")) {
    action.next_action = nextAction;
    count++;
  }
  if (!count) return null;

  return {
    id: crypto.randomUUID(),
    kind: "direct_project_edit",
    confidence: 0.99,
    label: `更新项目：${project.name}${action.name ? ` → ${action.name}` : ""}`,
    reason: `识别到 ${count} 项明确项目变更`,
    action
  };
}

export function classifyTurn(turn, state) {
  return directProjectEdit(turn, state) || classifyBase(turn, state);
}
