const list = document.getElementById("list");
const statusEl = document.getElementById("status");

function esc(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function formatLastSync(lastSync) {
  if (!lastSync?.at) return "";
  const d = new Date(lastSync.at);
  const time = Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
  return `最近同步${time ? ` · ${time}` : ""}：${esc(lastSync.label || "状态已更新")}`;
}

async function refresh() {
  const data = await chrome.runtime.sendMessage({type:"NEXTPLAN_GET_STATUS"});
  if (!data?.configured) {
    statusEl.textContent = "未完成一次性连接设置";
    list.innerHTML = `<div class="card"><div class="item-title">先连接 NextPlan 后端</div><div class="reason">打开设置，生成一个浏览器 Token，并把同一 Token 保存到 Railway。</div></div>`;
    return;
  }

  statusEl.textContent = data.autoSync ? `自动同步已开启 · 阈值 ${Math.round(data.autoThreshold*100)}%` : "仅候选确认模式";
  const items = data.pending || [];
  if (!items.length) {
    const last = formatLastSync(data.lastSync);
    list.innerHTML = `<div class="empty">没有待确认的状态变化。${last ? `<div class="last-sync">${last}</div>` : ""}</div>`;
    return;
  }

  list.innerHTML = items.map(x => {
    const destructive = Boolean(x.destructive || x.requiresConfirmation);
    const cardClass = destructive ? "card destructive" : "card";
    const applyClass = destructive ? "danger" : "primary";
    const applyLabel = destructive ? "确认删除" : "同步";
    const warning = destructive ? `<div class="warning">此操作会从 NextPlan 当前状态中删除该条目，必须手动确认。</div>` : "";
    return `
      <div class="${cardClass}" data-id="${esc(x.id)}">
        <div class="item-title">${esc(x.label)}</div>
        <div class="reason">${esc(x.reason)} · 置信度 ${Math.round((x.confidence||0)*100)}%</div>
        ${warning}
        <div class="actions">
          <button class="${applyClass}" data-act="apply" data-destructive="${destructive ? "1" : "0"}">${applyLabel}</button>
          <button class="secondary" data-act="ignore">取消</button>
        </div>
        <div class="inline-status" aria-live="polite"></div>
      </div>`;
  }).join("");
}

function setBusy(card, busy) {
  card.querySelectorAll("button").forEach(b => { b.disabled = busy; });
}

list.addEventListener("click", async e => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const card = btn.closest("[data-id]");
  const id = card?.dataset.id;
  if (!id) return;

  const feedback = card.querySelector(".inline-status");
  setBusy(card, true);

  if (btn.dataset.act === "apply") {
    const destructive = btn.dataset.destructive === "1";
    const original = btn.textContent;
    btn.innerHTML = `<span class="spinner"></span>${destructive ? "删除中…" : "同步中…"}`;
    feedback.textContent = destructive
      ? "正在提交删除，并等待中央状态确认…"
      : "正在写入 NextPlan，并等待中央状态确认…";
    feedback.className = "inline-status";

    try {
      const res = await chrome.runtime.sendMessage({type:"NEXTPLAN_APPLY", id});
      if (res?.status === "error") throw new Error(res.error || "同步失败");

      if(res?.status==="verification_pending"){
        btn.textContent="等待核验 · 点击重查";
        feedback.textContent="已提交写入，但 NextPlan 正式状态尚未核验成功。该操作仍保留在待确认队列，不会重复提交。";
        feedback.className="inline-status";
        setBusy(card,false);
        return;
      }
      btn.textContent = destructive ? "✓ 已删除" : "✓ 已同步";
      feedback.textContent = res?.status === "accepted_pending_builder"
        ? (destructive ? "删除已提交，中央状态正在更新。" : "已提交，中央状态正在更新。")
        : (destructive ? "已从 NextPlan 当前状态删除。" : "已同步到 NextPlan。");
      feedback.className = "inline-status ok";
      card.classList.add("done");
      setTimeout(() => refresh().catch(() => {}), 1100);
    } catch (err) {
      btn.textContent = original;
      feedback.textContent = `${destructive ? "删除" : "同步"}失败：${err?.message || "未知错误"}`;
      feedback.className = "inline-status bad";
      setBusy(card, false);
    }
    return;
  }

  btn.textContent = "取消中…";
  feedback.textContent = "";
  try {
    const res = await chrome.runtime.sendMessage({type:"NEXTPLAN_IGNORE", id});
    if (res?.status === "error") throw new Error(res.error || "取消失败");
    card.classList.add("done");
    feedback.textContent = "已取消。";
    feedback.className = "inline-status ok";
    setTimeout(() => refresh().catch(() => {}), 450);
  } catch (err) {
    btn.textContent = "取消";
    feedback.textContent = `操作失败：${err?.message || "未知错误"}`;
    feedback.className = "inline-status bad";
    setBusy(card, false);
  }
});

document.getElementById("options").onclick = e => { e.preventDefault(); chrome.runtime.openOptionsPage(); };
document.getElementById("refresh").onclick = e => { e.preventDefault(); refresh(); };
refresh().catch(err => {
  statusEl.textContent = "状态读取失败";
  list.innerHTML = `<div class="card"><div class="reason">${esc(err?.message || "未知错误")}</div></div>`;
});
