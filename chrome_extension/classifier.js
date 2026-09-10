function normalize(text) {
  return String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
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

export function classifyTurn(turn, state) {
  const text = String(turn.userText || "").trim();
  if (!text || /[?？]\s*$/.test(text)) return null;

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
