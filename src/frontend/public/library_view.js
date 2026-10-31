// src/frontend/public/library_view.js
// Folio Library Directory & Search View

import { api } from '../core/api.js';
import { navigate } from '../core/router.js';
import { renderPagination, renderError, renderEmpty } from '../core/ui.js';

export async function renderLibrary(container, routeContext) {
  const { query, signal } = routeContext;

  // Extract query parameters from URL hash
  const q = query.get('q') || '';
  const categoryId = query.get('category_id') || '';
  const tagIds = query.get('tag_ids') || '';
  const dateFrom = query.get('date_from') || '';
  const dateTo = query.get('date_to') || '';
  const sort = query.get('sort') || 'newest';
  const page = Math.max(1, parseInt(query.get('page') || '1', 10));

  document.title = 'Library Catalog — Folio';

  const hasActiveFilters = Boolean(q || categoryId || tagIds || dateFrom || dateTo || sort !== 'newest');

  container.innerHTML = `
    <div class="public-page library-layout">
      <!-- Sidebar Categories & Taxonomy Filter (~220px) -->
      <aside class="library-sidebar" aria-label="Library Filters">
        <h3 class="sidebar-title">Categories</h3>
        <div id="categoryFilterList" class="category-list">
          <div class="spinner" style="margin: 1rem auto; display: block;"></div>
        </div>

        <hr style="border: none; border-top: 1px solid var(--color-border); margin: 1.25rem 0;" />

        <div class="sidebar-collapsible-section">
          <button type="button" class="sidebar-toggle-btn" id="toggleDateFilterBtn" aria-expanded="${Boolean(dateFrom || dateTo)}">
            <span class="sidebar-title" style="margin: 0;">Date Filter</span>
            <span class="toggle-icon">${(dateFrom || dateTo) ? '▲' : '▼'}</span>
          </button>
          <div id="dateFilterPanel" class="collapsible-panel" style="${(dateFrom || dateTo) ? 'display: block;' : 'display: none;'}">
            <div class="field" style="margin-top: 0.5rem; margin-bottom: 0.75rem;">
              <label class="label" for="filterDateFrom">Added From</label>
              <input class="input" type="date" id="filterDateFrom" value="${escapeAttr(dateFrom)}" />
            </div>
            <div class="field" style="margin-bottom: 0.75rem;">
              <label class="label" for="filterDateTo">Added To</label>
              <input class="input" type="date" id="filterDateTo" value="${escapeAttr(dateTo)}" />
            </div>
            <div id="dateValidationError" class="field-error-text" style="display: none; margin-bottom: 0.5rem;"></div>
            <button class="btn btn-secondary btn-sm" id="applyDateFilterBtn" style="width: 100%;">Apply Date</button>
          </div>
        </div>

        ${hasActiveFilters ? `
          <button class="btn btn-secondary btn-sm" id="clearAllFiltersBtn" style="width: 100%; margin-top: 1rem;">Reset All Filters</button>
        ` : ''}
      </aside>

      <!-- Main Catalog Results Area -->
      <section class="library-main">
        <div class="library-toolbar">
          <div class="search-bar-wrapper">
            <input type="search" id="librarySearchInput" class="input library-search-input"
                   placeholder="Search 100+ documents by keyword, concept, or author..."
                   value="${escapeAttr(q)}" aria-label="Search documents" />
            <button class="btn btn-primary" id="librarySearchBtn">Search</button>
          </div>

          <div class="sort-wrapper">
            <label for="librarySortSelect" class="sort-label">Sort:</label>
            <select id="librarySortSelect" class="select sort-select" aria-label="Sort documents">
              <option value="newest" ${sort === 'newest' ? 'selected' : ''}>Newest First</option>
              <option value="oldest" ${sort === 'oldest' ? 'selected' : ''}>Oldest First</option>
              <option value="title" ${sort === 'title' ? 'selected' : ''}>Title (A–Z)</option>
            </select>
          </div>
        </div>

        <!-- Active Filter Chips Bar -->
        <div id="activeFiltersBar" class="active-filters-bar" style="${hasActiveFilters ? 'display: flex;' : 'display: none;'}"></div>

        <!-- Results Counter & Search Event Notice -->
        <div class="library-stats-header">
          <span id="resultsCountText" class="results-count-text">Loading catalog...</span>
          <span id="searchEventNotice" class="search-event-notice" style="display: none;"></span>
        </div>

        <!-- Document List Area -->
        <div id="documentsListContainer" class="documents-list">
          <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
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

    // Reset page to 1 whenever any filter is updated (unless page itself is explicitly specified)
    if (!('page' in updates)) {
      params.delete('page');
    }

    const queryString = params.toString();
    const newHash = queryString ? `/library?${queryString}` : '/library';
    navigate(newHash);
  }

  // Hook up filter inputs and buttons
  const searchInput = container.querySelector('#librarySearchInput');
  const searchBtn = container.querySelector('#librarySearchBtn');
  const sortSelect = container.querySelector('#librarySortSelect');
  const dateFromInput = container.querySelector('#filterDateFrom');
  const dateToInput = container.querySelector('#filterDateTo');
  const dateErrorEl = container.querySelector('#dateValidationError');
  const applyDateBtn = container.querySelector('#applyDateFilterBtn');
  const clearFiltersBtn = container.querySelector('#clearAllFiltersBtn');
  const toggleDateBtn = container.querySelector('#toggleDateFilterBtn');
  const datePanel = container.querySelector('#dateFilterPanel');

  if (toggleDateBtn && datePanel) {
    toggleDateBtn.onclick = () => {
      const isHidden = datePanel.style.display === 'none';
      datePanel.style.display = isHidden ? 'block' : 'none';
      toggleDateBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
      const icon = toggleDateBtn.querySelector('.toggle-icon');
      if (icon) icon.textContent = isHidden ? '▲' : '▼';
    };
  }

  searchBtn.onclick = () => updateRoute({ q: searchInput.value.trim() });
  searchInput.onkeydown = (e) => {
    if (e.key === 'Enter') updateRoute({ q: searchInput.value.trim() });
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
      allCatBtn.className = `category-pill ${!categoryId ? 'active' : ''}`;
      allCatBtn.textContent = 'All Collections';
      allCatBtn.onclick = () => updateRoute({ category_id: '' });
      catContainer.appendChild(allCatBtn);

      categoriesList.forEach((cat) => {
        const btn = document.createElement('button');
        btn.className = `category-pill ${categoryId === cat.id ? 'active' : ''}`;
        btn.innerHTML = `<span>${escapeText(cat.name)}</span> <span class="cat-count">${cat.published_document_count}</span>`;
        btn.onclick = () => updateRoute({ category_id: cat.id });
        catContainer.appendChild(btn);
      });
    }
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.warn('Failed to load categories list:', err);
  }

  // Populate active filter chips bar
  const activeFiltersBar = container.querySelector('#activeFiltersBar');
  if (activeFiltersBar && hasActiveFilters) {
    activeFiltersBar.innerHTML = '';

    if (q) {
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Query: "<strong>${escapeText(q)}</strong>"</span> <button class="chip-remove-btn" title="Remove query filter" aria-label="Remove search query">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ q: '' });
      activeFiltersBar.appendChild(chip);
    }

    if (categoryId) {
      const matchedCat = categoriesList.find(c => c.id === categoryId);
      const catLabel = matchedCat ? matchedCat.name : 'Category';
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Collection: <strong>${escapeText(catLabel)}</strong></span> <button class="chip-remove-btn" title="Remove collection filter" aria-label="Remove collection filter">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ category_id: '' });
      activeFiltersBar.appendChild(chip);
    }

    if (tagIds) {
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Tag filter active</span> <button class="chip-remove-btn" title="Remove tag filter" aria-label="Remove tag filter">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ tag_ids: '' });
      activeFiltersBar.appendChild(chip);
    }

    if (dateFrom || dateTo) {
      const dateLabel = `${dateFrom || 'Any'} → ${dateTo || 'Present'}`;
      const chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.innerHTML = `<span>Date: <strong>${escapeText(dateLabel)}</strong></span> <button class="chip-remove-btn" title="Remove date filter" aria-label="Remove date filter">✕</button>`;
      chip.querySelector('.chip-remove-btn').onclick = () => updateRoute({ date_from: '', date_to: '' });
      activeFiltersBar.appendChild(chip);
    }

    const resetAllChip = document.createElement('button');
    resetAllChip.className = 'btn btn-secondary btn-sm';
    resetAllChip.style.padding = '2px 8px';
    resetAllChip.style.fontSize = '0.75rem';
    resetAllChip.textContent = 'Clear All';
    resetAllChip.onclick = () => navigate('/library');
    activeFiltersBar.appendChild(resetAllChip);
  }

  // 2. Fetch published documents
  try {
    const docResponse = await api('/documents', {
      query: {
        q: q || undefined,
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

    const docsList = container.querySelector('#documentsListContainer');
    const statsText = container.querySelector('#resultsCountText');
    const searchNotice = container.querySelector('#searchEventNotice');
    const paginationEl = container.querySelector('#libraryPaginationContainer');

    statsText.textContent = `Showing ${docResponse.items.length} of ${docResponse.total} published research documents`;
    if (docResponse.search_event_id) {
      searchNotice.style.display = 'inline-block';
      searchNotice.textContent = `Search event ID: ${docResponse.search_event_id.slice(0, 8)}...`;
    } else {
      searchNotice.style.display = 'none';
    }

    if (docResponse.items.length === 0) {
      renderEmpty(docsList, {
        title: 'No matching documents found',
        description: 'Try adjusting your search keywords, broadening date ranges, or browsing other collections.',
        action: { label: 'Reset All Filters', onClick: () => navigate('/library') }
      });
      if (paginationEl) paginationEl.innerHTML = '';
      return;
    }

    docsList.innerHTML = '';
    docResponse.items.forEach((doc) => {
      const itemEl = document.createElement('article');
      itemEl.className = 'document-card-row';

      const detailUrl = `#/documents/${doc.id}${docResponse.search_event_id ? `?search_event_id=${docResponse.search_event_id}` : ''}`;
      const addedDate = new Date(doc.created_at).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });

      const tagsHtml = (doc.tags || []).map(t =>
        `<button class="tag-chip" data-tag-id="${t.id}" title="Filter by tag ${escapeAttr(t.name)}">${escapeText(t.name)}</button>`
      ).join(' ');

      itemEl.innerHTML = `
        <div class="doc-row-content">
          <h2 class="doc-row-title">
            <a href="${detailUrl}">${escapeText(doc.title)}</a>
          </h2>
          <div class="doc-row-meta">
            <button type="button" class="category-chip" data-cat-id="${doc.category_id}" title="Filter by ${escapeAttr(doc.category ? doc.category.name : 'Research')}">
              ${escapeText(doc.category ? doc.category.name : 'Research')}
            </button>
            <span class="meta-dot" aria-hidden="true">•</span>
            <span class="doc-author">By ${escapeText(doc.author || 'Wikipedia contributors')}</span>
            <span class="meta-dot" aria-hidden="true">•</span>
            <span class="doc-date">Added ${addedDate}</span>
            <div class="doc-counters">
              <span class="counter-item" title="${doc.views_count} views" aria-label="${doc.views_count} views">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                <span>${doc.views_count}</span>
              </span>
              <span class="counter-item" title="${doc.likes_count} likes" aria-label="${doc.likes_count} likes">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                <span>${doc.likes_count}</span>
              </span>
            </div>
          </div>
          <p class="doc-row-summary">${escapeText(doc.summary)}</p>
          <div class="doc-row-bottom">
            <div class="doc-tags-list">${tagsHtml}</div>
          </div>
        </div>
      `;

      // Handle category chip clicking
      const catBtn = itemEl.querySelector('.category-chip');
      if (catBtn) {
        catBtn.onclick = (e) => {
          e.preventDefault();
          const cid = catBtn.getAttribute('data-cat-id');
          if (cid) updateRoute({ category_id: cid });
        };
      }

      // Handle search result click event logging with stable request_key
      if (docResponse.search_event_id) {
        const titleLink = itemEl.querySelector('.doc-row-title a');
        if (titleLink) {
          const requestKey = genUuid();
          titleLink.addEventListener('click', () => {
            api('/events/clicks', {
              method: 'POST',
              body: {
                search_event_id: docResponse.search_event_id,
                document_id: doc.id,
                request_key: requestKey,
              },
            }).catch((err) => console.warn('Search click logging warning:', err));
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
      renderPagination(paginationEl, {
        page: docResponse.page,
        pageSize: docResponse.page_size,
        total: docResponse.total,
        onChange: (newPage) => updateRoute({ page: newPage }),
      });
    }

  } catch (err) {
    if (err.name === 'AbortError') return;
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
