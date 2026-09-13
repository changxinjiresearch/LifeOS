(() => {
  if (window.__NEXTPLAN_LOCAL_V012__) return;
  window.__NEXTPLAN_LOCAL_V012__ = true;

  const seen = new Set();
  let timer = null;
  let toastTimer = null;

  function textOf(el) {
    return (el?.innerText || el?.textContent || "").trim();
  }

  function normalizeCommandText(text) {
    return String(text || "").replace(/next\s*plan\s*[：:]\s*/gi, "NextPlan ");
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

  function toast(message, kind = "info", duration = 4200) {
    let host = document.getElementById("nextplan-local-toast");
    if (!host) {
      host = document.createElement("div");
      host.id = "nextplan-local-toast";
      Object.assign(host.style, {
        position: "fixed", right: "22px", bottom: "22px", zIndex: "2147483647",
        maxWidth: "360px", padding: "12px 15px", borderRadius: "14px",
        fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
        fontSize: "13px", lineHeight: "1.4", fontWeight: "600",
        boxShadow: "0 12px 36px rgba(15,23,42,.18)", opacity: "0",
        transform: "translateY(8px)", transition: "opacity .18s ease, transform .18s ease",
        pointerEvents: "none"
      });
      document.documentElement.appendChild(host);
    }
    const styles = {
      ok: {background: "rgba(235,249,243,.97)", color: "#087a55"},
      warn: {background: "rgba(255,247,237,.97)", color: "#a35400"},
      bad: {background: "rgba(255,241,241,.97)", color: "#b42318"},
      info: {background: "rgba(245,248,255,.97)", color: "#2457b8"}
    };
    Object.assign(host.style, styles[kind] || styles.info);
    host.textContent = message;
    requestAnimationFrame(() => { host.style.opacity = "1"; host.style.transform = "translateY(0)"; });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { host.style.opacity = "0"; host.style.transform = "translateY(8px)"; }, duration);
  }

  function handle(result) {
    if (!result) return;
    if (result.status === "auto_synced") toast(`NextPlan · Synced${result.label ? `: ${result.label}` : ""}`, "ok");
    else if (result.status === "queued") toast(`NextPlan · Change detected${result.label ? `: ${result.label}` : ""}. Open the extension to confirm.`, "info", 5600);
    else if (result.status === "informational") toast(`NextPlan · ${result.label || "No change needed"}`, "info");
    else if (result.status === "no_change") toast("NextPlan · No executable change detected", "warn", 5200);
    else if (result.status === "needs_desktop") toast(result.error || "Open NextPlan Desktop to connect.", "warn", 6000);
    else if (result.status === "error") toast(`NextPlan Local: ${result.error || "Connection failed"}`, "bad", 6500);
  }

  function collectLatestTurn() {
    const users = [...document.querySelectorAll('[data-message-author-role="user"]')];
    const assistants = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
    if (!users.length || !assistants.length) return;
    const originalUserText = textOf(users[users.length - 1]);
    const assistantText = textOf(assistants[assistants.length - 1]);
    if (!originalUserText || !assistantText) return;
    const fingerprint = stableKey(originalUserText, users.length);
    if (seen.has(fingerprint)) return;
    seen.add(fingerprint);
    if (seen.size > 100) seen.delete(seen.values().next().value);
    chrome.runtime.sendMessage({
      type: "NEXTPLAN_TURN",
      turn: {
        fingerprint,
        userText: normalizeCommandText(originalUserText).slice(0, 4000),
        assistantText: assistantText.slice(-4000),
        title: document.title || "ChatGPT",
        url: location.href
      }
    }).then(handle).catch(err => toast(`NextPlan Local: ${err?.message || "Connection failed"}`, "bad", 6500));
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(collectLatestTurn, 2200);
  }

  new MutationObserver(schedule).observe(document.documentElement, {subtree: true, childList: true, characterData: true});
  schedule();
})();
