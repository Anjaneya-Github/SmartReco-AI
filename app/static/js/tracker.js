/**
 * tracker.js — SmartReco AI client-side event tracker
 * Captures: page_view, product_view, search, click, wishlist, rating
 * Buffers events locally → batch POST to /api/v1/events/batch
 * every 5 seconds OR when buffer reaches 20 events.
 * Never blocks the UI — all sends are fire-and-forget.
 */
(function () {
  'use strict';

  const BATCH_URL = '/api/v1/events/batch';
  const FLUSH_INTERVAL_MS = 5000;
  const MAX_BUFFER = 20;

  let _buffer = [];
  let _sessionId = sessionStorage.getItem('sr_session');
  if (!_sessionId) {
    _sessionId = 'sess-' + Math.random().toString(36).slice(2) + '-' + Date.now();
    sessionStorage.setItem('sr_session', _sessionId);
  }

  function _getToken() {
    return localStorage.getItem('access_token');
  }

  function _buildEvent(eventType, productId, extra) {
    const evt = {
      session_id: _sessionId,
      event_type: eventType,
      metadata: extra || {},
    };
    if (productId) evt.product_id = productId;
    if (eventType === 'search' && extra && extra.query) {
      evt.search_query = extra.query;
      delete evt.metadata.query;
    }
    return evt;
  }

  function _flush() {
    if (!_buffer.length) return;
    const token = _getToken();
    if (!token) { _buffer = []; return; }
    const payload = { events: _buffer.splice(0, MAX_BUFFER) };
    fetch(BATCH_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => { /* silent — never block UI */ });
  }

  function track(eventType, productId, extra) {
    const evt = _buildEvent(eventType, productId, extra);
    _buffer.push(evt);
    if (_buffer.length >= MAX_BUFFER) _flush();
  }

  // Auto-track page view
  track('view', null, { url: window.location.pathname, referrer: document.referrer });

  // Track time spent on unload
  let _pageStart = Date.now();
  window.addEventListener('beforeunload', function () {
    const spent = Math.round((Date.now() - _pageStart) / 1000);
    track('view', null, { time_spent_seconds: spent, url: window.location.pathname });
    _flush();
  });

  // Flush on interval
  setInterval(_flush, FLUSH_INTERVAL_MS);

  // Expose globally
  window._tracker = { track, flush: _flush };
})();
