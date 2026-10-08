(() => {
  if (window.__NEXTPLAN_SYNC_V040__) return;
  window.__NEXTPLAN_SYNC_V040__ = true;

  const seen = new Set();
  let timer = null;
  let toastTimer = null;

  function textOf(el) {
    return (el?.innerText || el?.textContent || "").trim();
  }

  function stableKey(user, ordinal) {
    const raw = `${location.pathname}|${ordinal}|${user}`;
    let h = 2166136261;
    for (let i = 0; i < raw.length; i++) {
      h ^= raw.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(16);
  }

  function showToast(message, kind = "info", duration = 4200) {
    let host = document.getElementById("nextplan-sync-toast");
    if (!host) {
      host = document.createElement("div");
      host.id = "nextplan-sync-toast";
      Object.assign(host.style, {
        position: "fixed",
        right: "22px",
        bottom: "22px",
        zIndex: "2147483647",
        maxWidth: "360px",
        padding: "12px 15px",
        borderRadius: "14px",
        fontFamily: '-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif',
        fontSize: "13px",
        lineHeight: "1.4",
        fontWeight: "600",
        boxShadow: "0 12px 36px rgba(15,23,42,.18)",
        backdropFilter: "blur(18px)",
        WebkitBackdropFilter: "blur(18px)",
        opacity: "0",
        transform: "translateY(8px)",
        transition: "opacity .18s ease, transform .18s ease",
        pointerEvents: "none"
      });
      document.documentElement.appendChild(host);
    }

    const styles = {
      ok: {background: "rgba(235,249,243,.96)", color: "#087a55", border: "1px solid rgba(15,159,110,.18)"},
      warn: {background: "rgba(255,247,237,.97)", color: "#a35400", border: "1px solid rgba(255,159,10,.22)"},
      bad: {background: "rgba(255,241,241,.97)", color: "#b42318", border: "1px solid rgba(255,59,48,.20)"},
      info: {background: "rgba(245,248,255,.97)", color: "#2457b8", border: "1px solid rgba(52,120,246,.18)"}
    };
    Object.assign(host.style, styles[kind] || styles.info);
    host.textContent = message;

    requestAnimationFrame(() => {
      host.style.opacity = "1";
      host.style.transform = "translateY(0)";
    });

    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      host.style.opacity = "0";
      host.style.transform = "translateY(8px)";
    }, duration);
  }

  function handleResult(result) {
    if (!result) return;
    if (result.status === "auto_synced") {
      showToast(`NextPlan · 已同步${result.label ? `：${result.label}` : ""}`, "ok");
    } else if (result.status === "queued") {
      const suffix = result.destructive ? "，需要确认删除" : "，请点扩展确认";
      showToast(`NextPlan · 已识别${result.label ? `：${result.label}` : " 1 项变更"}${suffix}`, result.destructive ? "warn" : "info", 5600);
    } else if (result.status === "queued_after_error") {
      showToast(`NextPlan · 自动同步失败，已放入待确认队列${result.error ? `：${result.error}` : ""}`, "bad", 6500);
    } else if (result.status === "informational") {
      showToast(`NextPlan · ${result.label || "无需变更"}`, "info");
    } else if (result.status === "no_change" && result.explicitNextPlan) {
      showToast("NextPlan · 这条指令提到了 NextPlan，但没有识别出可写入的状态变化。", "warn", 5600);
    } else if (result.status === "duplicate") {
      showToast("NextPlan · 这一轮已经处理过", "info", 2500);
    } else if (result.status === "needs_setup") {
      showToast("NextPlan Sync 尚未完成连接设置", "warn", 6000);
    } else if (result.status === "error") {
      showToast(`NextPlan Sync 出错：${result.error || "未知错误"}`, "bad", 6500);
    }
  }

  function collectLatestTurn() {
    const users = [...document.querySelectorAll('[data-message-author-role="user"]')];
    const assistants = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
    if (!users.length || !assistants.length) return;

    const userText = textOf(users[users.length - 1]);
    if (!userText) return;
    const assistantText = textOf(assistants[assistants.length - 1]);
    if (!assistantText) return;

    const fingerprint = stableKey(userText, users.length);
    if (seen.has(fingerprint)) return;
    seen.add(fingerprint);
    if (seen.size > 100) seen.delete(seen.values().next().value);

    // Explicit user intent only. Stores an unconfirmed, short summary in the
    // extension's review inbox; no automatic Jarvis private memory writes.
    if (/^(?:Jarvis[，,:：\s]*请?记住[：:\s]*|\/jarvis-remember\s+)/i.test(userText)) {
      chrome.runtime.sendMessage({
        type:"NEXTPLAN_JARVIS_EXPLICIT_MEMORY",
        turn:{userText:userText.slice(0,1600),url:location.href}
      }).then(result=>{
        if(result?.status==="queued_for_review")
          showToast("Jarvis · 已识别明确记忆指令，待你在 NextPlan 审核后保存","info",6200);
      }).catch(()=>{});
    }

    chrome.runtime.sendMessage({
      type: "NEXTPLAN_TURN",
      turn: {
        fingerprint,
        userText: userText.slice(0, 4000),
        assistantText: assistantText.slice(-4000),
        title: document.title || "",
        url: location.href
      }
    }).then(handleResult).catch(err => {
      showToast(`NextPlan Sync 无法处理这一轮：${err?.message || "连接失败"}`, "bad", 6500);
    });
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(collectLatestTurn, 2200);
  }

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, {subtree: true, childList: true, characterData: true});
  schedule();
})();
