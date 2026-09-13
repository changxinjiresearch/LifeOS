const DEFAULTS = {
  endpoint: "http://127.0.0.1:47123",
  bridgeEndpoint: "http://127.0.0.1:47124",
  token: "",
  autoSync: true,
  autoThreshold: 0.88
};
const GENERATION = "local-v0.1.1-auto-bootstrap";

async function getConfig() {
  return {...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS))};
}

async function readJson(res) {
  try { return await res.json(); } catch { return {}; }
}

async function bootstrapSession() {
  const cfg = await getConfig();
  let res;
  try {
    res = await fetch(`${cfg.bridgeEndpoint}/bridge/bootstrap`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-NextPlan-Extension-Id": chrome.runtime.id
      },
      body: "{}"
    });
  } catch {
    throw new Error("Open NextPlan Desktop to connect");
  }
  const body = await readJson(res);
  if (!res.ok) {
    if (res.status === 403) throw new Error("This is not the official NextPlan Local Bridge build");
    if (res.status === 503) throw new Error("NextPlan Desktop is starting. Try again in a moment.");
    throw new Error(body.error || `Desktop bridge HTTP ${res.status}`);
  }
  if (!body.token || !body.endpoint) throw new Error("Desktop bridge returned an incomplete session");
  const endpoint = String(body.endpoint).replace(/\/$/, "");
  await chrome.storage.local.set({token: body.token, endpoint, lastBootstrap: new Date().toISOString()});
  return {...cfg, token: body.token, endpoint};
}

async function api(path, options = {}, requireAuth = true, allowRetry = true) {
  let cfg = await getConfig();
  if (requireAuth && !cfg.token) cfg = await bootstrapSession();
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (requireAuth) headers.Authorization = `Bearer ${cfg.token}`;
  let res;
  try {
    res = await fetch(`${cfg.endpoint}${path}`, {...options, headers, cache: "no-store"});
  } catch {
    if (requireAuth && allowRetry) {
      await chrome.storage.local.set({token: ""});
      await bootstrapSession();
      return api(path, options, requireAuth, false);
    }
    throw new Error("NextPlan Desktop is not reachable");
  }
  const body = await readJson(res);
  if ((res.status === 401 || res.status === 403) && requireAuth && allowRetry) {
    await chrome.storage.local.set({token: ""});
    await bootstrapSession();
    return api(path, options, requireAuth, false);
  }
  if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
  return body;
}

async function connectDesktop() {
  const cfg = await getConfig();
  if (!cfg.token) await bootstrapSession();
  await api("/state");
  const health = await api("/healthz", {}, false);
  await refreshBadge();
  const current = await getConfig();
  return {status: "connected", endpoint: current.endpoint, runtime: health.runtime || "nextplan-local-core"};
}

async function getPending() {
  const result = await api("/pending");
  return result.pending || [];
}

async function refreshBadge() {
  let items = [];
  try { items = await getPending(); } catch {}
  await chrome.action.setBadgeText({text: items.length ? String(Math.min(items.length, 99)) : ""});
  await chrome.action.setBadgeBackgroundColor({color: "#3478F6"});
  return items;
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

function clientContext() {
  let timezone = "";
  try { timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch {}
  return {
    source: "nextplan-local-extension",
    bridgeVersion: "0.1.1",
    now: new Date().toISOString(),
    timezone,
    utcOffsetMinutes: -new Date().getTimezoneOffset()
  };
}

async function handleTurn(turn) {
  if (await seen(turn.fingerprint)) return {status: "duplicate"};
  let result;
  try {
    result = await api("/conversation/capture", {
      method: "POST",
      body: JSON.stringify({turn, client: clientContext(), apply: true})
    });
  } catch (err) {
    const message = String(err?.message || "Connection failed");
    return {status: message.includes("Open NextPlan Desktop") || message.includes("not reachable") ? "needs_desktop" : "error", error: message};
  }

  const candidate = result?.candidate || null;
  if (!candidate) {
    await remember(turn.fingerprint);
    return {status: "no_change"};
  }
  if (candidate.informational || !candidate.action) {
    await remember(turn.fingerprint);
    return {status: "informational", label: candidate.label || "No change needed"};
  }
  if (result.receipt) {
    await remember(turn.fingerprint);
    await chrome.storage.local.set({lastSync: {at: new Date().toISOString(), label: candidate.label, result: result.receipt.status}});
    return {status: "auto_synced", label: candidate.label, receipt: result.receipt};
  }

  await refreshBadge();
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
  const receipt = await api("/pending/apply", {method: "POST", body: JSON.stringify({id})});
  await refreshBadge();
  await chrome.storage.local.set({lastSync: {at: new Date().toISOString(), label: receipt.summary || id, result: receipt.status}});
  return receipt;
}

async function ignorePending(id) {
  const result = await api("/pending/ignore", {method: "POST", body: JSON.stringify({id})});
  await refreshBadge();
  return result;
}

async function statusSnapshot() {
  let connectionError = null;
  let runtime = null;
  try {
    const connected = await connectDesktop();
    runtime = connected.runtime;
  } catch (err) {
    connectionError = err.message;
  }
  const config = await getConfig();
  let pending = [];
  if (!connectionError) {
    try { pending = await getPending(); } catch (err) { connectionError = err.message; }
  }
  const {lastSync = null} = await chrome.storage.local.get({lastSync: null});
  return {
    connected: !connectionError,
    paired: !connectionError,
    connectionError,
    runtime,
    endpoint: config.endpoint,
    pending,
    lastSync,
    mode: "desktop-auto-bootstrap",
    version: "0.1.1"
  };
}

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.local.get(Object.keys(DEFAULTS));
  await chrome.storage.local.set({...DEFAULTS, ...current, token: ""});
  try { await connectDesktop(); } catch {}
});
chrome.runtime.onStartup.addListener(async () => {
  await chrome.storage.local.set({token: ""});
  try { await connectDesktop(); } catch {}
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "NEXTPLAN_TURN") {
    handleTurn(message.turn).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_CONNECT" || message?.type === "NEXTPLAN_PAIR") {
    connectDesktop().then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_GET_STATUS") {
    statusSnapshot().then(sendResponse).catch(err => sendResponse({connected: false, paired: false, connectionError: err.message, pending: []}));
    return true;
  }
  if (message?.type === "NEXTPLAN_APPLY") {
    applyPending(message.id).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_IGNORE") {
    ignorePending(message.id).then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
  if (message?.type === "NEXTPLAN_TEST") {
    connectDesktop().then(sendResponse).catch(err => sendResponse({status: "error", error: err.message}));
    return true;
  }
});
