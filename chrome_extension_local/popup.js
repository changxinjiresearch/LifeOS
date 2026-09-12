async function send(message) {
  return await chrome.runtime.sendMessage(message);
}

async function refresh() {
  const status = await send({type: "NEXTPLAN_GET_STATUS"});
  const statusEl = document.getElementById("status");
  const itemsEl = document.getElementById("items");
  statusEl.textContent = status.paired ? `Connected · ${status.pending.length} pending` : "Not paired with NextPlan Local";
  statusEl.className = status.paired ? "muted ok" : "muted warn";
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
  if (status.paired && !(status.pending || []).length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.style.marginTop = "10px";
    empty.textContent = "No pending changes.";
    itemsEl.appendChild(empty);
  }
}

document.getElementById("settings").onclick = () => chrome.runtime.openOptionsPage();
refresh().catch(err => { document.getElementById("status").textContent = err.message; });
