(() => {
  const CFG_KEY = 'clo-v3-cfg';
  const WEB_DEFAULTS = {
    repo: 'changxinjiresearch/LifeOS',
    branch: 'main',
    path: 'state.json',
  };
  const nativeFetch = window.fetch.bind(window);
  const originalSetItem = Storage.prototype.setItem;
  let corePromise = null;

  function ensureDesktopConfig() {
    let cfg = {};
    try { cfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{}') || {}; } catch (_) {}
    // Keep Settings visually identical to Web while making the token a local sentinel.
    // The desktop state adapter below ignores repo/branch/path for data transport and
    // reads the canonical state from Local Core -> SQLite instead.
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
          const health = await nativeFetch(`${cfg.endpoint}/healthz`, { cache: 'no-store' });
          if (health.ok) return cfg;
        } catch (_) {}
        await sleep(250);
      }
      throw new Error(cfg.start_error || 'Local Core did not become ready');
    })();
    return corePromise;
  }

  async function readState() {
    const cfg = await coreConfig();
    const response = await nativeFetch(`${cfg.endpoint}/state`, {
      method: 'GET',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${cfg.token}`,
      },
    });
    if (!response.ok) {
      throw new Error(`Local Core ${response.status}`);
    }
    const state = await response.json();
    if (!state || !Array.isArray(state.projects)) {
      throw new Error('Invalid local state');
    }
    return state;
  }

  ensureDesktopConfig();
  const stateAdapter = Object.freeze({ kind: 'local', readState });
  window.__NEXTPLAN_STATE_ADAPTER__ = stateAdapter;
  window.__NEXTPLAN_DESKTOP__ = Object.freeze({ coreConfig, stateAdapter });
})();
