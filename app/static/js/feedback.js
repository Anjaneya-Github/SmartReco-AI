/**
 * feedback.js — standalone feedback helpers (used by product_detail, etc.)
 */
(function () {
  'use strict';

  window.submitFeedback = async function (recommendationId, liked) {
    const token = localStorage.getItem('access_token');
    if (!token) { if (typeof showToast === 'function') showToast('Please login first.', 'warning'); return; }
    try {
      const r = await fetch('/api/v1/recommendations/' + recommendationId + '/feedback', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ liked }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Failed');
      if (typeof showToast === 'function')
        showToast(liked ? '👍 Marked as helpful!' : '👎 Feedback recorded', liked ? 'success' : 'secondary');
    } catch (e) {
      if (typeof showToast === 'function') showToast('Could not save feedback: ' + e.message, 'danger');
    }
  };
})();
