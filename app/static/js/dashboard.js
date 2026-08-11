/**
 * dashboard.js — loads and renders the SmartReco AI user dashboard.
 * Reads from GET /api/v1/dashboard (read-only, never regenerates).
 */
(function () {
  'use strict';

  const token = localStorage.getItem('access_token');
  if (!token) { window.location.replace('/login'); return; }

  let _recoId = null;

  const CONFIDENCE_COLORS = { high: 'success', medium: 'warning', low: 'danger', none: 'secondary' };

  function tag(text, cls) {
    return `<span class="badge bg-${cls || 'secondary'} me-1">${text}</span>`;
  }

  function el(id) { return document.getElementById(id); }

  async function load() {
    try {
      const r = await fetch('/api/v1/dashboard', { headers: { 'Authorization': 'Bearer ' + token } });
      if (r.status === 401) { window.location.replace('/login'); return; }
      const d = await r.json();
      render(d);
    } catch (e) {
      if (el('welcome-sub')) el('welcome-sub').textContent = 'Failed to load dashboard. Please refresh.';
    }
  }

  function render(d) {
    // Welcome
    const name = d.user.full_name || d.user.email || 'there';
    el('welcome-name').textContent = 'Welcome back, ' + name + '!';
    el('welcome-sub').textContent = d.has_recommendation
      ? 'Your AI-powered recommendations are ready'
      : 'Your personalized learning journey awaits';

    // Quick stats
    if (el('stat-events')) el('stat-events').textContent = d.total_events_analysed || 0;
    if (el('stat-engagement')) el('stat-engagement').textContent = Math.round((d.engagement_score||0)*100) + '%';
    if (el('stat-confidence')) el('stat-confidence').textContent = d.has_recommendation ? Math.round(d.confidence_score*100)+'%' : '—';
    if (el('stat-level')) el('stat-level').textContent = (d.learning_level||'unknown').charAt(0).toUpperCase() + (d.learning_level||'unknown').slice(1);

    // Cache badge
    const cb = el('cache-badge');
    if (cb) {
      cb.textContent = d.cache_hit ? '⚡ Cached' : '🔄 Live';
      cb.className = 'badge bg-' + (d.cache_hit ? 'info' : 'dark') + ' border';
    }

    // Engagement bar
    const score = d.engagement_score || 0;
    const bar = el('eng-bar');
    if (bar) { bar.style.width = (score * 100).toFixed(0) + '%'; bar.textContent = ''; }
    if (el('eng-score')) el('eng-score').textContent = (score * 100).toFixed(0) + '% engagement';

    // Learning level
    if (el('learn-level')) el('learn-level').textContent = d.learning_level || 'unknown';

    // Top categories
    if (el('top-cats'))
      el('top-cats').innerHTML = (d.primary_categories || []).slice(0, 5)
        .map(c => tag(c, 'primary')).join('') || '<span class="text-muted small">None yet</span>';

    // Top tags
    if (el('top-tags'))
      el('top-tags').innerHTML = (d.favorite_tags || []).slice(0, 6)
        .map(t => tag(t, 'dark border text-muted')).join('') || '<span class="text-muted small">None yet</span>';

    // Recent summary
    if (el('recent-summary')) el('recent-summary').textContent = d.recent_activity_summary;

    // Recommendation story
    if (el('reco-summary')) el('reco-summary').textContent = d.recommendation_summary || 'No recommendation yet. Interact with some courses first!';
    if (el('reco-reasoning')) el('reco-reasoning').textContent = d.recommendation_reasoning || '';

    // Confidence badge
    const confBadge = el('confidence-badge');
    if (confBadge) {
      const label = d.confidence_label || 'none';
      confBadge.textContent = label.toUpperCase() + ' ' + (d.confidence_score * 100 || 0).toFixed(0) + '%';
      confBadge.className = 'badge bg-' + (CONFIDENCE_COLORS[label] || 'secondary');
    }

    // Timestamps
    if (el('reco-time') && d.generated_at)
      el('reco-time').textContent = 'Generated: ' + new Date(d.generated_at).toLocaleString();

    // AI model
    if (el('ai-model')) el('ai-model').textContent = d.ai_model || '—';

    // Evidence
    if (el('evidence-cats'))
      el('evidence-cats').textContent = [...(d.evidence_categories || []), ...(d.evidence_searches || [])].join(', ') || 'none';

    // Feedback
    _recoId = d.recommendation_id;
    if (_recoId && el('feedback-area')) el('feedback-area').style.display = '';

    // Products grid
    renderProducts(d.recommended_products || []);

    // Searches
    if (el('search-tags'))
      el('search-tags').innerHTML = (d.top_searches || []).slice(0, 8).map(s =>
        `<span class="badge bg-dark border text-info" style="cursor:pointer" onclick="searchCourse('${s}')">${s}</span>`
      ).join('') || '<span class="text-muted small">No searches yet.</span>';

    // Timeline
    renderTimeline(d.recent_activity || []);
  }

  function renderProducts(items) {
    const g = el('products-grid');
    if (!g) return;
    if (!items.length) {
      g.innerHTML = `<div class="col-12 text-center py-5 text-muted">
        <i class="bi bi-search" style="font-size:2rem"></i>
        <p class="mt-2">Browse some courses to get personalized recommendations</p>
        <a href="/products" class="btn btn-outline-primary btn-sm">Explore Courses</a>
      </div>`;
      return;
    }
    const diffColors = { beginner: 'success', intermediate: 'warning', advanced: 'danger' };
    g.innerHTML = items.map((p, i) => {
      const priceHtml = (!p.price || p.price === 0)
        ? '<span class="price-tag price-free">Free</span>'
        : `<span class="price-tag price-paid">$${p.price}</span>`;
      const stars = '★'.repeat(4) + '☆';
      return `
      <div class="col-md-6 col-xl-4">
        <div class="card course-card h-100" onclick="trackClick('${p.product_id}')">
          <div class="card-body pb-2">
            <div class="d-flex justify-content-between align-items-start mb-2">
              <span class="badge bg-primary bg-opacity-75 rounded-pill">#${i + 1} Pick</span>
              ${p.difficulty ? `<span class="badge bg-${diffColors[p.difficulty] || 'secondary'}">${p.difficulty}</span>` : ''}
            </div>
            <h6 class="fw-bold mb-2" style="min-height:2.4em;line-height:1.2">${p.title}</h6>
            ${p.category ? `<div class="mb-2"><span class="badge bg-dark text-info border border-info border-opacity-25">${p.category}</span></div>` : ''}
            <div class="d-flex flex-wrap gap-1 mb-2">
              ${(p.tags || []).slice(0, 3).map(t => `<span class="badge bg-secondary bg-opacity-50 text-muted">${t}</span>`).join('')}
            </div>
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="text-warning small">${stars}</span>
              <span class="text-muted small">(${Math.floor(Math.random()*200+50)})</span>
            </div>
          </div>
          <div class="card-footer bg-transparent border-top border-secondary d-flex justify-content-between align-items-center">
            ${priceHtml}
            <div class="d-flex gap-2">
              <button class="btn btn-sm btn-outline-secondary cart-btn" onclick="event.stopPropagation();addToCart('${p.product_id}','${p.title.replace(/'/g,'')}')" title="Add to Cart">
                <i class="bi bi-cart-plus"></i>
              </button>
              <a href="/products/${p.product_id}" class="btn btn-sm btn-primary cart-btn" onclick="event.stopPropagation()">
                <i class="bi bi-play-circle me-1"></i>Enroll
              </a>
            </div>
          </div>
        </div>
      </div>`;
    }).join('');
  }

  function renderTimeline(events) {
    const list = el('timeline-list');
    if (!list) return;
    if (!events.length) {
      list.innerHTML = '<li class="list-group-item text-muted small">No recent activity.</li>';
      return;
    }
    const icons = { view: 'bi-eye', click: 'bi-cursor', search: 'bi-search', purchase: 'bi-bag-check', wishlist: 'bi-heart', rating: 'bi-star', share: 'bi-share', impression: 'bi-eye-slash' };
    list.innerHTML = events.map(e => `
      <li class="list-group-item d-flex align-items-center gap-2 py-2">
        <i class="bi ${icons[e.event_type] || 'bi-circle'} text-info"></i>
        <div class="flex-grow-1">
          <span class="small">${e.product_title || e.search_query || e.event_type}</span><br/>
          <span class="text-muted" style="font-size:.7rem">${new Date(e.created_at).toLocaleString()}</span>
        </div>
        <span class="badge bg-dark text-muted">${e.event_type}</span>
      </li>`).join('');
  }

  window.trackClick = function (productId) {
    if (window._tracker) window._tracker.track('click', productId);
  };

  window.addToCart = function (productId, title) {
    if (window._tracker) window._tracker.track('wishlist', productId);
    if (typeof showToast === 'function') showToast('Added to cart: ' + title, 'success');
  };

  window.searchCourse = function (query) {
    if (window._tracker) window._tracker.track('search', null, { query });
    window.location = '/products';
  };

  window.sendFeedback = async function (liked) {
    if (!_recoId) return;
    try {
      const r = await fetch('/api/v1/recommendations/' + _recoId + '/feedback', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ liked }),
      });
      if (!r.ok) throw new Error('failed');
      if (typeof showToast === 'function') showToast('Feedback recorded — thank you!', 'success');
      el('feedback-area').style.display = 'none';
    } catch (e) {
      if (typeof showToast === 'function') showToast('Could not save feedback', 'danger');
    }
  };

  load();
})();
