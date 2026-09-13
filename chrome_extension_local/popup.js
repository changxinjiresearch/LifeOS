async function send(message) {
  return await chrome.runtime.sendMessage(message);
}

async function refresh() {
  const status = await send({type: "NEXTPLAN_GET_STATUS"});
  const statusEl = document.getElementById("status");
  const itemsEl = document.getElementById("items");
  const connectBtn = document.getElementById("connect");
  if (status.connected) {
    statusEl.textContent = `Connected · ${status.pending.length} pending`;
    statusEl.className = "muted ok";
    connectBtn.style.display = "none";
  } else {
    statusEl.textContent = status.connectionError || "Open NextPlan Desktop to connect";
    statusEl.className = "muted warn";
    connectBtn.style.display = "inline-block";
  }
  itemsEl.innerHTML = "";
  for (const item of status.pending || []) {
    const card = document.createElement("div");
    card.className = "item";
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = item.label || item.kind || "Detected change";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${item.kind || "change"} · confidence ${Number(item.confidence || 0).toFixed(2)}`;
    const apply = document.createElement("button");
    apply.className = "apply";
    apply.textContent = "Apply";
    apply.onclick = async () => { await send({type: "NEXTPLAN_APPLY", id: item.id}); await refresh(); };
    const ignore = document.createElement("button");
    ignore.className = "ignore";
    ignore.textContent = "Ignore";
    ignore.onclick = async () => { await send({type: "NEXTPLAN_IGNORE", id: item.id}); await refresh(); };
    card.append(label, meta, apply, ignore);
    itemsEl.appendChild(card);
  }
  if (status.connected && !(status.pending || []).length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.style.marginTop = "10px";
    empty.textContent = "No pending changes.";
    itemsEl.appendChild(empty);
  }
}

document.getElementById("connect").onclick = async () => {
  const statusEl = document.getElementById("status");
  statusEl.textContent = "Connecting…";
  statusEl.className = "muted";
  const result = await send({type: "NEXTPLAN_CONNECT"});
  if (result?.status !== "connected") {
    statusEl.textContent = result?.error || "Could not connect to NextPlan Desktop";
    statusEl.className = "muted bad";
    return;
  }
  await refresh();
};
document.getElementById("settings").onclick = () => chrome.runtime.openOptionsPage();
refresh().catch(err => {
  const statusEl = document.getElementById("status");
  statusEl.textContent = err.message;
  statusEl.className = "muted bad";
});
