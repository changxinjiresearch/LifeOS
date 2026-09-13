const statusEl = document.getElementById("status");
const detailEl = document.getElementById("detail");
const resultEl = document.getElementById("result");

function showStatus(status) {
  if (status?.connected) {
    statusEl.textContent = "Connected to NextPlan Desktop";
    statusEl.className = "status ok";
    detailEl.textContent = `${status.runtime || "NextPlan Local Core"} · ${status.endpoint || "http://127.0.0.1:47123"}`;
  } else {
    statusEl.textContent = "NextPlan Desktop is not connected";
    statusEl.className = "status bad";
    detailEl.textContent = status?.connectionError || "Open NextPlan Desktop, then click Connect to NextPlan.";
  }
}

async function refresh() {
  const status = await chrome.runtime.sendMessage({type: "NEXTPLAN_GET_STATUS"});
  showStatus(status);
  return status;
}

async function connect() {
  resultEl.className = "muted";
  resultEl.textContent = "Connecting…";
  const response = await chrome.runtime.sendMessage({type: "NEXTPLAN_CONNECT"});
  if (response?.status !== "connected") throw new Error(response?.error || "Could not connect to NextPlan Desktop");
  resultEl.className = "muted ok";
  resultEl.textContent = "Connected successfully. You can now use NextPlan from ChatGPT.";
  await refresh();
}

document.getElementById("connect").onclick = async () => {
  try { await connect(); }
  catch (err) {
    resultEl.className = "muted bad";
    resultEl.textContent = err.message;
    await refresh().catch(() => {});
  }
};

document.getElementById("test").onclick = async () => {
  try {
    const response = await chrome.runtime.sendMessage({type: "NEXTPLAN_TEST"});
    if (response?.status !== "connected") throw new Error(response?.error || "NextPlan Desktop unavailable");
    resultEl.className = "muted ok";
    resultEl.textContent = `Connection healthy · ${response.runtime || "NextPlan Local Core"}`;
    await refresh();
  } catch (err) {
    resultEl.className = "muted bad";
    resultEl.textContent = err.message;
    await refresh().catch(() => {});
  }
};

refresh().catch(err => {
  showStatus({connected: false, connectionError: err.message});
});
