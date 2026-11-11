// src/frontend/public/library_view.js
// Folio Library Directory & Search View (Mounted-Instance vs Request Lifecycle,
// Prefetch Ownership Handoff, Keyed Chip Exit/Reflow & Keyboard Focus Preservation)

import { api } from '../core/api.js';
import { navigate, getActiveNavigationTarget } from '../core/router.js';
import { renderPagination, renderError, renderEmpty } from '../core/ui.js';
import {
  MOTION_TOKENS,
  prefersReducedMotion,
  onReducedMotionChange,
  setSharedTitle,
  safeScrollIntoView,
} from '../core/motion.js';

// Pre-fetched document cache and clicked document title hint for seamless shared-title transition
export let prefetchedDocCache = new Map();
export let clickedDocHint = null;

/**
 * Aborts and removes unclaimed prefetch entries, optionally keeping one target document ID
 * that is actively being handed off to Document Detail view.
 */
export function pruneUnclaimedPrefetches(keepDocId = null) {
  for (const [id, entry] of Array.from(prefetchedDocCache.entries())) {
    if (keepDocId && id === keepDocId && !entry.claimed) {
      continue;
    }
    prefetchedDocCache.delete(id);
    if (entry.expireTimer) {
      clearTimeout(entry.expireTimer);
    }
    if (entry.hashWatchHandler && typeof window !== 'undefined') {
      window.removeEventListener('hashchange', entry.hashWatchHandler);
    }
    if (!entry.claimed && entry.controller) {
      try {
        entry.controller.abort();
      } catch (_) {}
    }
  }
}

/**
 * Claims ownership of an in-flight prefetched document request from Library for Detail view.
 * Links the Detail route's AbortSignal to the prefetch AbortController so abandoning Detail
 * aborts the underlying network request cleanly without unhandled rejections.
 */
export function claimPrefetchedDocument(docId, detailSignal = null) {
  const entry = prefetchedDocCache.get(docId);
  // Abort and clear any other unclaimed entries
  pruneUnclaimedPrefetches(docId);

  if (!entry) {
    return null;
  }

  prefetchedDocCache.delete(docId);
  if (entry.expireTimer) {
    clearTimeout(entry.expireTimer);
    entry.expireTimer = null;
  }
  if (entry.hashWatchHandler && typeof window !== 'undefined') {
    window.removeEventListener('hashchange', entry.hashWatchHandler);
    entry.hashWatchHandler = null;
  }

  if (Date.now() - entry.createdAt > 10000) {
    try {
      if (entry.controller) entry.controller.abort();
    } catch (_) {}
    return null;
  }

  entry.claimed = true;

  if (detailSignal) {
    if (detailSignal.aborted) {
      try {
        if (entry.controller) entry.controller.abort();
      } catch (_) {}
    } else {
      detailSignal.addEventListener(
        'abort',
        () => {
          try {
            if (entry.controller) entry.controller.abort();
          } catch (_) {}
        },
        { once: true }
      );
    }
  }

  return entry.promise;
}

function startDocumentPrefetch(doc) {
  pruneUnclaimedPrefetches(null);
  try {
    const prefetchController = new AbortController();
    const prefetchPromise = api(`/documents/${doc.id}`, {
      signal: prefetchController.signal,
    });
    // Attach immediate noop rejection handler so if aborted before Detail claims it,
    // Chromium never raises an unhandledrejection pageerror, while awaiting prefetchPromise
    // still propagates the exact error/AbortError to the consumer.
    prefetchPromise.catch(() => {});

    const entry = {
      docId: doc.id,
      promise: prefetchPromise,
      controller: prefetchController,
      title: doc.title,
      createdAt: Date.now(),
      claimed: false,
      expireTimer: null,
      hashWatchHandler: null,
    };

    const hashWatchHandler = () => {
      const target = getActiveNavigationTarget();
      const isTargetingThisDoc =
        target &&
        target.path === `/documents/${doc.id}` &&
        target.params &&
        target.params.id === doc.id;
      if (!isTargetingThisDoc && !entry.claimed) {
        pruneUnclaimedPrefetches(null);
      }
    };

    if (typeof window !== 'undefined') {
      entry.hashWatchHandler = hashWatchHandler;
      window.addEventListener('hashchange', hashWatchHandler);
    }

    entry.expireTimer = setTimeout(() => {
      if (!entry.claimed && prefetchedDocCache.get(doc.id) === entry) {
        pruneUnclaimedPrefetches(null);
      }
    }, 4000);

    prefetchedDocCache.set(doc.id, entry);
  } catch (_) {}
}

/**
 * Safely parses and renders a highlighted search snippet without raw HTML or attribute injection.
 * Only <em class="search-highlight"> elements and text nodes are permitted.
 */
export function renderSafeSnippet(snippetHtml, fallbackSummary = '') {
  const container = document.createElement('p');
  container.className = 'doc-row-summary';

  const raw = snippetHtml || fallbackSummary || '';
  if (!raw) return container;

  if (!snippetHtml || !/<[a-z][\s\S]*>/i.test(snippetHtml)) {
    container.textContent = raw;
    return container;
  }

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
          sanitizeNode(child, targetNode);
        }
      }
    }
  }

  sanitizeNode(parsedDoc.body, container);
  return container;
}

// Instance counter for explicit mounted Library instance ownership
let libraryInstanceSeq = 0;

function isInstanceActive(instance, routeContext = null) {
  if (!instance || instance.disposed) return false;
  if (!instance.container || instance.container.__folioLibraryInstance !== instance) return false;
  if (instance.mountSignal && instance.mountSignal.aborted) return false;
  if (routeContext && typeof routeContext.isMountActive === 'function' && !routeContext.isMountActive()) {
    return false;
  }
  return true;
}

/**
 * Synchronizes Library controls, title, Reset button, category indicator, and active filter chips
 * immediately from a URLSearchParams object.
 */
function syncLibraryControlsAndChips(instance, queryParams) {
  if (!isInstanceActive(instance)) return;

  instance.currentQuery = new URLSearchParams(queryParams);

  const q = (instance.currentQuery.get('q') || '').trim();
  const mode = (instance.currentQuery.get('mode') || 'bm25').toLowerCase();
  const categoryId = instance.currentQuery.get('category_id') || '';
  const tagIds = instance.currentQuery.get('tag_ids') || '';
  const dateFrom = instance.currentQuery.get('date_from') || '';
  const dateTo = instance.currentQuery.get('date_to') || '';
  const rawSort = instance.currentQuery.get('sort') || 'newest';
  const sort = rawSort === 'title_asc' ? 'title' : rawSort;

  instance.currentCategoryId = categoryId;
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

  const {
    searchInput,
    modeSelect,
    sortSelect,
    sortWrapper,
    dateFromInput,
    dateToInput,
    mobileFilterBtn,
    clearFiltersContainer,
  } = instance.elements;

  // Synchronize search input distinguishing draft typing from applied filter changes
  if (instance.appliedQuery === undefined) {
    instance.appliedQuery = q;
  }
  if (q !== instance.appliedQuery) {
    instance.appliedQuery = q;
    if (searchInput) searchInput.value = q;
  } else if (searchInput && document.activeElement !== searchInput && searchInput.value !== q) {
    searchInput.value = q;
  }

  if (modeSelect) modeSelect.value = mode;
  if (sortSelect) sortSelect.value = sort;
  if (sortWrapper) sortWrapper.style.display = isSearchMode ? 'none' : 'flex';
  if (sortSelect) sortSelect.disabled = isSearchMode;
  if (dateFromInput) dateFromInput.value = dateFrom;
  if (dateToInput) dateToInput.value = dateTo;

  // Sync mobile filter button active indicator
  if (mobileFilterBtn) {
    let dot = mobileFilterBtn.querySelector('.filter-active-indicator');
    if (hasActiveFilters) {
      if (!dot) {
        dot = document.createElement('span');
        dot.className = 'filter-active-indicator';
        dot.setAttribute('aria-label', 'Active filters applied');
        dot.textContent = '●';
        mobileFilterBtn.appendChild(dot);
      }
    } else if (dot) {
      dot.remove();
    }
  }

  // Synchronize Reset All Filters button in sidebar
  if (clearFiltersContainer) {
    clearFiltersContainer.innerHTML = hasActiveFilters
      ? `<button type="button" class="btn btn-secondary btn-sm" id="clearAllFiltersBtn" style="width: 100%; margin-top: 1rem;">Reset All Filters</button>`
      : '';
    const newClearBtn = clearFiltersContainer.querySelector('#clearAllFiltersBtn');
    if (newClearBtn) {
      newClearBtn.onclick = () => {
        if (!isInstanceActive(instance)) return;
        instance.appliedQuery = '';
        if (searchInput) searchInput.value = '';
        instance.updateRoute({
          q: null,
          mode: null,
          category_id: null,
          tag_ids: null,
          date_from: null,
          date_to: null,
          sort: null,
          page: null,
          search_context_token: null,
        });
      };
    }
  }

  // Sync category highlight sliding pill
  if (typeof instance.updateCategoryHighlight === 'function') {
    instance.updateCategoryHighlight(categoryId, true);
  }

  // Reconcile keyed filter chips with entrance, exit, reflow, and keyboard focus management
  renderActiveFilterChips(instance, {
    q,
    mode,
    isSearchMode,
    categoryId,
    tagIds,
    dateFrom,
    dateTo,
    hasActiveFilters,
  });
}

export async function renderLibrary(container, routeContext) {
  const { query } = routeContext;
  const mountSignal = routeContext.mountSignal || routeContext.signal;

  const q = (query.get('q') || '').trim();
  const mode = (query.get('mode') || 'bm25').toLowerCase();
  const categoryId = query.get('category_id') || '';
  const tagIds = query.get('tag_ids') || '';
  const dateFrom = query.get('date_from') || '';
  const dateTo = query.get('date_to') || '';
  const sort = query.get('sort') || 'newest';

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

  const isDatePanelOpen = Boolean(dateFrom || dateTo);

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

        <div class="date-filter-section">
          <button type="button" class="btn btn-secondary btn-sm toggle-date-btn" id="toggleDateFilterBtn" aria-expanded="${isDatePanelOpen ? 'true' : 'false'}" aria-controls="dateFilterAccordion">
            <span>Filter by Date</span>
            <svg class="chevron-icon ${isDatePanelOpen ? 'open' : ''}" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>

          <div class="collapsible-accordion ${isDatePanelOpen ? 'is-open' : ''}" id="dateFilterAccordion" style="margin-top: 0.5rem;">
            <div class="collapsible-inner" id="dateFilterInner" ${!isDatePanelOpen ? 'inert' : ''}>
              <div class="field" style="margin-bottom: 0.5rem;">
                <label class="label" for="filterDateFrom" style="font-size: 0.75rem;">From</label>
                <input type="date" class="input input-sm" id="filterDateFrom" value="${escapeAttr(dateFrom)}" />
              </div>
              <div class="field" style="margin-bottom: 0.75rem;">
                <label class="label" for="filterDateTo" style="font-size: 0.75rem;">To</label>
                <input type="date" class="input input-sm" id="filterDateTo" value="${escapeAttr(dateTo)}" />
              </div>
              <div id="dateValidationError" class="date-validation-inline-error" style="display: none; font-size: 0.75rem; padding: 0.4rem; margin-bottom: 0.5rem; color: var(--color-danger); background: var(--color-danger-subtle, #fde8e8); border-radius: var(--radius-sm, 4px);"></div>
              <button type="button" class="btn btn-primary btn-sm" id="applyDateFilterBtn" style="width: 100%;">Apply Dates</button>
            </div>
          </div>
        </div>

        <div id="clearFiltersBtnContainer">
          ${hasActiveFilters ? `
            <button type="button" class="btn btn-secondary btn-sm" id="clearAllFiltersBtn" style="width: 100%; margin-top: 1rem;">Reset All Filters</button>
          ` : ''}
        </div>
      </aside>

      <!-- Main Catalog & Search Column -->
      <section class="library-main-content" aria-label="Library Documents Catalog">
        <div class="library-toolbar">
          <div class="search-bar-wrapper">
            <input
              type="search"
              class="input library-search-input"
              id="librarySearchInput"
              placeholder="Search research papers, algorithms, history..."
              value="${escapeAttr(q)}"
              maxlength="200"
              aria-label="Search research documents"
            />
            <button type="button" class="btn btn-primary" id="librarySearchBtn" aria-label="Execute search">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <span>Search</span>
            </button>
          </div>

          <div class="library-controls-right">
            <!-- Retrieval Mode Selector -->
            <div class="control-group">
              <label for="libraryModeSelect" class="control-label">Mode:</label>
              <select class="select select-sm" id="libraryModeSelect" aria-label="Search mode selection">
                <option value="bm25" ${mode === 'bm25' ? 'selected' : ''}>BM25 Keyword</option>
                <option value="semantic" ${mode === 'semantic' || mode === 'vector' ? 'selected' : ''}>Semantic Vector</option>
                <option value="hybrid" ${mode === 'hybrid' ? 'selected' : ''}>Hybrid Reciprocal</option>
              </select>
            </div>

            <!-- Sort By Selector (Disabled when search mode is active) -->
            <div class="control-group" id="sortWrapper" style="${isSearchMode ? 'display: none;' : 'display: flex;'}">
              <label for="librarySortSelect" class="control-label">Sort:</label>
              <select class="select select-sm" id="librarySortSelect" aria-label="Sort documents" ${isSearchMode ? 'disabled' : ''}>
                <option value="newest" ${sort === 'newest' ? 'selected' : ''}>Newest First</option>
                <option value="oldest" ${sort === 'oldest' ? 'selected' : ''}>Oldest First</option>
                <option value="title" ${sort === 'title' || sort === 'title_asc' ? 'selected' : ''}>Title A–Z</option>
                <option value="title_desc" ${sort === 'title_desc' ? 'selected' : ''}>Title Z–A</option>
                <option value="popular" ${sort === 'popular' ? 'selected' : ''}>Most Popular</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Active Filter Badges Bar -->
        <div class="active-filters-bar" id="activeFiltersBar" style="${hasActiveFilters ? 'display: flex;' : 'display: none;'}"></div>

        <!-- Degraded Engine Alert Banner -->
        <div id="degradedEngineBanner" style="display: none; margin-bottom: 1rem;"></div>

        <!-- Results Counter & Telemetry Bar -->
        <div class="results-stats-header">
          <span id="resultsCountText" class="results-count-text">Loading catalog...</span>
          <div id="searchTelemetryBar" class="search-telemetry-bar" style="display: none;"></div>
        </div>

        <!-- Catalog Documents List -->
        <div id="documentsListContainer" class="documents-list" role="region" aria-label="Document search results">
          <div class="spinner" style="margin: 3rem auto; display: block;" aria-label="Loading documents..."></div>
        </div>

        <!-- Catalog Pagination -->
        <div id="libraryPaginationContainer"></div>
      </section>
    </div>
  `;

  // Elements mapping
  const searchInput = container.querySelector('#librarySearchInput');
  const searchBtn = container.querySelector('#librarySearchBtn');
  const modeSelect = container.querySelector('#libraryModeSelect');
  const sortSelect = container.querySelector('#librarySortSelect');
  const sortWrapper = container.querySelector('#sortWrapper');
  const dateFromInput = container.querySelector('#filterDateFrom');
  const dateToInput = container.querySelector('#filterDateTo');
  const dateErrorEl = container.querySelector('#dateValidationError');
  const applyDateBtn = container.querySelector('#applyDateFilterBtn');
  const toggleDateBtn = container.querySelector('#toggleDateFilterBtn');
  const dateAccordion = container.querySelector('#dateFilterAccordion');
  const dateInner = container.querySelector('#dateFilterInner');
  const mobileFilterBtn = container.querySelector('#mobileFilterToggleBtn');
  const librarySidebar = container.querySelector('#librarySidebar');
  const activeFiltersBar = container.querySelector('#activeFiltersBar');
  const catContainer = container.querySelector('#categoryFilterList');
  const clearFiltersContainer = container.querySelector('#clearFiltersBtnContainer');
  const degradedBanner = container.querySelector('#degradedEngineBanner');
  const statsText = container.querySelector('#resultsCountText');
  const telemetryBar = container.querySelector('#searchTelemetryBar');
  const docsList = container.querySelector('#documentsListContainer');
  const paginationEl = container.querySelector('#libraryPaginationContainer');

  // Create explicit mounted page instance object
  const instance = {
    instanceId: ++libraryInstanceSeq,
    mountId: routeContext.mountId,
    container,
    mountSignal,
    disposed: false,
    activeRequestId: 0,
    currentQuery: new URLSearchParams(query),
    appliedQuery: q,
    currentCategoryId: categoryId,
    categoriesList: [],
    categoriesLoaded: false,
    lastRemovedChipIndex: null,
    lastRemovedChipKey: null,
    enteringChips: new Map(),
    exitingChips: new Map(),
    reflowAnims: new Map(),
    lastChipsSignature: null,
    elements: {
      searchInput,
      searchBtn,
      modeSelect,
      sortSelect,
      sortWrapper,
      dateFromInput,
      dateToInput,
      dateErrorEl,
      toggleDateBtn,
      dateAccordion,
      dateInner,
      mobileFilterBtn,
      librarySidebar,
      activeFiltersBar,
      catContainer,
      clearFiltersContainer,
      degradedBanner,
      statsText,
      telemetryBar,
      docsList,
      paginationEl,
    },
    updateRoute: null,
    updateCategoryHighlight: null,
    handleResize: null,
  };

  container.__folioLibraryInstance = instance;
  try { sessionStorage.setItem('folio_last_library_route', window.location.hash || '#/library'); } catch (_) {}

  // Push updates to URL hash bound to this instance, synchronously updating currentQuery and chips
  function updateRoute(updates) {
    if (!isInstanceActive(instance)) return;
    const currentParams = new URLSearchParams(instance.currentQuery);
    Object.entries(updates).forEach(([k, v]) => {
      if (v !== null && v !== undefined && v !== '') {
        currentParams.set(k, String(v));
      } else {
        currentParams.delete(k);
      }
    });

    if (!('page' in updates)) {
      currentParams.delete('page');
      currentParams.delete('search_context_token');
    }

    // Synchronously update instance query & reconcile filter chips/focus before async hashchange
    syncLibraryControlsAndChips(instance, currentParams);

    const queryString = currentParams.toString();
    const newHash = queryString ? `/library?${queryString}` : '/library';
    try { sessionStorage.setItem('folio_last_library_route', `#${newHash}`); } catch (_) {}
    navigate(newHash);
  }

  instance.updateRoute = updateRoute;

  // Sliding teal pill highlight indicator logic
  let indicator = null;
  let currentIndicatorAnim = null;

  function createCategoryIndicator() {
    if (!catContainer) return;
    catContainer.classList.add('has-indicator');
    indicator = document.createElement('div');
    indicator.className = 'category-pill-indicator';
    indicator.id = 'categoryIndicator';
    indicator.setAttribute('aria-hidden', 'true');
    catContainer.insertBefore(indicator, catContainer.firstChild);
  }

  function positionIndicator(targetBtn, animate = true) {
    if (!indicator || !targetBtn) return;
    const top = targetBtn.offsetTop;
    const left = targetBtn.offsetLeft;
    const width = targetBtn.offsetWidth;
    const height = targetBtn.offsetHeight;

    if (currentIndicatorAnim) {
      currentIndicatorAnim.cancel();
      currentIndicatorAnim = null;
    }

    if (!animate || prefersReducedMotion()) {
      indicator.style.transform = `translate(${left}px, ${top}px)`;
      indicator.style.width = `${width}px`;
      indicator.style.height = `${height}px`;
      indicator.style.opacity = '1';
      return;
    }

    const currentTransform = indicator.style.transform || `translate(${left}px, ${top}px)`;
    const currentWidth = indicator.style.width || `${width}px`;
    const currentHeight = indicator.style.height || `${height}px`;

    const anim = indicator.animate(
      [
        {
          transform: currentTransform,
          width: currentWidth,
          height: currentHeight,
          opacity: 1,
        },
        {
          transform: `translate(${left}px, ${top}px)`,
          width: `${width}px`,
          height: `${height}px`,
          opacity: 1,
        },
      ],
      {
        duration: 200,
        easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
      }
    );

    currentIndicatorAnim = anim;
    anim.onfinish = () => {
      if (currentIndicatorAnim === anim) {
        indicator.style.transform = `translate(${left}px, ${top}px)`;
        indicator.style.width = `${width}px`;
        indicator.style.height = `${height}px`;
        indicator.style.opacity = '1';
        currentIndicatorAnim = null;
      }
    };
    anim.oncancel = () => {
      if (currentIndicatorAnim === anim) {
        currentIndicatorAnim = null;
      }
    };
  }

  function updateCategoryHighlight(activeCatId, animate = true) {
    if (!catContainer || !isInstanceActive(instance)) return;
    const allPills = catContainer.querySelectorAll('.category-pill');
    let activeBtn = null;
    allPills.forEach((btn) => {
      const btnCatId = btn.getAttribute('data-cat-id') || '';
      if (btnCatId === (activeCatId || '')) {
        btn.classList.add('active');
        activeBtn = btn;
      } else {
        btn.classList.remove('active');
      }
    });

    if (activeBtn) {
      positionIndicator(activeBtn, animate);
    } else if (indicator) {
      indicator.style.opacity = '0';
    }
  }

  instance.updateCategoryHighlight = updateCategoryHighlight;

  // Responsive Drawer Breakpoint & Inert Synchronization
  const mobileMq = window.matchMedia('(max-width: 860px)');
  function syncSidebarInert() {
    if (!isInstanceActive(instance)) return;
    const isMobile = mobileMq.matches;
    if (!isMobile) {
      librarySidebar.removeAttribute('inert');
      if (mobileFilterBtn) mobileFilterBtn.setAttribute('aria-expanded', 'false');
    } else {
      const isOpen = librarySidebar.classList.contains('open');
      if (isOpen) {
        librarySidebar.removeAttribute('inert');
        if (mobileFilterBtn) mobileFilterBtn.setAttribute('aria-expanded', 'true');
      } else {
        librarySidebar.setAttribute('inert', '');
        if (mobileFilterBtn) mobileFilterBtn.setAttribute('aria-expanded', 'false');
      }
    }
    requestAnimationFrame(() => {
      if (!isInstanceActive(instance)) return;
      updateCategoryHighlight(instance.currentCategoryId, false);
    });
  }

  syncSidebarInert();
  const mqListener = () => syncSidebarInert();
  if (mobileMq.addEventListener) {
    mobileMq.addEventListener('change', mqListener);
  } else if (mobileMq.addListener) {
    mobileMq.addListener(mqListener);
  }

  // Mobile Filter Drawer Toggle
  if (mobileFilterBtn && librarySidebar) {
    mobileFilterBtn.onclick = () => {
      const isExpanded = librarySidebar.classList.toggle('open');
      mobileFilterBtn.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
      if (isExpanded) {
        librarySidebar.removeAttribute('inert');
        requestAnimationFrame(() => {
          if (isInstanceActive(instance)) {
            updateCategoryHighlight(instance.currentCategoryId, false);
          }
        });
      } else {
        if (librarySidebar.contains(document.activeElement)) {
          mobileFilterBtn.focus();
        }
        if (mobileMq.matches) {
          librarySidebar.setAttribute('inert', '');
        }
      }
    };
  }

  // Date Filter Accordion Toggle
  if (toggleDateBtn && dateAccordion && dateInner) {
    toggleDateBtn.onclick = () => {
      const isOpen = dateAccordion.classList.toggle('is-open');
      toggleDateBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      if (isOpen) {
        dateInner.removeAttribute('inert');
      } else {
        dateInner.setAttribute('inert', '');
      }
    };
  }

  function handleSearchSubmit() {
    if (!isInstanceActive(instance)) return;
    const rawVal = searchInput.value.trim();
    if (rawVal.length > 200) {
      if (dateErrorEl) {
        dateErrorEl.textContent = 'Search query exceeds maximum allowed length of 200 characters.';
        dateErrorEl.style.display = 'block';
      }
      return;
    }
    instance.appliedQuery = rawVal;
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

  // Reposition indicator on resize or font loading
  const handleResize = () => {
    if (!isInstanceActive(instance)) return;
    updateCategoryHighlight(instance.currentCategoryId, false);
  };
  instance.handleResize = handleResize;
  window.addEventListener('resize', handleResize);
  if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => {
      if (isInstanceActive(instance)) handleResize();
    });
  }

  // Subscribe to live reduced motion changes
  const cleanupReducedMotion = onReducedMotionChange((isReduced) => {
    if (!isInstanceActive(instance)) return;
    if (currentIndicatorAnim) {
      currentIndicatorAnim.cancel();
      currentIndicatorAnim = null;
    }
    updateCategoryHighlight(instance.currentCategoryId, false);
    if (isReduced) {
      finalizeAllChipAnimations(instance);
    }
  });

  // Register idempotent page-level cleanup immediately BEFORE any network await (Finding A)
  const libraryCleanup = () => {
    if (instance.disposed) return;
    instance.disposed = true;

    window.removeEventListener('resize', handleResize);
    if (mobileMq.removeEventListener) {
      mobileMq.removeEventListener('change', mqListener);
    } else if (mobileMq.removeListener) {
      mobileMq.removeListener(mqListener);
    }
    if (cleanupReducedMotion) cleanupReducedMotion();
    if (currentIndicatorAnim) {
      currentIndicatorAnim.cancel();
      currentIndicatorAnim = null;
    }
    cancelAllChipAnimations(instance);

    if (container.__folioLibraryInstance === instance) {
      container.__folioLibraryInstance = null;
    }

    // Preserve only a prefetch actively being handed off to the target /documents/:id route (Finding C)
    const target = getActiveNavigationTarget();
    const handoffDocId =
      target && target.path && target.path.startsWith('/documents/') && target.params?.id
        ? target.params.id
        : null;
    pruneUnclaimedPrefetches(handoffDocId);
  };

  if (typeof routeContext.registerCleanup === 'function') {
    routeContext.registerCleanup(libraryCleanup);
  }

  // Fetch categories tied to the mounted page lifecycle (mountSignal), NOT the per-query signal!
  // This ensures changing search query during initial mount does not abort or break categories (Finding A2).
  const categoriesPromise = (async () => {
    try {
      const catData = await api('/categories', {
        query: { page: 1, page_size: 50 },
        signal: mountSignal,
      });
      if (!isInstanceActive(instance, routeContext)) return;

      instance.categoriesList = catData.items || [];
      instance.categoriesLoaded = true;

      if (catContainer) {
        catContainer.innerHTML = '';
        createCategoryIndicator();

        const activeCat = instance.currentCategoryId || '';
        const allCatBtn = document.createElement('button');
        allCatBtn.type = 'button';
        allCatBtn.className = `category-pill ${!activeCat ? 'active' : ''}`;
        allCatBtn.setAttribute('data-cat-id', '');
        allCatBtn.textContent = 'All Collections';
        allCatBtn.onclick = () => updateRoute({ category_id: '' });
        catContainer.appendChild(allCatBtn);

        instance.categoriesList.forEach((cat) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = `category-pill ${activeCat === cat.id ? 'active' : ''}`;
          btn.setAttribute('data-cat-id', cat.id);
          btn.innerHTML = `<span>${escapeText(cat.name)}</span> <span class="cat-count">${cat.published_document_count}</span>`;
          btn.onclick = () => updateRoute({ category_id: cat.id });
          catContainer.appendChild(btn);
        });

        requestAnimationFrame(() => {
          if (isInstanceActive(instance)) {
            updateCategoryHighlight(instance.currentCategoryId, false);
          }
        });
      }

      // If a category filter chip was rendered before categories finished loading, update its label in-place
      if (instance.currentCategoryId && activeFiltersBar) {
        const matchedCat = instance.categoriesList.find(
          (c) => c.id === instance.currentCategoryId
        );
        if (matchedCat) {
          const catChipLabel = activeFiltersBar.querySelector(
            ".active-filter-chip[data-chip-key='category_id']:not(.chip-removing) .chip-label"
          );
          if (catChipLabel) {
            catChipLabel.innerHTML = `<span>Collection: <strong>${escapeText(matchedCat.name)}</strong></span>`;
          }
        }
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      if (!isInstanceActive(instance)) return;
      console.warn('Failed to load categories list:', err);
      if (catContainer) {
        catContainer.textContent = 'Collections are temporarily unavailable.';
      }
    }
  })();

  // Start initial document query concurrently
  const docsPromise = fetchAndDisplayDocuments(instance, routeContext, {
    isInitialMount: true,
  });

  await Promise.all([categoriesPromise, docsPromise]);

  return libraryCleanup;
}

/**
 * In-place update handler called when staying on the Library route (Phase A).
 * Preserves the mounted Library instance, inputs, focus, open accordion panels, and smoothly updates results.
 */
export async function updateLibrary(container, routeContext) {
  const instance = container.__folioLibraryInstance;
  if (!isInstanceActive(instance, routeContext)) {
    return renderLibrary(container, routeContext);
  }

  await fetchAndDisplayDocuments(instance, routeContext, { isInitialMount: false });
}

/**
 * Common document fetching, skeleton loading, and rendering engine for both mount and in-place updates.
 * Strictly guarded by both mounted-instance ownership and per-request sequence ID.
 */
async function fetchAndDisplayDocuments(instance, routeContext, { isInitialMount = false } = {}) {
  if (!isInstanceActive(instance, routeContext)) return;

  const { query, signal } = routeContext;
  if (signal.aborted || (typeof routeContext.isStale === 'function' && routeContext.isStale())) return;
  const reqId = ++instance.activeRequestId;

  const isRequestStale = () =>
    !isInstanceActive(instance, routeContext) ||
    signal.aborted ||
    (typeof routeContext.isStale === 'function' && routeContext.isStale()) ||
    instance.activeRequestId !== reqId;

  const { elements, updateRoute } = instance;
  const {
    docsList,
    statsText,
    telemetryBar,
    paginationEl,
    degradedBanner,
  } = elements;

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

  syncLibraryControlsAndChips(instance, query);

  if (!isInitialMount) {
    // Previous errors no longer own a retry action once another request starts.
    const previousError = docsList?.querySelector('.notice-error');
    if (previousError?.contains(document.activeElement)) {
      elements.searchInput?.focus({ preventScroll: true });
    }
    previousError?.remove();
    if (docsList) {
      docsList.classList.remove('documents-list-fade');
      docsList.classList.add('is-updating');
      docsList.setAttribute('aria-busy', 'true');
    }
    if (statsText) {
      statsText.textContent = isSearchMode ? `Searching for "${q}"...` : 'Updating catalog...';
    }
  }

  // Skeleton loading delayed timer (150ms): only show skeleton if initial response takes > 150ms
  let skeletonTimer = null;
  if (isInitialMount && docsList) {
    skeletonTimer = setTimeout(() => {
      if (isRequestStale()) return;
      renderSkeletonCards(docsList);
    }, 150);
  }

  try {
    let docResponse;

    if (isSearchMode) {
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

      if (page > 1 && searchContextToken) {
        searchQueryParams.search_context_token = searchContextToken;
      }

      try {
        docResponse = await api('/search', { query: searchQueryParams, signal });
      } catch (err) {
        if (isRequestStale()) return;
        if (
          page > 1 &&
          (err.status === 410 ||
            err.code === 'SEARCH_CONTEXT_EXPIRED' ||
            err.code === 'CONTEXT_PARAMETER_MISMATCH' ||
            err.status === 400)
        ) {
          console.warn('Search context token expired or mismatched. Restarting search from page 1.');
          updateRoute({ page: 1, search_context_token: null });
          return;
        }
        throw err;
      }
    } else {
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

    if (skeletonTimer) clearTimeout(skeletonTimer);

    // Strict ownership & request sequence guard (Finding A)
    if (isRequestStale()) return;

    if (docsList) {
      docsList.classList.remove('is-updating');
      docsList.setAttribute('aria-busy', 'false');
    }

    // Display Degraded Engine Alert Banner if applicable
    if (isSearchMode && docResponse.is_degraded && degradedBanner) {
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
      const totalCandidates =
        docResponse.snapshot_total ??
        docResponse.snapshot_candidate_count ??
        docResponse.items.length;
      if (statsText) {
        statsText.textContent = `Found ${totalCandidates} result${totalCandidates === 1 ? '' : 's'} for "${q}" (Page ${docResponse.page})`;
      }
      if (telemetryBar) {
        telemetryBar.style.display = 'flex';
        telemetryBar.innerHTML = `
          <span class="telemetry-badge telemetry-engine ${docResponse.is_degraded ? 'badge-degraded' : ''}" title="Retrieval engine used">
            ${escapeText((docResponse.engine_used || 'bm25').toUpperCase())}
          </span>
          <span class="telemetry-badge telemetry-latency" title="Search latency">
            ${docResponse.latency_ms ? docResponse.latency_ms.toFixed(1) : '<1'}ms
          </span>
          <span class="telemetry-badge telemetry-gen" title="Index Generation">
            ${escapeText(docResponse.index_generation ? docResponse.index_generation.slice(0, 18) : 'active')}
          </span>
        `;
      }
    } else {
      if (statsText) {
        statsText.textContent = `Showing ${docResponse.items.length} of ${docResponse.total} published research documents`;
      }
      if (telemetryBar) {
        telemetryBar.style.display = 'none';
        telemetryBar.innerHTML = '';
      }
    }

    // Empty Results State
    if (!docResponse.items || docResponse.items.length === 0) {
      if (docsList) {
        renderEmpty(docsList, {
          title: isSearchMode ? `No documents matched "${q}"` : 'No matching documents found',
          description: isSearchMode
            ? 'Try checking spelling, broadening search terms, switching retrieval mode, or clearing category filters.'
            : 'Try adjusting date ranges or selecting another collection from the sidebar.',
          action: {
            label: 'Reset All Filters',
            onClick: () => {
              if (!isInstanceActive(instance)) return;
              instance.appliedQuery = '';
              if (instance.elements.searchInput) instance.elements.searchInput.value = '';
              updateRoute({
                q: null,
                mode: null,
                category_id: null,
                tag_ids: null,
                date_from: null,
                date_to: null,
                sort: null,
                page: null,
                search_context_token: null,
              });
            },
          },
        });
      }
      if (paginationEl) paginationEl.innerHTML = '';
      return;
    }

    // Render Results List with Motion
    if (docsList) {
      docsList.innerHTML = '';
      if (!isInitialMount) {
        docsList.classList.remove('documents-list-fade');
        void docsList.offsetWidth;
        docsList.classList.add('documents-list-fade');
        docsList.addEventListener(
          'animationend',
          () => {
            docsList.classList.remove('documents-list-fade');
          },
          { once: true }
        );
      }

      const hasBackRestoration = Boolean(
        (window.history.state && window.history.state.folioDocId) ||
          sessionStorage.getItem('folio_last_doc_id')
      );

      docResponse.items.forEach((doc, idx) => {
        const itemEl = document.createElement('article');
        itemEl.className = 'document-card-row';
        itemEl.setAttribute('data-doc-id', doc.id);

        if (isInitialMount && !hasBackRestoration && idx < 5 && !prefersReducedMotion()) {
          itemEl.classList.add('card-entrance');
          itemEl.style.setProperty('--card-index', String(idx));
        }

        const searchEventId = isSearchMode
          ? docResponse.search_event_id
          : docResponse.search_event_id || null;
        const detailUrl = `#/documents/${doc.id}${searchEventId ? `?search_event_id=${encodeURIComponent(searchEventId)}` : ''}`;
        const addedDate = new Date(doc.published_at || doc.created_at).toLocaleDateString('en-US', {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });

        const tagsHtml = (doc.tags || [])
          .map(
            (t) =>
              `<button type="button" class="tag-chip" data-tag-id="${t.id}" title="Filter by tag ${escapeAttr(t.name)}">${escapeText(t.name)}</button>`
          )
          .join(' ');

        const rankNumber = isSearchMode ? doc.rank || (page - 1) * 15 + idx + 1 : null;
        const scoreValue =
          isSearchMode && typeof doc.score === 'number' ? doc.score.toFixed(3) : null;

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

        const summaryWrapper = itemEl.querySelector('.doc-summary-wrapper');
        if (summaryWrapper) {
          summaryWrapper.appendChild(renderSafeSnippet(doc.snippet, doc.summary));
        }

        // Category chip click
        const catBtn = itemEl.querySelector('.category-chip');
        if (catBtn) {
          catBtn.onclick = (e) => {
            e.preventDefault();
            const cid = catBtn.getAttribute('data-cat-id');
            if (cid) updateRoute({ category_id: cid });
          };
        }

        // Tag chip click
        itemEl.querySelectorAll('.tag-chip').forEach((btn) => {
          btn.onclick = (e) => {
            e.preventDefault();
            const tid = btn.getAttribute('data-tag-id');
            updateRoute({ tag_ids: tid });
          };
        });

        // Title navigation & shared title transition + managed prefetch handoff (Finding C)
        const titleLink = itemEl.querySelector('.doc-row-title a');
        if (titleLink) {
          const requestKey = genUuid();
          titleLink.addEventListener('click', (e) => {
            // Respect native new-tab modifiers (Ctrl/Cmd/Shift/Alt/middle-click)
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0) {
              return;
            }

            // Record click telemetry once per click
            if (searchEventId) {
              api('/events/clicks', {
                method: 'POST',
                body: {
                  search_event_id: searchEventId,
                  document_id: doc.id,
                  request_key: requestKey,
                },
              }).catch((err) => console.warn('Search click telemetry notice:', err));
            }

            // Save scroll position and active doc ID per history entry
            try {
              const state = window.history.state || {};
              window.history.replaceState(
                { ...state, folioScroll: window.scrollY, folioDocId: doc.id },
                ''
              );
              sessionStorage.setItem('folio_library_scroll', String(window.scrollY));
              sessionStorage.setItem('folio_last_doc_id', doc.id);
            } catch (_) {}

            // Assign shared element name strictly to this clicked title
            setSharedTitle(titleLink, doc.id);
            clickedDocHint = { id: doc.id, title: doc.title, timestamp: Date.now() };

            // Start managed prefetch with immediate rejection handling & ownership handoff
            startDocumentPrefetch(doc);
          });
        }

        docsList.appendChild(itemEl);
      });
    }

    // Render pagination with smooth scroll to top of catalog results
    if (paginationEl) {
      const handlePageChange = (newPage) => {
        if (docsList) {
          safeScrollIntoView(docsList, { behavior: 'smooth', block: 'start' });
        }
        if (isSearchMode) {
          updateRoute({
            page: newPage,
            search_context_token: docResponse.search_context_token,
          });
        } else {
          updateRoute({ page: newPage });
        }
      };

      if (isSearchMode) {
        const totalCandidates =
          docResponse.snapshot_total ??
          docResponse.snapshot_candidate_count ??
          docResponse.items.length;
        renderPagination(paginationEl, {
          page: docResponse.page,
          pageSize: docResponse.page_size,
          total: totalCandidates,
          hasMore: docResponse.has_more,
          onChange: handlePageChange,
        });
      } else {
        renderPagination(paginationEl, {
          page: docResponse.page,
          pageSize: docResponse.page_size,
          total: docResponse.total,
          onChange: handlePageChange,
        });
      }
    }

    // Restore scroll and focus when returning from Document Detail AFTER cards & pagination are in DOM
    if (docsList) {
      try {
        const savedDocId =
          window.history.state?.folioDocId || sessionStorage.getItem('folio_last_doc_id');
        const savedScroll =
          window.history.state?.folioScroll !== undefined
            ? window.history.state.folioScroll
            : sessionStorage.getItem('folio_library_scroll')
              ? parseInt(sessionStorage.getItem('folio_library_scroll'), 10)
              : null;

        if (savedDocId && savedScroll !== null) {
          sessionStorage.removeItem('folio_last_doc_id');
          sessionStorage.removeItem('folio_library_scroll');
          const targetCard = docsList.querySelector(`[data-doc-id="${savedDocId}"]`);
          if (targetCard) {
            const applyScrollAndFocus = () => {
              if (!isInstanceActive(instance)) return;
              window.scrollTo({ top: savedScroll, behavior: 'instant' });
              const titleLink = targetCard.querySelector('.doc-row-title a');
              if (titleLink) {
                setSharedTitle(titleLink, savedDocId);
                titleLink.focus({ preventScroll: true });
              }
            };
            applyScrollAndFocus();
            requestAnimationFrame(applyScrollAndFocus);
          }
        }
      } catch (_) {}
    }
  } catch (err) {
    if (skeletonTimer) clearTimeout(skeletonTimer);
    if (isRequestStale()) return;
    if (err && err.name === 'AbortError') return;
    if (docsList) {
      docsList.classList.remove('is-updating');
      docsList.setAttribute('aria-busy', 'false');
      renderError(docsList, err, {
        onRetry: () => {
          if (isRequestStale()) return;
          fetchAndDisplayDocuments(instance, routeContext, { isInitialMount: false });
        },
      });
    }

    if (statsText) {
      statsText.textContent = '';
    }
    if (telemetryBar) {
      telemetryBar.style.display = 'none';
      telemetryBar.innerHTML = '';
    }
    if (degradedBanner) {
      degradedBanner.style.display = 'none';
      degradedBanner.innerHTML = '';
    }
    if (paginationEl) {
      paginationEl.innerHTML = '';
    }
  }
}

/**
 * Renders skeleton placeholder cards when a fetch takes longer than 150ms.
 */
function renderSkeletonCards(container) {
  container.innerHTML = `
    <div class="skeleton-card" aria-hidden="true">
      <div class="skeleton-line title"></div>
      <div class="skeleton-line meta"></div>
      <div class="skeleton-line desc"></div>
      <div class="skeleton-line desc-short"></div>
    </div>
    <div class="skeleton-card" aria-hidden="true">
      <div class="skeleton-line title"></div>
      <div class="skeleton-line meta"></div>
      <div class="skeleton-line desc"></div>
    </div>
    <div class="skeleton-card" aria-hidden="true">
      <div class="skeleton-line title"></div>
      <div class="skeleton-line meta"></div>
      <div class="skeleton-line desc"></div>
    </div>
  `;
}

// ==============================================================================
// Keyed Filter Chips Reconciliation, Exit/Reflow Animations & Focus (Finding D)
// ==============================================================================

function syncFiltersBarVisibility(instance) {
  const { activeFiltersBar } = instance.elements;
  if (!activeFiltersBar) return;
  const activeCount = activeFiltersBar.querySelectorAll(
    '.active-filter-chip:not(.chip-removing)'
  ).length;
  const exitingCount = instance.exitingChips.size;
  const clearAllBtn = activeFiltersBar.querySelector('.chip-clear-all-btn');

  if (activeCount === 0 && !clearAllBtn && exitingCount === 0) {
    activeFiltersBar.style.display = 'none';
    activeFiltersBar.style.minHeight = '';
  } else {
    activeFiltersBar.style.display = 'flex';
  }
}

function finalizeAllChipAnimations(instance) {
  for (const entry of Array.from(instance.enteringChips.values())) {
    if (entry.timer) clearTimeout(entry.timer);
    if (entry.anim) {
      try {
        entry.anim.cancel();
      } catch (_) {}
    }
    if (entry.chip) {
      entry.chip.classList.remove('chip-entering');
    }
  }
  instance.enteringChips.clear();

  for (const entry of Array.from(instance.exitingChips.values())) {
    if (typeof entry.finalize === 'function') {
      entry.finalize();
    }
  }
  instance.exitingChips.clear();

  for (const anim of Array.from(instance.reflowAnims.values())) {
    try {
      anim.cancel();
    } catch (_) {}
  }
  instance.reflowAnims.clear();
  instance.lastChipsSignature = null;

  syncFiltersBarVisibility(instance);
}

function cancelAllChipAnimations(instance) {
  finalizeAllChipAnimations(instance);
}

/**
 * Reconciles active filter chips by stable filter key (`q`, `mode`, `category_id`, `tag_ids`, `date`),
 * preserving DOM identity for unchanged chips, animating entrance only on new chips (~140ms),
 * running real exit + FLIP reflow animations on removed chips, and keeping keyboard focus valid.
 */
function renderActiveFilterChips(
  instance,
  { q, mode, isSearchMode, categoryId, tagIds, dateFrom, dateTo, hasActiveFilters }
) {
  const { activeFiltersBar, searchInput } = instance.elements;
  if (!activeFiltersBar) return;

  const { categoriesList, updateRoute } = instance;
  const reduced = prefersReducedMotion();

  // Build desired keyed chip descriptors in canonical order
  const desiredChips = [];

  if (q) {
    desiredChips.push({
      key: 'q',
      html: `<span>Query: "<strong>${escapeText(q)}</strong>"</span>`,
      btnTitle: 'Remove query filter',
      btnAria: 'Remove search query',
      onRemove: () => {
        instance.appliedQuery = '';
        if (searchInput) searchInput.value = '';
        updateRoute({ q: '' });
      },
    });
  }

  if (isSearchMode && mode !== 'bm25') {
    desiredChips.push({
      key: 'mode',
      html: `<span>Mode: <strong>${escapeText(mode.toUpperCase())}</strong></span>`,
      btnTitle: 'Reset to standard BM25',
      btnAria: 'Reset to BM25 mode',
      onRemove: () => updateRoute({ mode: 'bm25' }),
    });
  }

  if (categoryId) {
    const matchedCat = categoriesList.find((c) => c.id === categoryId);
    const catLabel = matchedCat ? matchedCat.name : 'Category';
    desiredChips.push({
      key: 'category_id',
      html: `<span>Collection: <strong>${escapeText(catLabel)}</strong></span>`,
      btnTitle: 'Remove collection filter',
      btnAria: 'Remove collection filter',
      onRemove: () => updateRoute({ category_id: '' }),
    });
  }

  if (tagIds) {
    desiredChips.push({
      key: 'tag_ids',
      html: `<span>Tag filter active</span>`,
      btnTitle: 'Remove tag filter',
      btnAria: 'Remove tag filter',
      onRemove: () => updateRoute({ tag_ids: '' }),
    });
  }

  if (dateFrom || dateTo) {
    const dateLabel = `${dateFrom || 'Any'} → ${dateTo || 'Present'}`;
    desiredChips.push({
      key: 'date',
      html: `<span>Date: <strong>${escapeText(dateLabel)}</strong></span>`,
      btnTitle: 'Remove date filter',
      btnAria: 'Remove date filter',
      onRemove: () => updateRoute({ date_from: '', date_to: '' }),
    });
  }

  const desiredMap = new Map(desiredChips.map((d, idx) => [d.key, { ...d, index: idx }]));

  // Idempotent reconcile guard: avoid cancelling in-flight reflow animations when chip state has not changed
  const currentChipsSignature = desiredChips
    .map((d) => `${d.key}:::${d.html}:::${d.btnTitle}:::${d.btnAria}`)
    .join(';;;') + `|||clearAll=${Boolean(hasActiveFilters)}`;

  const existingActiveChips = Array.from(
    activeFiltersBar.querySelectorAll('.active-filter-chip:not(.chip-removing)')
  );
  const isDomCountMatching = existingActiveChips.length === desiredChips.length;
  if (instance.lastChipsSignature === currentChipsSignature && isDomCountMatching) {
    return;
  }
  instance.lastChipsSignature = currentChipsSignature;

  // 1. Collect currently active (non-removing) chips & record FIRST rects before DOM changes
  let clearAllBtn = activeFiltersBar.querySelector('.chip-clear-all-btn');
  const prevBarHeight = activeFiltersBar.offsetHeight;

  const firstRects = new Map();
  const firstOffsets = new Map();

  existingActiveChips.forEach((chip) => {
    firstRects.set(chip, chip.getBoundingClientRect());
    firstOffsets.set(chip, {
      left: chip.offsetLeft,
      top: chip.offsetTop,
      width: chip.offsetWidth,
      height: chip.offsetHeight,
    });
  });
  if (clearAllBtn) {
    firstRects.set(clearAllBtn, clearAllBtn.getBoundingClientRect());
  }

  // Cancel any in-flight reflow animations so subsequent layout measurement uses natural coordinates
  for (const [el, anim] of Array.from(instance.reflowAnims.entries())) {
    try {
      anim.cancel();
    } catch (_) {}
    instance.reflowAnims.delete(el);
  }

  // 2. If any desired chip key is currently in exitingChips, finalize it immediately before re-adding
  for (const key of desiredMap.keys()) {
    if (instance.exitingChips.has(key)) {
      const exiting = instance.exitingChips.get(key);
      if (exiting && typeof exiting.finalize === 'function') {
        exiting.finalize();
      }
    }
  }

  // 3. Identify surviving vs exiting chips
  const survivingByKey = new Map();
  const chipsToExit = [];

  existingActiveChips.forEach((chip) => {
    const key = chip.getAttribute('data-chip-key') || '';
    if (desiredMap.has(key)) {
      survivingByKey.set(key, chip);
    } else {
      chipsToExit.push({ key, chip });
    }
  });

  // 4. Before disabling/removing exiting chips, check whether focus needs to be restored
  const previouslyFocusedInBar = activeFiltersBar.contains(document.activeElement)
    ? document.activeElement
    : null;
  const focusWasInExitingChip = chipsToExit.some(({ chip }) =>
    chip.contains(document.activeElement)
  );
  const needsFocusRestore =
    focusWasInExitingChip || typeof instance.lastRemovedChipIndex === 'number';

  // 5. Reconcile surviving and newly entering chips in canonical order
  // Never re-append existing surviving chips so browser focus inside them is never blurred
  if (
    hasActiveFilters ||
    desiredChips.length > 0 ||
    chipsToExit.length > 0 ||
    instance.exitingChips.size > 0
  ) {
    activeFiltersBar.style.display = 'flex';
  }

  function bindChipRemove(btn, chipEl, key, removeFn) {
    const triggerRemove = () => {
      if (!isInstanceActive(instance)) return;
      if (chipEl.classList.contains('chip-removing')) return;

      const currentActive = Array.from(
        activeFiltersBar.querySelectorAll('.active-filter-chip:not(.chip-removing)')
      );
      const idx = currentActive.indexOf(chipEl);
      instance.lastRemovedChipIndex = idx >= 0 ? idx : 0;
      instance.lastRemovedChipKey = key;

      removeFn();
    };

    btn.onclick = (e) => {
      e.preventDefault();
      triggerRemove();
    };

    btn.onkeydown = (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        triggerRemove();
      }
    };
  }

  let enteredAny = false;

  desiredChips.forEach((desc, descIdx) => {
    let chip = survivingByKey.get(desc.key);
    if (chip) {
      // Preserve existing DOM node identity and position; update label and remove callback in place
      const labelEl = chip.querySelector('.chip-label');
      if (labelEl && labelEl.innerHTML !== desc.html) {
        labelEl.innerHTML = desc.html;
      }
      const removeBtn = chip.querySelector('.chip-remove-btn');
      if (removeBtn) {
        removeBtn.setAttribute('title', desc.btnTitle);
        removeBtn.setAttribute('aria-label', desc.btnAria);
        bindChipRemove(removeBtn, chip, desc.key, desc.onRemove);
      }
    } else {
      // Create new chip and trigger 140ms entrance animation
      enteredAny = true;
      chip = document.createElement('span');
      chip.className = 'active-filter-chip';
      chip.setAttribute('data-chip-key', desc.key);
      chip.innerHTML = `<span class="chip-label">${desc.html}</span> <button type="button" class="chip-remove-btn" title="${escapeAttr(desc.btnTitle)}" aria-label="${escapeAttr(desc.btnAria)}">✕</button>`;

      const removeBtn = chip.querySelector('.chip-remove-btn');
      if (removeBtn) {
        bindChipRemove(removeBtn, chip, desc.key, desc.onRemove);
      }

      if (!reduced) {
        chip.classList.add('chip-entering');
        const clearEntering = () => {
          chip.classList.remove('chip-entering');
          const entry = instance.enteringChips.get(desc.key);
          if (entry && entry.timer) clearTimeout(entry.timer);
          instance.enteringChips.delete(desc.key);
        };
        const timer = setTimeout(clearEntering, MOTION_TOKENS.fast + 20);
        chip.addEventListener('animationend', clearEntering, { once: true });
        instance.enteringChips.set(desc.key, { chip, anim: null, timer });
      }

      // Insert in canonical order before the next surviving active chip or clearAllBtn
      let refNode = null;
      for (let i = descIdx + 1; i < desiredChips.length; i++) {
        const nextChip = survivingByKey.get(desiredChips[i].key);
        if (nextChip && nextChip.parentNode === activeFiltersBar) {
          refNode = nextChip;
          break;
        }
      }
      if (!refNode && clearAllBtn && clearAllBtn.parentNode === activeFiltersBar) {
        refNode = clearAllBtn;
      }
      if (refNode) {
        activeFiltersBar.insertBefore(chip, refNode);
      } else {
        activeFiltersBar.appendChild(chip);
      }

      survivingByKey.set(desc.key, chip);
    }
  });

  // 6. Reconcile Clear All button at the end of activeFiltersBar
  if (hasActiveFilters) {
    if (!clearAllBtn) {
      clearAllBtn = document.createElement('button');
      clearAllBtn.type = 'button';
      clearAllBtn.className = 'btn btn-secondary btn-sm chip-clear-all-btn';
      clearAllBtn.style.padding = '2px 8px';
      clearAllBtn.style.fontSize = '0.75rem';
      clearAllBtn.textContent = 'Clear All';
    }
    clearAllBtn.onclick = () => {
      if (!isInstanceActive(instance)) return;
      instance.appliedQuery = '';
      if (searchInput) searchInput.value = '';
      instance.lastRemovedChipIndex = 0;
      updateRoute({
        q: null,
        mode: null,
        category_id: null,
        tag_ids: null,
        date_from: null,
        date_to: null,
        sort: null,
        page: null,
        search_context_token: null,
      });
    };
    if (clearAllBtn.parentNode !== activeFiltersBar) {
      activeFiltersBar.appendChild(clearAllBtn);
    }
  } else if (clearAllBtn) {
    clearAllBtn.remove();
    clearAllBtn = null;
  }

  // 7. Shift keyboard focus onto nearest surviving active chip remove button or search input
  // BEFORE disabling/removing exiting chips so focus never drops to BODY
  if (needsFocusRestore) {
    const removedIdx =
      typeof instance.lastRemovedChipIndex === 'number' ? instance.lastRemovedChipIndex : 0;
    instance.lastRemovedChipIndex = null;
    instance.lastRemovedChipKey = null;

    const remainingButtons = Array.from(survivingByKey.values())
      .map((c) => c.querySelector('.chip-remove-btn'))
      .filter(Boolean);

    if (remainingButtons.length > 0) {
      const nextBtn = remainingButtons[Math.min(removedIdx, remainingButtons.length - 1)];
      if (nextBtn) nextBtn.focus();
    } else if (searchInput) {
      searchInput.focus();
    }
  } else if (
    previouslyFocusedInBar &&
    previouslyFocusedInBar.isConnected &&
    !previouslyFocusedInBar.closest('.chip-removing') &&
    document.activeElement !== previouslyFocusedInBar
  ) {
    previouslyFocusedInBar.focus();
  }

  // 8. Start exit lifecycle for removed chips
  chipsToExit.forEach(({ key, chip }) => {
    if (instance.enteringChips.has(key)) {
      const entering = instance.enteringChips.get(key);
      if (entering && entering.timer) clearTimeout(entering.timer);
      instance.enteringChips.delete(key);
      chip.classList.remove('chip-entering');
    }

    if (reduced) {
      chip.remove();
      return;
    }

    // Keep bar height stable if the last chip is exiting
    if (desiredChips.length === 0 && !hasActiveFilters && prevBarHeight > 0) {
      activeFiltersBar.style.minHeight = `${prevBarHeight}px`;
    }

    const box = firstOffsets.get(chip) || {
      left: chip.offsetLeft,
      top: chip.offsetTop,
      width: chip.offsetWidth,
      height: chip.offsetHeight,
    };

    chip.classList.add('chip-removing');
    chip.setAttribute('aria-hidden', 'true');
    chip.setAttribute('inert', '');

    const btn = chip.querySelector('.chip-remove-btn');
    if (btn) {
      btn.disabled = true;
      btn.tabIndex = -1;
      btn.onclick = null;
      btn.onkeydown = null;
    }

    chip.style.position = 'absolute';
    chip.style.left = `${box.left}px`;
    chip.style.top = `${box.top}px`;
    chip.style.width = `${box.width}px`;
    chip.style.height = `${box.height}px`;
    chip.style.margin = '0';
    chip.style.pointerEvents = 'none';

    let exitAnim = null;
    if (typeof chip.animate === 'function') {
      try {
        exitAnim = chip.animate(
          [
            { opacity: 0.92, transform: 'scale(0.98)' },
            { opacity: 0, transform: 'scale(0.85)' },
          ],
          {
            duration: MOTION_TOKENS.fast,
            easing: MOTION_TOKENS.easing,
            fill: 'forwards',
          }
        );
      } catch (_) {}
    }

    let finalized = false;
    const finalize = () => {
      if (finalized) return;
      finalized = true;
      clearTimeout(timer);
      instance.exitingChips.delete(key);
      if (exitAnim) {
        try {
          exitAnim.cancel();
        } catch (_) {}
      }
      if (chip.parentNode) {
        chip.parentNode.removeChild(chip);
      }
      syncFiltersBarVisibility(instance);
    };

    // Let the browser finish WAAPI on its animation clock, including delayed frames.
    const timer = exitAnim ? null : setTimeout(finalize, MOTION_TOKENS.fast + 30);
    if (exitAnim) {
      exitAnim.onfinish = finalize;
      exitAnim.oncancel = finalize;
    }

    instance.exitingChips.set(key, { chip, anim: exitAnim, timer, finalize });
  });

  // 9. Run FLIP reflow animation on surviving chips when sibling chips entered or exited
  if (!reduced && (chipsToExit.length > 0 || enteredAny)) {
    const reflowTargets = Array.from(survivingByKey.values());
    if (clearAllBtn && firstRects.has(clearAllBtn)) {
      reflowTargets.push(clearAllBtn);
    }

    reflowTargets.forEach((el) => {
      const firstRect = firstRects.get(el);
      if (!firstRect) return;
      const lastRect = el.getBoundingClientRect();
      const dx = firstRect.left - lastRect.left;
      const dy = firstRect.top - lastRect.top;
      if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
        if (typeof el.animate === 'function') {
          try {
            const anim = el.animate(
              [
                { transform: `translate(${dx}px, ${dy}px)` },
                { transform: 'translate(0, 0)' },
              ],
              {
                duration: MOTION_TOKENS.fast,
                easing: MOTION_TOKENS.easing,
              }
            );
            instance.reflowAnims.set(el, anim);
            const cleanupReflow = () => {
              if (instance.reflowAnims.get(el) === anim) {
                instance.reflowAnims.delete(el);
              }
            };
            anim.onfinish = cleanupReflow;
            anim.oncancel = cleanupReflow;
          } catch (_) {}
        }
      }
    });
  }

  syncFiltersBarVisibility(instance);
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
