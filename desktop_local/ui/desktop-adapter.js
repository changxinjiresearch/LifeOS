(() => {
  const CFG_KEY = 'clo-v3-cfg';
  const CAL_COMPAT_PREFIX = '__NP_CAL_V1__:';
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

  function decodeCompatCalendar(deadline) {
    const raw = String(deadline?.title || '');
    if (!raw.startsWith(CAL_COMPAT_PREFIX)) return null;
    try {
      const meta = JSON.parse(decodeURIComponent(raw.slice(CAL_COMPAT_PREFIX.length)));
      const projectId = String(deadline.project_id || '') === 'calendar' ? null : (deadline.project_id || null);
      return {
        id: deadline.id || `calendar-compat-${String(deadline.date || '')}-${String(meta.title || 'event')}`,
        title: String(meta.title || 'Event'),
        date: deadline.date || deadline.due || '',
        time: String(meta.time || ''),
        timezone: String(meta.timezone || ''),
        kind: String(meta.kind || 'event'),
        category: String(meta.category || '其他'),
        project_id: projectId,
        task_id: deadline.task_id || null,
        compatibility_source: 'deadline-v1'
      };
    } catch (_) {
      return null;
    }
  }

  function adaptCompatibilityState(state) {
    const nativeEvents = Array.isArray(state.calendar_events) ? state.calendar_events.slice() : [];
    const deadlines = [];
    const compatEvents = [];
    for (const deadline of (Array.isArray(state.deadlines) ? state.deadlines : [])) {
      const event = decodeCompatCalendar(deadline);
      if (event) compatEvents.push(event);
      else deadlines.push(deadline);
    }
    const ids = new Set(nativeEvents.map(event => String(event?.id || '')).filter(Boolean));
    for (const event of compatEvents) {
      const id = String(event.id || '');
      if (id && ids.has(id)) continue;
      nativeEvents.push(event);
      if (id) ids.add(id);
    }
    state.deadlines = deadlines;
    state.calendar_events = nativeEvents;
    return state;
  }

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
    return adaptCompatibilityState(state);
  }

  ensureDesktopConfig();
  const stateAdapter = Object.freeze({ kind: 'local', readState });
  window.__NEXTPLAN_STATE_ADAPTER__ = stateAdapter;
  window.__NEXTPLAN_DESKTOP__ = Object.freeze({ coreConfig, stateAdapter });
})();
