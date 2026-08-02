(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.EirosPip = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  async function activateKeepalivePip(options) {
    const opts = options || {};
    let hostError = '';

    if (typeof opts.requestHostPip === 'function') {
      try {
        if (await opts.requestHostPip()) {
          return { ok: true, mode: 'host-pip', error: '' };
        }
      } catch (error) {
        hostError = String(error && error.message || error || 'Host PiP unavailable');
      }
    }

    const videoReady = typeof opts.isVideoReady === 'function' && opts.isVideoReady();
    if (!videoReady) {
      return {
        ok: false,
        mode: 'none',
        error: hostError || 'Host PiP unavailable and video stream is not ready',
      };
    }

    if (typeof opts.requestNativeVideoPip === 'function') {
      try {
        if (await opts.requestNativeVideoPip()) {
          return { ok: true, mode: 'video-pip', error: '' };
        }
      } catch (error) {
        return {
          ok: false,
          mode: 'none',
          error: String(error && error.message || error || 'Native Video PiP unavailable'),
        };
      }
    }

    return {
      ok: false,
      mode: 'none',
      error: hostError || 'PiP unavailable',
    };
  }

  return { activateKeepalivePip };
});
