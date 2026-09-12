const DEFAULTS = {
  endpoint: "http://127.0.0.1:47123",
  token: "",
  autoSync: true,
  autoThreshold: 0.88
};
const GENERATION = "local-v0.1-stage4";

async function getConfig() {
  return {...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS))};
}

async function api(path, options = {}, requireAuth = true) {
  const cfg = await getConfig();
  if (requireAuth && !cfg.token) throw new Error("NextPlan Local is not paired");
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (requireAuth) headers.Authorization = `Bearer ${cfg.token}`;
  const res = await fetch(`${cfg.endpoint}${path}`, {...options, headers});
  let body = {};
  try { body = await res.json(); } catch {}
  if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
  return body;
}

async function pair(code) {
  const result = await api("/pairing/complete", {
    method: "POST",
    body: JSON.stringify({code, extension_id: chrome.runtime.id})
  }, false);
  if (!result.token) throw new Error("Pairing did not return a local credential");
  await chrome.storage.local.set({token: result.token});
  return {status: "paired"};
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

async function seen(fp) {
  const {processedFingerprints = []} = await chrome.storage.local.get({processedFingerprints: []});
  return processedFingerprints.includes(`${GENERATION}:${fp}`);
}

async function remember(fp) {
  const {processedFingerprints = []} = await chrome.storage.local.get({processedFingerprints: []});
  const key = `${GENERATION}:${fp}`;
  if (!processedFingerprints.includes(key)) {
    await chrome.storage.local.set({processedFingerprints: [...processedFingerprints, key].slice(-300)});
  }
}

async function enqueue(candidate, turn) {
  const items = await getPending();
  items.push({...candidate, source: {title: turn.title, url: turn.url}});
  await setPending(items);
}

function clientContext() {
  let timezone = "";
  try { timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch {}
  return {
    source: "nextplan-local-extension",
    bridgeVersion: "0.1.0",
    now: new Date().toISOString(),
    timezone,
    utcOffsetMinutes: -new Date().getTimezoneOffset()
  };
}

async function handleTurn(turn) {
  if (await seen(turn.fingerprint)) return {status: "duplicate"};
  const cfg = await getConfig();
  if (!cfg.token) return {status: "needs_pairing"};

  let result;
  try {
    result = await api("/conversation/capture", {
      method: "POST",
      body: JSON.stringify({turn, client: clientContext(), apply: true})
    });
  } catch (err) {
    return {status: "error", error: err.message};
  }

  const candidate = result?.candidate || null;
  if (!candidate) {
    await remember(turn.fingerprint);
    return {status: "no_change"};
  }
  if (candidate.informational || !candidate.action) {
    await remember(turn.fingerprint);
    return {status: "informational", label: candidate.label || "无需变更"};
  }
  if (result.receipt) {
    await remember(turn.fingerprint);
    await chrome.storage.local.set({lastSync: {at: new Date().toISOString(), label: candidate.label, result: result.receipt.status}});
    return {status: "auto_synced", label: candidate.label, receipt: result.receipt};
  }

  await enqueue(candidate, turn);
  await remember(turn.fingerprint);
  return {
    status: "queued",
    label: candidate.label,
    confidence: candidate.confidence,
    requiresConfirmation: Boolean(candidate.requiresConfirmation),
    kind: candidate.kind
  };
}

async function applyPending(id) {
  const items = await getPending();
  const candidate = items.find(x => x.id === id);
  if (!candidate?.action) throw new Error("Candidate not found");
  const receipt = await api("/actions/execute", {
    method: "POST",
    body: JSON.stringify({action: candidate.action})
  });
  await setPending(items.filter(x => x.id !== id));
  await chrome.storage.local.set({lastSync: {at: new Date().toISOString(), label: candidate.label, result: receipt.status}});
  return receipt;
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
  if (message?.type === "NEXTPLAN_PAIR") {
    pair(String(message.code || "")).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_GET_STATUS") {
    Promise.all([getConfig(), getPending(), chrome.storage.local.get({lastSync: null})]).then(([config, pending, extra]) => {
      sendResponse({paired: Boolean(config.token), endpoint: config.endpoint, pending, lastSync: extra.lastSync, mode: "local-bridge", version: "0.1.0"});
    });
    return true;
  }
  if (message?.type === "NEXTPLAN_APPLY") {
    applyPending(message.id).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_IGNORE") {
    getPending().then(items => setPending(items.filter(x => x.id !== message.id))).then(() => sendResponse({status: "ignored"}));
    return true;
  }
  if (message?.type === "NEXTPLAN_TEST") {
    api("/healthz", {}, false).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
});
