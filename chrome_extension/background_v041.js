const DEFAULT_ENDPOINT = "https://lifeos-production-89ce.up.railway.app";
const DEFAULTS = { endpoint: DEFAULT_ENDPOINT, token: "", autoSync: true, autoThreshold: 0.88 };
const PROCESSING_GENERATION = "v0.5.0-cloud-bridge";

async function getConfig() {
  return {...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS))};
}

async function api(path, options = {}) {
  const cfg = await getConfig();
  if (!cfg.token) throw new Error("NextPlan extension token is not configured");
  const res = await fetch(`${cfg.endpoint}${path}`, {
    ...options,
    headers: {
      "Authorization": `Bearer ${cfg.token}`,
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
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

function fingerprintKey(fp) {
  return `${PROCESSING_GENERATION}:${fp}`;
}

async function wasProcessed(fp) {
  const data = await chrome.storage.local.get({processedFingerprints: []});
  return data.processedFingerprints.includes(fingerprintKey(fp));
}

async function rememberProcessed(fp) {
  const data = await chrome.storage.local.get({processedFingerprints: []});
  const key = fingerprintKey(fp);
  if (data.processedFingerprints.includes(key)) return;
  await chrome.storage.local.set({processedFingerprints: [...data.processedFingerprints, key].slice(-250)});
}

async function enqueue(candidate, turn) {
  const items = await getPending();
  items.push({...candidate, source: {title: turn.title, url: turn.url}});
  await setPending(items);
}

async function applyCandidate(candidate) {
  if (!candidate?.action) throw new Error("Candidate has no writable action");
  const result = await api("/extension/action", {
    method: "POST",
    body: JSON.stringify(candidate.action)
  });
  await setPending((await getPending()).filter(x => x.id !== candidate.id));
  await chrome.storage.local.set({
    lastSync: {at: new Date().toISOString(), label: candidate.label, result: result.status || "ok"}
  });
  return result;
}

function clientContext() {
  let timezone = "";
  try { timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch {}
  return {
    now: new Date().toISOString(),
    timezone,
    utcOffsetMinutes: -new Date().getTimezoneOffset(),
    bridgeVersion: "0.5.0"
  };
}

async function classifyInCloud(turn) {
  const result = await api("/extension/classify", {
    method: "POST",
    body: JSON.stringify({turn, client: clientContext()})
  });
  return result?.candidate || null;
}

async function handleTurn(turn) {
  if (await wasProcessed(turn.fingerprint)) return {status: "duplicate"};

  const cfg = await getConfig();
  if (!cfg.token) {
    await chrome.action.setBadgeText({text: "!"});
    await chrome.action.setBadgeBackgroundColor({color: "#FF9F0A"});
    return {status: "needs_setup"};
  }

  let candidate;
  try {
    candidate = await classifyInCloud(turn);
  } catch (err) {
    return {status: "error", error: `云端解析不可用：${err.message}`};
  }

  if (!candidate) {
    await rememberProcessed(turn.fingerprint);
    return {status: "no_change", explicitNextPlan: /next\s*plan/i.test(String(turn.userText || ""))};
  }

  if (candidate.informational || !candidate.action) {
    await rememberProcessed(turn.fingerprint);
    return {status: "informational", label: candidate.label, reason: candidate.reason};
  }

  const canAutoSync = !candidate.requiresConfirmation && !candidate.destructive;
  if (cfg.autoSync && canAutoSync && Number(candidate.confidence || 0) >= Number(cfg.autoThreshold || 0.88)) {
    try {
      const result = await applyCandidate(candidate);
      await rememberProcessed(turn.fingerprint);
      return {status: "auto_synced", label: candidate.label, result};
    } catch (err) {
      await enqueue({...candidate, reason: `${candidate.reason || "云端识别"}；自动同步失败：${err.message}`}, turn);
      await rememberProcessed(turn.fingerprint);
      return {status: "queued_after_error", label: candidate.label, error: err.message};
    }
  }

  await enqueue(candidate, turn);
  await rememberProcessed(turn.fingerprint);
  return {
    status: "queued",
    label: candidate.label,
    confidence: candidate.confidence,
    destructive: Boolean(candidate.destructive),
    requiresConfirmation: Boolean(candidate.requiresConfirmation)
  };
}

async function injectIntoOpenChatGPTTabs() {
  try {
    const tabs = await chrome.tabs.query({url: ["https://chatgpt.com/*"]});
    for (const tab of tabs) {
      if (!tab.id) continue;
      try { await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["content.js"]}); } catch {}
    }
  } catch {}
}

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.local.get(Object.keys(DEFAULTS));
  await chrome.storage.local.set({...DEFAULTS, ...current});
  await setPending(await getPending());
  await injectIntoOpenChatGPTTabs();
});

chrome.runtime.onStartup.addListener(() => { injectIntoOpenChatGPTTabs(); });

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "NEXTPLAN_TURN") {
    handleTurn(message.turn).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_GET_STATUS") {
    Promise.all([getConfig(), getPending(), chrome.storage.local.get({lastSync: null})]).then(([config, pending, extra]) => {
      sendResponse({configured: Boolean(config.token), autoSync: config.autoSync, autoThreshold: config.autoThreshold, pending, lastSync: extra.lastSync, mode: "cloud-bridge", version: "0.5.0"});
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
    Promise.all([
      api("/extension/state"),
      api("/extension/classify", {
        method: "POST",
        body: JSON.stringify({turn: {userText: "NextPlan bridge health test?", assistantText: "", title: "", url: ""}, client: clientContext()})
      })
    ]).then(([state, cloud]) => sendResponse({status: "ok", projects: (state.projects || []).length, classifier: cloud.classifier || "cloud"}))
      .catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
});
