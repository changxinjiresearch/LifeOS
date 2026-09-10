(() => {
  const seen = new Set();
  let timer = null;

  function textOf(el) {
    return (el?.innerText || el?.textContent || "").trim();
  }

  function stableKey(user, assistant) {
    const raw = `${location.pathname}|${user}|${assistant.slice(-1200)}`;
    let h = 2166136261;
    for (let i = 0; i < raw.length; i++) {
      h ^= raw.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(16);
  }

  function collectLatestTurn() {
    const users = [...document.querySelectorAll('[data-message-author-role="user"]')];
    const assistants = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
    if (!users.length) return;

    const userText = textOf(users[users.length - 1]);
    if (!userText) return;
    const assistantText = assistants.length ? textOf(assistants[assistants.length - 1]) : "";
    if (!assistantText) return;

    const fingerprint = stableKey(userText, assistantText);
    if (seen.has(fingerprint)) return;
    seen.add(fingerprint);
    if (seen.size > 100) seen.delete(seen.values().next().value);

    chrome.runtime.sendMessage({
      type: "NEXTPLAN_TURN",
      turn: {
        fingerprint,
        userText: userText.slice(0, 4000),
        assistantText: assistantText.slice(-2500),
        title: document.title || "",
        url: location.href
      }
    }).catch(() => {});
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(collectLatestTurn, 2200);
  }

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, {subtree: true, childList: true, characterData: true});
  schedule();
})();
