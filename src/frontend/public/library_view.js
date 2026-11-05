// src/frontend/public/library_view.js
// Folio Library Directory & Search View (Milestone 7 — IR Engine & Telemetry Integration)

import { api } from '../core/api.js';
import { navigate } from '../core/router.js';
import { renderPagination, renderError, renderEmpty } from '../core/ui.js';

/**
 * Safely parses and renders a highlighted search snippet without raw HTML or attribute injection.
 * Only <em class="search-highlight"> elements and text nodes are permitted.
 */
export function renderSafeSnippet(snippetHtml, fallbackSummary = '') {
  const container = document.createElement('p');
  container.className = 'doc-row-summary';

  const raw = snippetHtml || fallbackSummary || '';
  if (!raw) return container;

  // Plain text fallback if no HTML tags are present
  if (!snippetHtml || !/<[a-z][\s\S]*>/i.test(snippetHtml)) {
    container.textContent = raw;
    return container;
  }

  // Parse in an isolated HTML document
  const parser = new DOMParser();
  const parsedDoc = parser.parseFromString(`<body>${snippetHtml}</body>`, 'text/html');

  function sanitizeNode(srcNode, targetNode) {
    for (const child of Array.from(srcNode.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        targetNode.appendChild(document.createTextNode(child.textContent));
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        const tagName = child.tagName.toLowerCase();
        if (tagName === 'em' || tagName === 'mark') {
          const em = document.createElement('em');
          em.className = 'search-highlight';
          sanitizeNode(child, em);
          targetNode.appendChild(em);
        } else {
          // Flatten unknown/unsafe tags into text content
          sanitizeNode(child, targetNode);
        }
      }
    }
  }

  sanitizeNode(parsedDoc.body, container);
  return container;
}

export async function renderLibrary(container, routeContext) {
  const { query, signal } = routeContext;

  // Extract query parameters from URL hash
  const q = (query.get('q') || '').trim();
  const mode = (query.get('mode') || 'bm25').toLowerCase();
  const categoryId = query.get('category_id') || '';
  const tagIds = query.get('tag_ids') || '';
  const dateFrom = query.get('date_from') || '';
  const dateTo = query.get('date_to') || '';
  const sort = query.get('sort') || 'newest';
  const page = Math.max(1, parseInt(query.get('page') || '1', 10));
  const searchContextToken = query.get('search_context_token') || '';

  const isSearchMode = Boolean(q);
  document.title = isSearchMode ? `Search: "${q}" — Folio` : 'Library Catalog — Folio';

  const hasActiveFilters = Boolean(
    q ||
    (isSearchMode && mode !== 'bm25') ||
    categoryId ||
    tagIds ||
    dateFrom ||
    dateTo ||
    (!isSearchMode && sort !== 'newest')
  );

  container.innerHTML = `
    <div class="public-page library-layout">
      <!-- Mobile Filter Toggle Bar (Viewport <= 860px) -->
      <div class="mobile-filter-bar">
        <button type="button" class="btn btn-secondary btn-sm mobile-filter-btn" id="mobileFilterToggleBtn" aria-expanded="false" aria-controls="librarySidebar">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="4" y1="21" x2="4" y2="14"></line>
            <line x1="4" y1="10" x2="4" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="12"></line>
            <line x1="12" y1="8" x2="12" y2="3"></line>
            <line x1="20" y1="21" x2="20" y2="16"></line>
            <line x1="20" y1="12" x2="20" y2="3"></line>
            <line x1="1" y1="14" x2="7" y2="14"></line>
            <line x1="9" y1="8" x2="15" y2="8"></line>
            <line x1="17" y1="16" x2="23" y2="16"></line>
          </svg>
          <span>Collections & Filters</span>
          ${hasActiveFilters ? '<span class="filter-active-indicator" aria-label="Active filters applied">●</span>' : ''}
        </button>
      </div>

      <!-- Sidebar Categories & Taxonomy Filter (~220px) -->
      <aside class="library-sidebar" id="librarySidebar" aria-label="Library Collections and Filters">
        <h3 class="sidebar-title" id="collectionsHeader">Collections</h3>
        <div id="categoryFilterList" class="category-list" role="navigation" aria-labelledby="collectionsHeader">
          <div class="spinner" style="margin: 1rem auto; display: block;" aria-label="Loading collections..."></div>
        </div>

        <hr style="border: none; border-top: 1px solid var(--color-border); margin: 1.25rem 0;" />

        <div class="sidebar-collapsible-section">
          <button type="button" class="sidebar-toggle-btn" id="toggleDateFilterBtn" aria-expanded="${Boolean(dateFrom || dateTo)}" aria-controls="dateFilterPanel">
            <span class="sidebar-title" style="margin: 0;">Date Filter</span>
            <span class="toggle-icon">${(dateFrom || dateTo) ? '▲' : '▼'}</span>
          </button>
          <div id="dateFilterPanel" class="collapsible-panel" style="${(dateFrom || dateTo) ? 'display: block;' : 'display: none;'}">
            <div class="field" style="margin-top: 0.5rem; margin-bottom: 0.75rem;">
              <label class="label" for="filterDateFrom">Published From</label>
              <input class="input" type="date" id="filterDateFrom" value="${escapeAttr(dateFrom)}" aria-describedby="dateValidationError" />
            </div>
            <div class="field" style="margin-bottom: 0.75rem;">
              <label class="label" for="filterDateTo">Published To</label>
              <input class="input" type="date" id="filterDateTo" value="${escapeAttr(dateTo)}" aria-describedby="dateValidationError" />
            </div>
            <div id="dateValidationError" class="field-error-text" style="display: none; margin-bottom: 0.5rem;" role="alert"></div>
            <button type="button" class="btn btn-secondary btn-sm" id="applyDateFilterBtn" style="width: 100%;">Apply Date</button>
          </div>
        </div>

        ${hasActiveFilters ? `
          <button type="button" class="btn btn-secondary btn-sm" id="clearAllFiltersBtn" style="width: 100%; margin-top: 1rem;">Reset All Filters</button>
        ` : ''}
      </aside>

      <!-- Main Catalog Results Area -->
      <section class="library-main" role="region" aria-label="Library Catalog and Search Results">
        <div class="library-toolbar">
          <div class="search-bar-wrapper">
            <label for="librarySearchInput" class="visually-hidden">Search library documents</label>
            <input type="search" id="librarySearchInput" class="input library-search-input"
                   placeholder="Search 100+ research documents by concept, title, or query..."
                   value="${escapeAttr(q)}" aria-label="Search documents" maxlength="200" />
            <button type="button" class="btn btn-primary" id="librarySearchBtn">Search</button>
          </div>

          <div class="search-controls-wrapper">
            <!-- Retrieval Mode Selector -->
            <div class="mode-wrapper">
              <label for="libraryModeSelect" class="mode-label">Mode:</label>
              <select id="libraryModeSelect" class="select mode-select" aria-label="Information retrieval mode">
                <option value="bm25" ${mode === 'bm25' ? 'selected' : ''}>BM25 (Keyword)</option>
                <option value="semantic" ${mode === 'semantic' ? 'selected' : ''}>Semantic (Vector)</option>
                <option value="hybrid" ${mode === 'hybrid' ? 'selected' : ''}>Hybrid (RRF)</option>
              </select>
            </div>

            <!-- Sort Selector (active in browse mode) -->
            <div class="sort-wrapper" style="${isSearchMode ? 'display: none;' : 'display: flex;'}">
              <label for="librarySortSelect" class="sort-label">Sort:</label>
              <select id="librarySortSelect" class="select sort-select" aria-label="Sort documents" ${isSearchMode ? 'disabled' : ''}>
                <option value="newest" ${sort === 'newest' ? 'selected' : ''}>Newest First</option>
                <option value="oldest" ${sort === 'oldest' ? 'selected' : ''}>Oldest First</option>
                <option value="title" ${sort === 'title' ? 'selected' : ''}>Title (A–Z)</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Active Filter Chips Bar -->
        <div id="activeFiltersBar" class="active-filters-bar" style="${hasActiveFilters ? 'display: flex;' : 'display: none;'}" aria-label="Active filters"></div>

        <!-- Degraded Engine Notice Banner -->
        <div id="degradedEngineBanner" style="display: none;"></div>

        <!-- Results Counter & Telemetry Stats Header -->
        <div class="library-stats-header" aria-live="polite">
          <span id="resultsCountText" class="results-count-text">Loading catalog...</span>
          <div id="searchTelemetryBar" class="search-telemetry-bar" style="display: none;"></div>
        </div>

        <!-- Document List Area -->
        <div id="documentsListContainer" class="documents-list" aria-live="polite">
          <div style="text-align: center; padding: 3rem;"><span class="spinner" aria-label="Loading documents"></span></div>
        </div>

        <!-- Catalog Pagination -->
        <div id="libraryPaginationContainer"></div>
      </section>
    </div>
  `;

  // Helper to push new query state to URL hash
  function updateRoute(updates) {
    const params = new URLSearchParams(query);
    Object.entries(updates).forEach(([k, v]) => {
      if (v !== null && v !== undefined && v !== '') {
        params.set(k, String(v));
      } else {
        params.delete(k);
      }
    });

    // Reset page to 1 and clear search context whenever query/filter changes
    if (!('page' in updates)) {
      params.delete('page');
      params.delete('search_context_token');
    }

    const queryString = params.toString();
    const newHash = queryString ? `/library?${queryString}` : '/library';
    navigate(newHash);
  }

  // Hook up filter inputs and buttons
  const searchInput = container.querySelector('#librarySearchInput');
  const searchBtn = container.querySelector('#librarySearchBtn');
  const modeSelect = container.querySelector('#libraryModeSelect');
  const sortSelect = container.querySelector('#librarySortSelect');
  const dateFromInput = container.querySelector('#filterDateFrom');
  const dateToInput = container.querySelector('#filterDateTo');
  const dateErrorEl = container.querySelector('#dateValidationError');
  const applyDateBtn = container.querySelector('#applyDateFilterBtn');
  const clearFiltersBtn = container.querySelector('#clearAllFiltersBtn');
  const toggleDateBtn = container.querySelector('#toggleDateFilterBtn');
  const datePanel = container.querySelector('#dateFilterPanel');
  const mobileFilterBtn = container.querySelector('#mobileFilterToggleBtn');
  const librarySidebar = container.querySelector('#librarySidebar');

  // Mobile Filter Drawer Toggle
  if (mobileFilterBtn && librarySidebar) {
    mobileFilterBtn.onclick = () => {
      const isExpanded = librarySidebar.classList.toggle('open');
      mobileFilterBtn.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    };
  }

  if (toggleDateBtn && datePanel) {
    toggleDateBtn.onclick = () => {
      const isHidden = datePanel.style.display === 'none';
      datePanel.style.display = isHidden ? 'block' : 'none';
      toggleDateBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
      const icon = toggleDateBtn.querySelector('.toggle-icon');
      if (icon) icon.textContent = isHidden ? '▲' : '▼';
    };
  }

  function handleSearchSubmit() {
    const rawVal = searchInput.value.trim();
    if (rawVal.length > 200) {
      if (dateErrorEl) {
        dateErrorEl.textContent = 'Search query exceeds maximum allowed length of 200 characters.';
        dateErrorEl.style.display = 'block';
      }
      return;
    }
    const updates = { q: rawVal };
    if (modeSelect.value && modeSelect.value !== 'bm25') {
      updates.mode = modeSelect.value;
    } else {
      updates.mode = null;
    }
    updateRoute(updates);
  }

  searchBtn.onclick = handleSearchSubmit;
  searchInput.onkeydown = (e) => {
    if (e.key === 'Enter') handleSearchSubmit();
  };

  modeSelect.onchange = () => {
    // Changing retrieval mode updates route
    updateRoute({ mode: modeSelect.value !== 'bm25' ? modeSelect.value : null });
  };

  sortSelect.onchange = () => updateRoute({ sort: sortSelect.value });

  applyDateBtn.onclick = () => {
    const fromVal = dateFromInput.value;
    const toVal = dateToInput.value;
    if (fromVal && toVal && fromVal > toVal) {
      if (dateErrorEl) {
        dateErrorEl.textContent = 'Start date must be earlier than or equal to end date.';
        dateErrorEl.style.display = 'block';
      }
      return;
    }
    if (dateErrorEl) dateErrorEl.style.display = 'none';
    updateRoute({ date_from: fromVal, date_to: toVal });
  };

  if (clearFiltersBtn) {
    clearFiltersBtn.onclick = () => navigate('/library');
  }

  // State for rendering active filter chips
  let categoriesList = [];

  // 1. Fetch categories for sidebar
  try {
    const catData = await api('/categories', { query: { page: 1, page_size: 50 }, signal });
    categoriesList = catData.items || [];
    const catContainer = container.querySelector('#categoryFilterList');
    if (catContainer) {
      catContainer.innerHTML = '';

      const allCatBtn = document.createElement('button');
      allCatBtn.type = 'button';
      allCatBtn.className = `category-pill ${!categoryId ? 'active' : ''}`;
      allCatBtn.textContent = 'All Collections';
      allCatBtn.onclick = () => updateRoute({ category_id: '' });
      catContainer.appendChild(allCatBtn);

      categoriesList.forEach((cat) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `category-pill ${categoryId === cat.id ? 'active' : ''}`;
        btn.innerHTML = `<span>${escapeText(cat.name)}</span> <span class="cat-count">${cat.published_document_count}</span>`;
        btn.onclick = () => updateRoute({ category_id: cat.id });
        catContainer.appendChild(btn);
      });
    }
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.warn('Failed to load categories list:', err);
    const catContainer = container.querySelector('#categoryFilterList');
    if (catContainer) {
      catContainer.textContent = 'Collections are temporarily unavailable.';
    }
  }

  // Populate active filter chips bar
  const activeFiltersBar = container.querySelector('#activeFiltersBar');
  if (activeFiltersBar && hasActiveFilters) {
    activeFiltersBar.innerHTML = '';

    if (q) {
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Query: "<strong>${escapeText(q)}</strong>"</span> <button type="button" class="chip-remove-btn" title="Remove query filter" aria-label="Remove search query">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ q: '' });
      activeFiltersBar.appendChild(chip);
    }

    if (isSearchMode && mode !== 'bm25') {
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Mode: <strong>${escapeText(mode.toUpperCase())}</strong></span> <button type="button" class="chip-remove-btn" title="Reset to standard BM25" aria-label="Reset to BM25 mode">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ mode: 'bm25' });
      activeFiltersBar.appendChild(chip);
    }

    if (categoryId) {
      const matchedCat = categoriesList.find(c => c.id === categoryId);
      const catLabel = matchedCat ? matchedCat.name : 'Category';
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Collection: <strong>${escapeText(catLabel)}</strong></span> <button type="button" class="chip-remove-btn" title="Remove collection filter" aria-label="Remove collection filter">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ category_id: '' });
      activeFiltersBar.appendChild(chip);
    }

    if (tagIds) {
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Tag filter active</span> <button type="button" class="chip-remove-btn" title="Remove tag filter" aria-label="Remove tag filter">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ tag_ids: '' });
      activeFiltersBar.appendChild(chip);
    }

    if (dateFrom || dateTo) {
      const dateLabel = `${dateFrom || 'Any'} → ${dateTo || 'Present'}`;
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Date: <strong>${escapeText(dateLabel)}</strong></span> <button type="button" class="chip-remove-btn" title="Remove date filter" aria-label="Remove date filter">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ date_from: '', date_to: '' });
      activeFiltersBar.appendChild(chip);
    }

    const resetAllChip = document.createElement('button');
    resetAllChip.type = 'button';
    resetAllChip.className = 'btn btn-secondary btn-sm';
    resetAllChip.style.padding = '2px 8px';
    resetAllChip.style.fontSize = '0.75rem';
    resetAllChip.textContent = 'Clear All';
    resetAllChip.onclick = () => navigate('/library');
    activeFiltersBar.appendChild(resetAllChip);
  }

  // 2. Fetch documents (Search API vs Browse Catalog)
  try {
    let docResponse;

    if (isSearchMode) {
      // Connect to Folio Search API (/api/v1/search)
      const searchQueryParams = {
        q,
        mode,
        page,
        page_size: 15,
        category_id: categoryId || undefined,
        tag_ids: tagIds || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      };

      // Server requires search_context_token from page 2 onwards
      if (page > 1 && searchContextToken) {
        searchQueryParams.search_context_token = searchContextToken;
      }

      try {
        docResponse = await api('/search', { query: searchQueryParams, signal });
      } catch (err) {
        // If context expired (HTTP 410) or parameter mismatch on page > 1, recover by restarting from page 1
        if (page > 1 && (err.status === 410 || err.code === 'SEARCH_CONTEXT_EXPIRED' || err.code === 'CONTEXT_PARAMETER_MISMATCH' || err.status === 400)) {
          console.warn('Search context token expired or mismatched. Restarting search from page 1.');
          updateRoute({ page: 1, search_context_token: null });
          return;
        }
        throw err;
      }
    } else {
      // Browse Catalog (/api/v1/documents) - Unfiltered or taxonomy browse without search query
      docResponse = await api('/documents', {
        query: {
          category_id: categoryId || undefined,
          tag_ids: tagIds || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          sort,
          page,
          page_size: 15,
        },
        signal,
      });
    }

    const docsList = container.querySelector('#documentsListContainer');
    const statsText = container.querySelector('#resultsCountText');
    const telemetryBar = container.querySelector('#searchTelemetryBar');
    const paginationEl = container.querySelector('#libraryPaginationContainer');
    const degradedBanner = container.querySelector('#degradedEngineBanner');

    // Display Degraded Engine Alert Banner if applicable
    if (isSearchMode && docResponse.is_degraded) {
      degradedBanner.style.display = 'block';
      degradedBanner.innerHTML = `
        <div class="degraded-engine-banner" role="status">
          <div class="degraded-engine-title">
            <span class="degraded-icon" aria-hidden="true">⚠️</span>
            <strong>Degraded Retrieval Engine Active</strong>
          </div>
          <div class="degraded-engine-desc">
            Search request for <code>${escapeText(docResponse.engine_requested)}</code> degraded to <code>${escapeText(docResponse.engine_used)}</code>.
            ${docResponse.degraded_reason ? `<span class="degraded-reason">Reason: ${escapeText(docResponse.degraded_reason)}</span>` : ''}
          </div>
        </div>
      `;
    } else if (degradedBanner) {
      degradedBanner.style.display = 'none';
      degradedBanner.innerHTML = '';
    }

    // Stats Header & Telemetry
    if (isSearchMode) {
      const totalCandidates = docResponse.snapshot_total ?? docResponse.snapshot_candidate_count ?? docResponse.items.length;
      statsText.textContent = `Found ${totalCandidates} result${totalCandidates === 1 ? '' : 's'} for "${q}" (Page ${docResponse.page})`;

      telemetryBar.style.display = 'flex';
      telemetryBar.innerHTML = `
        <span class="telemetry-badge telemetry-engine ${docResponse.is_degraded ? 'badge-degraded' : ''}" title="Retrieval engine used">
          ${escapeText(docResponse.engine_used.toUpperCase())}
        </span>
        <span class="telemetry-badge telemetry-latency" title="Search latency">
          ${docResponse.latency_ms ? docResponse.latency_ms.toFixed(1) : '<1'}ms
        </span>
        <span class="telemetry-badge telemetry-gen" title="Index Generation">
          ${escapeText(docResponse.index_generation ? docResponse.index_generation.slice(0, 18) : 'active')}
        </span>
      `;
    } else {
      statsText.textContent = `Showing ${docResponse.items.length} of ${docResponse.total} published research documents`;
      telemetryBar.style.display = 'none';
      telemetryBar.innerHTML = '';
    }

    // Empty Results State
    if (!docResponse.items || docResponse.items.length === 0) {
      renderEmpty(docsList, {
        title: isSearchMode ? `No documents matched "${q}"` : 'No matching documents found',
        description: isSearchMode
          ? 'Try checking spelling, broadening search terms, switching retrieval mode, or clearing category filters.'
          : 'Try adjusting date ranges or selecting another collection from the sidebar.',
        action: { label: 'Reset All Filters', onClick: () => navigate('/library') }
      });
      if (paginationEl) paginationEl.innerHTML = '';
      return;
    }

    // Render Results List
    docsList.innerHTML = '';
    docResponse.items.forEach((doc, idx) => {
      const itemEl = document.createElement('article');
      itemEl.className = 'document-card-row';

      const searchEventId = isSearchMode ? docResponse.search_event_id : (docResponse.search_event_id || null);
      const detailUrl = `#/documents/${doc.id}${searchEventId ? `?search_event_id=${encodeURIComponent(searchEventId)}` : ''}`;
      const addedDate = new Date(doc.published_at || doc.created_at).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });

      const tagsHtml = (doc.tags || []).map(t =>
        `<button type="button" class="tag-chip" data-tag-id="${t.id}" title="Filter by tag ${escapeAttr(t.name)}">${escapeText(t.name)}</button>`
      ).join(' ');

      // Ranking & Score indicator in Search Mode
      const rankNumber = isSearchMode ? (doc.rank || (page - 1) * 15 + idx + 1) : null;
      const scoreValue = (isSearchMode && typeof doc.score === 'number') ? doc.score.toFixed(3) : null;

      itemEl.innerHTML = `
        <div class="doc-row-content">
          <div class="doc-row-header-line">
            ${isSearchMode ? `
              <span class="doc-rank-badge" title="Search rank position #${rankNumber}" aria-label="Rank ${rankNumber}">#${rankNumber}</span>
            ` : ''}
            <h2 class="doc-row-title">
              <a href="${detailUrl}">${escapeText(doc.title)}</a>
            </h2>
            ${scoreValue ? `
              <span class="doc-score-pill" title="Relevance Score: ${doc.score.toFixed(4)}" aria-label="Relevance score ${scoreValue}">
                ${scoreValue}
              </span>
            ` : ''}
          </div>

          <div class="doc-row-meta">
            <button type="button" class="category-chip" data-cat-id="${doc.category ? doc.category.id : (doc.category_id || '')}" title="Filter by collection ${escapeAttr(doc.category ? doc.category.name : 'Research')}">
              ${escapeText(doc.category ? doc.category.name : 'Research')}
            </button>
            <span class="meta-dot" aria-hidden="true">•</span>
            <span class="doc-author">By ${escapeText(doc.author || 'Wikipedia contributors')}</span>
            <span class="meta-dot" aria-hidden="true">•</span>
            <span class="doc-date">Added ${addedDate}</span>
            <div class="doc-counters">
              <span class="counter-item" title="${doc.views_count || 0} views" aria-label="${doc.views_count || 0} views">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                <span>${doc.views_count || 0}</span>
              </span>
              <span class="counter-item" title="${doc.likes_count || 0} likes" aria-label="${doc.likes_count || 0} likes">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                <span>${doc.likes_count || 0}</span>
              </span>
            </div>
          </div>

          <!-- Snippet or Summary container -->
          <div class="doc-summary-wrapper"></div>

          <div class="doc-row-bottom">
            <div class="doc-tags-list">${tagsHtml}</div>
          </div>
        </div>
      `;

      // Safely append summary / highlighted snippet (never raw HTML)
      const summaryWrapper = itemEl.querySelector('.doc-summary-wrapper');
      if (summaryWrapper) {
        summaryWrapper.appendChild(renderSafeSnippet(doc.snippet, doc.summary));
      }

      // Handle category chip clicking
      const catBtn = itemEl.querySelector('.category-chip');
      if (catBtn) {
        catBtn.onclick = (e) => {
          e.preventDefault();
          const cid = catBtn.getAttribute('data-cat-id');
          if (cid) updateRoute({ category_id: cid });
        };
      }

      // Interaction Telemetry: Single search click event dispatch per document navigation
      if (searchEventId) {
        const titleLink = itemEl.querySelector('.doc-row-title a');
        if (titleLink) {
          const requestKey = genUuid();
          titleLink.addEventListener('click', () => {
            // Dispatched without route signal so navigation does not cancel click telemetry
            api('/events/clicks', {
              method: 'POST',
              body: {
                search_event_id: searchEventId,
                document_id: doc.id,
                request_key: requestKey,
              },
            }).catch((err) => console.warn('Search click telemetry notice:', err));
          });
        }
      }

      // Handle tag clicking to filter by tag
      itemEl.querySelectorAll('.tag-chip').forEach(btn => {
        btn.onclick = (e) => {
          e.preventDefault();
          const tid = btn.getAttribute('data-tag-id');
          updateRoute({ tag_ids: tid });
        };
      });

      docsList.appendChild(itemEl);
    });

    // Render pagination
    if (paginationEl) {
      if (isSearchMode) {
        const totalCandidates = docResponse.snapshot_total ?? docResponse.snapshot_candidate_count ?? docResponse.items.length;
        renderPagination(paginationEl, {
          page: docResponse.page,
          pageSize: docResponse.page_size,
          total: totalCandidates,
          hasMore: docResponse.has_more,
          onChange: (newPage) => updateRoute({
            page: newPage,
            search_context_token: docResponse.search_context_token,
          }),
        });
      } else {
        renderPagination(paginationEl, {
          page: docResponse.page,
          pageSize: docResponse.page_size,
          total: docResponse.total,
          onChange: (newPage) => updateRoute({ page: newPage }),
        });
      }
    }

  } catch (err) {
    if (err.name === 'AbortError') return;
    const statsText = container.querySelector('#resultsCountText');
    if (statsText) statsText.textContent = 'Unable to load documents';
    renderError(container.querySelector('#documentsListContainer'), err, {
      onRetry: () => renderLibrary(container, routeContext)
    });
  }

  // Cleanup handler called when route changes
  return function routeCleanup() {
    document.title = 'Folio — Knowledge & Research Library';
  };
}

function escapeText(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  if (!str) return '';
  return str.replace(/"/g, '&quot;');
}

function genUuid() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
