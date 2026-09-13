(() => {
  const CFG_KEY = 'clo-v3-cfg';
  const WEB_DEFAULTS = {
    repo: 'changxinjiresearch/LifeOS',
    branch: 'main',
    path: 'state.json',
  };
  const originalFetch = window.fetch.bind(window);
  const originalSetItem = Storage.prototype.setItem;
  let corePromise = null;

  function ensureDesktopConfig() {
    let cfg = {};
    try { cfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{}') || {}; } catch (_) {}
    // Keep all user-visible Settings defaults exactly the same as the canonical Web UI.
    // The token is a masked local sentinel only; network access is transparently routed
    // to Local Core below, so desktop canonical state remains SQLite-local.
    cfg.repo = cfg.repo || WEB_DEFAULTS.repo;
    cfg.branch = cfg.branch || WEB_DEFAULTS.branch;
    cfg.path = cfg.path || WEB_DEFAULTS.path;
    cfg.token = 'nextplan-local';
    originalSetItem.call(localStorage, CFG_KEY, JSON.stringify(cfg));
  }

  Storage.prototype.setItem = function (key, value) {
    if (key === CFG_KEY) {
      try {
        const cfg = JSON.parse(String(value || '{}')) || {};
        cfg.repo = cfg.repo || WEB_DEFAULTS.repo;
        cfg.branch = cfg.branch || WEB_DEFAULTS.branch;
        cfg.path = cfg.path || WEB_DEFAULTS.path;
        cfg.token = 'nextplan-local';
        value = JSON.stringify(cfg);
      } catch (_) {}
    }
    return originalSetItem.call(this, key, value);
  };

  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

  async function coreConfig() {
    if (corePromise) return corePromise;
    corePromise = (async () => {
      if (!window.__TAURI__?.core?.invoke) {
        throw new Error('NextPlan desktop runtime is unavailable');
      }
      const cfg = await window.__TAURI__.core.invoke('core_config');
      if (!cfg?.endpoint || !cfg?.token) throw new Error('Local Core configuration is incomplete');
      for (let i = 0; i < 48; i += 1) {
        try {
          const health = await originalFetch(`${cfg.endpoint}/healthz`, { cache: 'no-store' });
          if (health.ok) return cfg;
        } catch (_) {}
        await sleep(250);
      }
      throw new Error(cfg.start_error || 'Local Core did not become ready');
    })();
    return corePromise;
  }

  function utf8Base64(text) {
    const bytes = new TextEncoder().encode(text);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  window.fetch = async function (input, init = {}) {
    const url = typeof input === 'string' ? input : String(input?.url || '');
    if (url.startsWith('https://api.github.com/repos/') && url.includes('/contents/')) {
      try {
        const cfg = await coreConfig();
        const response = await originalFetch(`${cfg.endpoint}/state`, {
          method: 'GET',
          cache: 'no-store',
          headers: {
            Accept: 'application/json',
            Authorization: `Bearer ${cfg.token}`,
          },
        });
        const text = await response.text();
        if (!response.ok) {
          return new Response(text || JSON.stringify({ message: `Local Core ${response.status}` }), {
            status: response.status,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        const state = JSON.parse(text);
        return new Response(JSON.stringify({ content: utf8Base64(JSON.stringify(state)) }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      } catch (error) {
        return new Response(JSON.stringify({ message: String(error?.message || error) }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    }
    return originalFetch(input, init);
  };

  ensureDesktopConfig();
  window.__NEXTPLAN_DESKTOP__ = { coreConfig };
})();
