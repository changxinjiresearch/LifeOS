import { classifyTurn } from "./classifier.js";

const DEFAULT_ENDPOINT = "https://lifeos-production-89ce.up.railway.app";
const DEFAULTS = { endpoint: DEFAULT_ENDPOINT, token: "", autoSync: true, autoThreshold: 0.88 };

async function getConfig() {
  return {...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS))};
}

async function api(path, options = {}) {
  const cfg = await getConfig();
  if (!cfg.token) throw new Error("NextPlan extension token is not configured");
  const res = await fetch(`${cfg.endpoint}${path}`, {
    ...options,
    headers: {"Authorization": `Bearer ${cfg.token}`, "Content-Type": "application/json", ...(options.headers || {})}
  });
  let body = {};
  try { body = await res.json(); } catch {}
  if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
  return body;
}

async function getPending() {
  return (await chrome.storage.local.get({pendingCandidates: []})).pendingCandidates;
}

async function setPending(items) {
  const trimmed = items.slice(-50);
  await chrome.storage.local.set({pendingCandidates: trimmed});
  await chrome.action.setBadgeText({text: trimmed.length ? String(Math.min(trimmed.length, 99)) : ""});
  await chrome.action.setBadgeBackgroundColor({color: "#3478F6"});
}

async function firstTimeFingerprint(fp) {
  const data = await chrome.storage.local.get({processedFingerprints: []});
  if (data.processedFingerprints.includes(fp)) return false;
  const next = [...data.processedFingerprints, fp].slice(-250);
  await chrome.storage.local.set({processedFingerprints: next});
  return true;
}

async function enqueue(candidate, turn) {
  const items = await getPending();
  items.push({...candidate, source: {title: turn.title, url: turn.url}});
  await setPending(items);
}

async function applyCandidate(candidate) {
  const result = await api("/extension/action", {method: "POST", body: JSON.stringify(candidate.action)});
  await setPending((await getPending()).filter(x => x.id !== candidate.id));
  await chrome.storage.local.set({lastSync: {at: new Date().toISOString(), label: candidate.label, result: result.status || "ok"}});
  return result;
}

async function handleTurn(turn) {
  if (!await firstTimeFingerprint(turn.fingerprint)) return {status: "duplicate"};
  const cfg = await getConfig();
  if (!cfg.token) {
    await chrome.action.setBadgeText({text: "!"});
    await chrome.action.setBadgeBackgroundColor({color: "#FF9F0A"});
    return {status: "needs_setup"};
  }
  const state = await api("/extension/state");
  const candidate = classifyTurn(turn, state);
  if (!candidate) return {status: "no_change"};

  // Destructive actions (delete project/task) are never auto-synced,
  // regardless of confidence or threshold. They must be confirmed in popup.
  const canAutoSync = !candidate.requiresConfirmation && !candidate.destructive;
  if (cfg.autoSync && canAutoSync && candidate.confidence >= Number(cfg.autoThreshold || 0.88)) {
    try {
      return {status: "auto_synced", result: await applyCandidate(candidate)};
    } catch (err) {
      await enqueue({...candidate, reason: `${candidate.reason}；自动同步失败：${err.message}`}, turn);
      return {status: "queued_after_error"};
    }
  }
  await enqueue(candidate, turn);
  return {status: "queued", confidence: candidate.confidence, requiresConfirmation: Boolean(candidate.requiresConfirmation)};
}

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.local.get(Object.keys(DEFAULTS));
  await chrome.storage.local.set({...DEFAULTS, ...current});
  await setPending(await getPending());
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "NEXTPLAN_TURN") {
    handleTurn(message.turn).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_GET_STATUS") {
    Promise.all([getConfig(), getPending(), chrome.storage.local.get({lastSync: null})]).then(([config, pending, extra]) => {
      sendResponse({configured: Boolean(config.token), autoSync: config.autoSync, autoThreshold: config.autoThreshold, pending, lastSync: extra.lastSync});
    });
    return true;
  }
  if (message?.type === "NEXTPLAN_APPLY") {
    getPending().then(items => {
      const candidate = items.find(x => x.id === message.id);
      if (!candidate) throw new Error("Candidate not found");
      return applyCandidate(candidate);
    }).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_IGNORE") {
    getPending().then(items => setPending(items.filter(x => x.id !== message.id))).then(() => sendResponse({status: "ignored"}));
    return true;
  }
  if (message?.type === "NEXTPLAN_TEST") {
    api("/extension/state").then(state => sendResponse({status: "ok", projects: (state.projects || []).length})).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
});
