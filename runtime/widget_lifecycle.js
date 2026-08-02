(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.EirosWidgetLifecycle = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function createPulseLifecycle(options) {
    const opts = options || {};
    const target = opts.target;
    let storage = opts.storage;
    if (storage === undefined && target) {
      try {
        storage = target.localStorage;
      } catch (error) {
        storage = null;
      }
    }
    const projectId = String(opts.projectId || 'eiros-hub');
    const threadId = String(opts.threadId || 'first-contact');
    const sessionId = String(opts.sessionId || 'pulse');
    const onRetire = typeof opts.onRetire === 'function' ? opts.onRetire : function () {};
    const killKey = ['eiros-ui-kill', projectId, threadId].join(':');
    const listenerKillKey = ['eiros-wake-listener-kill', projectId, threadId].join(':');
    let retired = false;
    let destroyed = false;

    function retire(reason) {
      if (retired || destroyed) return;
      retired = true;
      onRetire(String(reason || 'retired'));
    }

    function onStorage(event) {
      if (!event) return;
      if (event.key === killKey) retire('global kill');
      if (event.key === listenerKillKey) retire('listener kill');
    }

    if (target && typeof target.addEventListener === 'function') {
      target.addEventListener('storage', onStorage);
    }

    return {
      killKey,
      listenerKillKey,
      isRetired: function () {
        return retired;
      },
      retireLegacy: function (keys) {
        if (!storage || typeof storage.setItem !== 'function') return;
        const marker = 'retired-by-' + sessionId;
        for (const key of Array.from(new Set(keys || []))) {
          if (!key) continue;
          try {
            storage.setItem(String(key), marker);
          } catch (error) {}
        }
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        if (target && typeof target.removeEventListener === 'function') {
          target.removeEventListener('storage', onStorage);
        }
      },
    };
  }

  return { createPulseLifecycle };
});
