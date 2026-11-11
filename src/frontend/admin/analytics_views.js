// src/frontend/admin/analytics_views.js
// Analytics & SEO: Document SEO metadata editor, SERP preview, Analytics dashboard

import { api, ApiError } from '../core/api.js';
import { can } from '../core/session.js';
import { notify, confirmAction, renderPagination, renderError } from '../core/ui.js';
import { wrapAdminLayout } from './admin_shell.js';

// ==============================================================================
// 1. SEO Metadata Management & SERP Preview
// ==============================================================================

export async function renderSeoManager(container, routeContext) {
  if (!can('seo:write')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/seo',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have SEO metadata management permissions.</p></div>'
    );
    return;
  }

  const { query, params, signal } = routeContext;
  const q = query.get('q') || '';
  const page = parseInt(query.get('page') || '1', 10);

  document.title = 'SEO Metadata — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div style="display: flex; gap: 0.5rem; flex: 1; max-width: 600px;">
        <input type="search" id="seoSearchInput" class="input" placeholder="Search documents to configure SEO..." value="${escapeAttr(q)}" />
        <button class="btn btn-secondary" id="seoFilterBtn">Filter</button>
      </div>
      ${can('analytics:read') ? `<a href="#/admin/analytics" class="btn btn-secondary">View Analytics &rarr;</a>` : ''}
    </div>

    <div id="seoTableArea" class="table-container">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
    <div id="seoPagination"></div>

    <div id="seoModalRoot"></div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/seo', 'SEO Metadata & SERP Management', contentHtml);

  const searchInput = container.querySelector('#seoSearchInput');
  const filterBtn = container.querySelector('#seoFilterBtn');

  function updateParams(newParams) {
    const p = new URLSearchParams(query);
    Object.entries(newParams).forEach(([k, v]) => {
      if (v) p.set(k, v);
      else p.delete(k);
    });
    if (!('page' in newParams)) p.delete('page');
    window.location.hash = `#/admin/seo?${p.toString()}`;
  }

  filterBtn.addEventListener('click', () => {
    updateParams({ q: searchInput.value.trim() });
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      updateParams({ q: searchInput.value.trim() });
    }
  });

  const tableArea = container.querySelector('#seoTableArea');
  const paginationArea = container.querySelector('#seoPagination');

  try {
    const res = await api('/admin/documents', { query: { q: q || undefined, page, page_size: 20 }, signal });
    renderSeoTable(tableArea, paginationArea, res, (newPage) => {
      updateParams({ page: newPage });
    }, container);

    // If deep link provided #/admin/seo/:id, immediately open that document's SEO editor
    if (params && params.id) {
      try {
        const fullDoc = await api(`/admin/documents/${params.id}`, { signal });
        showSeoModal(container, fullDoc);
      } catch (err) {
        if (!signal?.aborted) {
          notify(`Failed to open document ${params.id}: ${err.message}`, { kind: 'error' });
        }
      }
    }
  } catch (err) {
    if (signal?.aborted) return;
    renderError(tableArea, err, { onRetry: () => renderSeoManager(container, routeContext) });
  }
}

function renderSeoTable(tableArea, paginationArea, data, onPageChange, container) {
  if (!data.items || data.items.length === 0) {
    tableArea.innerHTML = `
      <div class="empty-state" style="padding: 3rem; text-align: center;">
        <h3>No documents found</h3>
        <p class="text-muted">No documents match the search criteria.</p>
      </div>
    `;
    paginationArea.innerHTML = '';
    return;
  }

  const rowsHtml = data.items.map((doc) => {
    const hasSeoTitle = !!doc.seo_title;
    const hasSeoDesc = !!doc.seo_description;

    return `
      <tr data-doc-id="${doc.id}">
        <td style="max-width: 380px;">
          <div style="font-weight: 600; color: var(--color-ink);">${escapeText(doc.title)}</div>
          <div style="font-size: 0.8rem; color: var(--color-muted);">
            Category: ${escapeText(doc.category?.name || 'Uncategorized')}
          </div>
        </td>
        <td>
          ${hasSeoTitle ? `<span class="badge badge-success">Custom Title</span>` : '<span class="badge">Default</span>'}
        </td>
        <td>
          ${hasSeoDesc ? `<span class="badge badge-success">Custom Description</span>` : '<span class="badge">Default</span>'}
        </td>
        <td>
          <span class="badge ${doc.status === 'published' ? 'badge-success' : 'badge-warning'}">${escapeText(doc.status)}</span>
        </td>
        <td>
          <button class="btn btn-sm btn-secondary btn-edit-seo" data-doc-id="${doc.id}">Edit SEO</button>
        </td>
      </tr>
    `;
  }).join('');

  tableArea.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Document</th>
          <th>SEO Title</th>
          <th>Meta Description</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
    </table>
  `;

  renderPagination(paginationArea, {
    page: data.page,
    pageSize: data.page_size,
    total: data.total,
    onChange: onPageChange
  });

  tableArea.querySelectorAll('.btn-edit-seo').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const docId = e.target.dataset.docId;
      try {
        btn.disabled = true;
        const fullDoc = await api(`/admin/documents/${docId}`);
        showSeoModal(container, fullDoc);
      } catch (err) {
        notify(err.message || 'Failed to load document details', { kind: 'error' });
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function showSeoModal(container, doc) {
  const previousActiveElement = document.activeElement;
  const modalRoot = container.querySelector('#seoModalRoot');
  const seoTitle = doc.seo_title || '';
  const seoDesc = doc.seo_description || '';
  const seoKeywords = Array.isArray(doc.seo_keywords) ? doc.seo_keywords.join(', ') : (doc.seo_keywords || '');
  const coverAlt = doc.cover_image_alt || '';

  const siteOrigin = typeof window !== 'undefined' ? window.location.origin : 'https://folio.library';

  modalRoot.innerHTML = `
    <div class="modal-backdrop" id="seoBackdrop">
      <div class="modal-dialog card" role="dialog" aria-modal="true" aria-labelledby="seoModalTitle" style="max-width: 680px; margin: 4vh auto; padding: 1.5rem; max-height: 92vh; overflow-y: auto;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
          <h3 id="seoModalTitle" style="margin: 0;">SEO Metadata: ${escapeText(doc.title)}</h3>
          <button class="btn btn-sm btn-secondary" id="closeSeoBtn" aria-label="Close SEO Dialog">&times;</button>
        </div>

        <form id="seoEditForm">
          <!-- Google SERP Simulation Card -->
          <div style="margin-bottom: 1.5rem; background: #ffffff; border: 1px solid #dfe1e5; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
              <span style="font-size: 0.75rem; text-transform: uppercase; color: #5f6368; font-weight: 700;">
                Google SERP Simulation (Snippet Preview)
              </span>
              <span class="badge badge-sm badge-info">Illustrative</span>
            </div>
            <div style="font-size: 0.8rem; color: #202124; margin-bottom: 0.25rem;">
              <span style="color: #1a0dab; font-weight: 500;">folio.library</span> &rsaquo; research &rsaquo; ${escapeText(doc.category?.slug || 'doc')}
            </div>
            <div id="serpTitlePreview" style="color: #1a0dab; font-size: 1.15rem; font-weight: 400; line-height: 1.3; margin-bottom: 0.25rem; word-break: break-word;">
              ${escapeText(seoTitle || doc.title)} — Folio Research
            </div>
            <div id="serpDescPreview" style="color: #4d5156; font-size: 0.85rem; line-height: 1.4; word-break: break-word;">
              ${escapeText(seoDesc || doc.summary || 'No description configured. Search engines construct snippet from page body.')}
            </div>
          </div>

          <!-- SEO Simulation Disclaimer -->
          <div class="notice" style="margin-bottom: 1.25rem; font-size: 0.8rem; line-height: 1.4; background: var(--color-bg); border-left: 3px solid var(--color-accent); padding: 0.6rem 0.75rem;">
            <strong>Search Engine Notice:</strong> This preview illustrates metadata tags. Due to client-side hash routing and search crawler algorithms, actual search engine rendering and snippets cannot be guaranteed to appear identically.
          </div>

          <div class="field" style="margin-bottom: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <label class="label" for="inputSeoTitle">Meta Title (SEO Title)</label>
              <span id="seoTitleCounter" style="font-size: 0.75rem; color: var(--color-muted);">0 / 60</span>
            </div>
            <input type="text" id="inputSeoTitle" class="input" placeholder="Custom page title for search engine result headers..." value="${escapeAttr(seoTitle)}" />
            <div class="form-help">Leave empty to use default document title. Optimal length: 50–60 characters.</div>
          </div>

          <div class="field" style="margin-bottom: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <label class="label" for="inputSeoDesc">Meta Description</label>
              <span id="seoDescCounter" style="font-size: 0.75rem; color: var(--color-muted);">0 / 160</span>
            </div>
            <textarea id="inputSeoDesc" class="textarea" rows="3" placeholder="Succinct summary of the document for search results...">${escapeText(seoDesc)}</textarea>
            <div class="form-help">Optimal length: 130–160 characters.</div>
          </div>

          <div class="field" style="margin-bottom: 1rem;">
            <label class="label" for="inputSeoKeywords">Keywords (comma-separated)</label>
            <input type="text" id="inputSeoKeywords" class="input" placeholder="e.g. computer science, algorithms, machine learning" value="${escapeAttr(seoKeywords)}" />
          </div>

          <div class="field" style="margin-bottom: 1.5rem;">
            <label class="label" for="inputCoverAlt">Cover Image Alt Text</label>
            <input type="text" id="inputCoverAlt" class="input" placeholder="Accessible descriptive text for the cover image..." value="${escapeAttr(coverAlt)}" />
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 0.5rem;">
            <button type="button" class="btn btn-secondary" id="cancelSeoBtn">Cancel</button>
            <button type="submit" class="btn btn-primary" id="saveSeoBtn">Save SEO Metadata</button>
          </div>
        </form>
      </div>
    </div>
  `;

  const backdrop = modalRoot.querySelector('#seoBackdrop');
  const closeBtn = modalRoot.querySelector('#closeSeoBtn');
  const cancelBtn = modalRoot.querySelector('#cancelSeoBtn');
  const form = modalRoot.querySelector('#seoEditForm');
  const saveBtn = modalRoot.querySelector('#saveSeoBtn');

  const inputTitle = modalRoot.querySelector('#inputSeoTitle');
  const inputDesc = modalRoot.querySelector('#inputSeoDesc');
  const inputKeywords = modalRoot.querySelector('#inputSeoKeywords');
  const inputAlt = modalRoot.querySelector('#inputCoverAlt');

  const serpTitle = modalRoot.querySelector('#serpTitlePreview');
  const serpDesc = modalRoot.querySelector('#serpDescPreview');
  const titleCounter = modalRoot.querySelector('#seoTitleCounter');
  const descCounter = modalRoot.querySelector('#seoDescCounter');

  function updateCountersAndPreview() {
    const tVal = inputTitle.value.trim();
    const dVal = inputDesc.value.trim();

    titleCounter.textContent = `${tVal.length} / 60`;
    descCounter.textContent = `${dVal.length} / 160`;

    serpTitle.textContent = tVal ? `${tVal} — Folio Research` : `${doc.title} — Folio Research`;
    serpDesc.textContent = dVal || doc.summary || 'No description configured.';
  }

  inputTitle.addEventListener('input', updateCountersAndPreview);
  inputDesc.addEventListener('input', updateCountersAndPreview);
  updateCountersAndPreview();

  function closeModal() {
    document.removeEventListener('keydown', keydownTrapHandler);
    modalRoot.innerHTML = '';
    if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
      previousActiveElement.focus();
    }
  }

  function keydownTrapHandler(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeModal();
      return;
    }
    if (e.key === 'Tab') {
      const dialog = modalRoot.querySelector('.modal-dialog');
      if (!dialog) return;
      const focusables = Array.from(dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'))
        .filter(el => !el.disabled && el.offsetParent !== null);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
  document.addEventListener('keydown', keydownTrapHandler);
  setTimeout(() => {
    inputTitle?.focus();
  }, 50);

  closeBtn.addEventListener('click', closeModal);
  cancelBtn.addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeModal();
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const newTitle = inputTitle.value.trim() || null;
    const newDesc = inputDesc.value.trim() || null;
    const newAlt = inputAlt.value.trim() || null;
    const rawKeywords = inputKeywords.value.trim();
    const keywordsArr = rawKeywords ? rawKeywords.split(',').map((k) => k.trim()).filter(Boolean) : [];

    try {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';
      await api(`/admin/documents/${doc.id}/seo`, {
        method: 'PATCH',
        body: {
          seo_title: newTitle,
          seo_description: newDesc,
          seo_keywords: keywordsArr,
          cover_image_alt: newAlt,
        }
      });
      notify('SEO metadata updated successfully.', { kind: 'success' });
      closeModal();
      renderSeoManager(container, { query: new URLSearchParams(window.location.hash.split('?')[1] || '') });
    } catch (err) {
      notify(err.message || 'Failed to update SEO metadata', { kind: 'error' });
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save SEO Metadata';
    }
  });
}

// ==============================================================================
// 2. Library Analytics Dashboard (Actual Server Metrics & Period Breakdown)
// ==============================================================================

export async function renderAnalyticsDashboard(container, routeContext) {
  if (!can('analytics:read')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/analytics',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have analytics read permissions.</p></div>'
    );
    return;
  }

  const { query, signal } = routeContext;
  const days = parseInt(query.get('days') || '30', 10);

  document.title = 'Library Analytics — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div style="display: flex; gap: 0.5rem; align-items: center;">
        <span style="font-size: 0.85rem; font-weight: 600; color: var(--color-muted);">Filter Period:</span>
        <button class="btn btn-sm ${days === 7 ? 'btn-primary' : 'btn-secondary'} btn-period" data-days="7">Last 7 Days</button>
        <button class="btn btn-sm ${days === 30 ? 'btn-primary' : 'btn-secondary'} btn-period" data-days="30">Last 30 Days</button>
        <button class="btn btn-sm ${days === 90 ? 'btn-primary' : 'btn-secondary'} btn-period" data-days="90">Last 90 Days</button>
      </div>
      ${can('seo:write') ? `<a href="#/admin/seo" class="btn btn-secondary">SEO Management &rarr;</a>` : ''}
    </div>

    <div id="analyticsBodyArea">
      <div style="text-align: center; padding: 4rem;"><span class="spinner"></span></div>
    </div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/analytics', 'Library Analytics & Search Metrics', contentHtml);

  container.querySelectorAll('.btn-period').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const selectedDays = e.target.dataset.days;
      window.location.hash = `#/admin/analytics?days=${selectedDays}`;
    });
  });

  const bodyArea = container.querySelector('#analyticsBodyArea');

  try {
    const dateTo = new Date().toISOString().split('T')[0];
    const dateFromObj = new Date();
    dateFromObj.setDate(dateFromObj.getDate() - days);
    const dateFrom = dateFromObj.toISOString().split('T')[0];

    const data = await api('/admin/analytics/overview', {
      query: { date_from: dateFrom, date_to: dateTo },
      signal,
    });

    renderAnalyticsContent(bodyArea, data);
  } catch (err) {
    if (signal?.aborted) return;
    renderError(bodyArea, err, { onRetry: () => renderAnalyticsDashboard(container, routeContext) });
  }
}

function renderAnalyticsContent(container, data) {
  const totals = data.totals || {};
  const daily = data.daily || [];
  const topQueries = data.top_queries || [];
  const topDocs = data.top_documents || [];

  const totalsHtml = `
    <div class="analytics-totals-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
      <div class="card" style="padding: 1.25rem; border-left: 4px solid var(--color-text);">
        <div style="font-size: 0.8rem; text-transform: uppercase; color: var(--color-muted); font-weight: 700;">Published Documents</div>
        <div style="font-size: 2.25rem; font-weight: 700; color: var(--color-text); margin-top: 0.25rem;">
          ${totals.published_documents || 0}
        </div>
      </div>
      <div class="card" style="padding: 1.25rem; border-left: 4px solid var(--color-accent);">
        <div style="font-size: 0.8rem; text-transform: uppercase; color: var(--color-muted); font-weight: 700;">Search Requests</div>
        <div style="font-size: 2.25rem; font-weight: 700; color: var(--color-accent); margin-top: 0.25rem;">
          ${totals.search_requests || 0}
        </div>
      </div>
      <div class="card" style="padding: 1.25rem; border-left: 4px solid #b7791f;">
        <div style="font-size: 0.8rem; text-transform: uppercase; color: var(--color-muted); font-weight: 700;">Result Clicks</div>
        <div style="font-size: 2.25rem; font-weight: 700; color: #b7791f; margin-top: 0.25rem;">
          ${totals.result_clicks || 0}
        </div>
      </div>
      <div class="card" style="padding: 1.25rem; border-left: 4px solid #4a5568;">
        <div style="font-size: 0.8rem; text-transform: uppercase; color: var(--color-muted); font-weight: 700;">Document Views</div>
        <div style="font-size: 2.25rem; font-weight: 700; color: #4a5568; margin-top: 0.25rem;">
          ${totals.document_views || 0}
        </div>
      </div>
    </div>
  `;

  // Render SVG Trend Chart
  const chartHtml = renderSvgActivityChart(daily);

  // Top Queries Table
  const topQueriesHtml = topQueries.length > 0 ? `
    <table class="table">
      <thead>
        <tr>
          <th>#</th>
          <th>Search Query</th>
          <th style="text-align: right;">Searches</th>
          <th style="text-align: right;">Result Clicks</th>
        </tr>
      </thead>
      <tbody>
        ${topQueries.map((q, idx) => `
          <tr>
            <td style="color: var(--color-muted); width: 40px;">${idx + 1}</td>
            <td style="font-weight: 600;">${escapeText(q.query_string)}</td>
            <td style="text-align: right;">${q.search_requests}</td>
            <td style="text-align: right;">${q.result_clicks}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  ` : '<div class="empty-state" style="padding: 2rem; text-align: center; color: var(--color-muted);">No search queries recorded in this period.</div>';

  // Top Documents Table
  const topDocsHtml = topDocs.length > 0 ? `
    <table class="table">
      <thead>
        <tr>
          <th>#</th>
          <th>Document</th>
          <th style="text-align: right;">Views</th>
          <th style="text-align: right;">Clicks</th>
        </tr>
      </thead>
      <tbody>
        ${topDocs.map((d, idx) => `
          <tr>
            <td style="color: var(--color-muted); width: 40px;">${idx + 1}</td>
            <td>
              <a href="#/documents/${d.id}" target="_blank" style="font-weight: 600; color: var(--color-text); text-decoration: underline;">
                ${escapeText(d.title)}
              </a>
            </td>
            <td style="text-align: right;">${d.document_views}</td>
            <td style="text-align: right;">${d.result_clicks}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  ` : '<div class="empty-state" style="padding: 2rem; text-align: center; color: var(--color-muted);">No document view events recorded in this period.</div>';

  // Daily Activity Breakdown Table (showing up to 14 latest days)
  const displayDaily = daily.slice(-14).reverse();
  const dailyRowsHtml = displayDaily.map((d) => `
    <tr>
      <td style="font-weight: 600;">${escapeText(d.date)}</td>
      <td style="text-align: right;">${d.search_requests}</td>
      <td style="text-align: right;">${d.result_clicks}</td>
      <td style="text-align: right;">${d.document_views}</td>
    </tr>
  `).join('');

  const dailyTableHtml = `
    <div class="card" style="padding: 1.25rem; margin-top: 1.5rem;">
      <h3 style="margin-top: 0; margin-bottom: 0.75rem;">Daily Activity Breakdown</h3>
      <div class="table-container">
        <table class="table">
          <thead>
            <tr>
              <th>Date</th>
              <th style="text-align: right;">Search Requests</th>
              <th style="text-align: right;">Result Clicks</th>
              <th style="text-align: right;">Document Views</th>
            </tr>
          </thead>
          <tbody>
            ${dailyRowsHtml || '<tr><td colspan="4" style="text-align: center;">No daily records</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
  `;

  container.innerHTML = `
    ${totalsHtml}

    ${chartHtml}

    <div class="analytics-split-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-top: 1.5rem;">
      <div class="card" style="padding: 1.25rem;">
        <h3 style="margin-top: 0; margin-bottom: 0.75rem;">Top Search Queries</h3>
        <div class="table-container">
          ${topQueriesHtml}
        </div>
      </div>

      <div class="card" style="padding: 1.25rem;">
        <h3 style="margin-top: 0; margin-bottom: 0.75rem;">Top Read Documents</h3>
        <div class="table-container">
          ${topDocsHtml}
        </div>
      </div>
    </div>

    ${dailyTableHtml}
  `;
}

function renderSvgActivityChart(daily) {
  if (!daily || daily.length === 0) {
    return '';
  }

  const maxVal = Math.max(
    1,
    ...daily.map((d) => Math.max(d.search_requests || 0, d.result_clicks || 0, d.document_views || 0))
  );

  const plotHeight = 220;
  const leftMargin = 45;
  const topMargin = 15;
  const bottomMargin = 35;
  const rightMargin = 20;

  const barWidth = 10;
  const groupGap = 12;
  const barGroupWidth = barWidth * 3 + groupGap;
  const totalPlotWidth = daily.length * barGroupWidth;
  const svgWidth = Math.max(800, totalPlotWidth + leftMargin + rightMargin);
  const svgHeight = plotHeight + topMargin + bottomMargin;

  // Horizontal Grid Lines & Y-Axis Labels
  const ySteps = 4;
  let gridLines = '';
  for (let s = 0; s <= ySteps; s++) {
    const stepVal = Math.round((maxVal / ySteps) * s);
    const yPos = topMargin + plotHeight - Math.round((stepVal / maxVal) * plotHeight);
    gridLines += `
      <line x1="${leftMargin}" y1="${yPos}" x2="${svgWidth - rightMargin}" y2="${yPos}" stroke="#E6ECE9" stroke-width="1" stroke-dasharray="3 3" />
      <text x="${leftMargin - 10}" y="${yPos + 4}" font-size="11" font-family="var(--font-ui)" text-anchor="end" fill="#6B7C85">${stepVal}</text>
    `;
  }

  // Determine tick decimation interval based on number of days
  const tickInterval = daily.length > 60 ? 7 : (daily.length > 20 ? 3 : 1);

  const bars = daily.map((d, i) => {
    const x = leftMargin + i * barGroupWidth;
    const hSearch = Math.round(((d.search_requests || 0) / maxVal) * plotHeight);
    const hClicks = Math.round(((d.result_clicks || 0) / maxVal) * plotHeight);
    const hViews = Math.round(((d.document_views || 0) / maxVal) * plotHeight);

    const ySearch = topMargin + plotHeight - hSearch;
    const yClicks = topMargin + plotHeight - hClicks;
    const yViews = topMargin + plotHeight - hViews;

    const shortDate = d.date.slice(5); // MM-DD
    const showLabel = (i % tickInterval === 0) || (i === daily.length - 1);

    return `
      <g transform="translate(${x}, 0)">
        <rect x="0" y="${ySearch}" width="${barWidth}" height="${hSearch}" fill="var(--color-accent)" rx="2">
          <title>${d.date} - Searches: ${d.search_requests || 0}</title>
        </rect>
        <rect x="${barWidth}" y="${yClicks}" width="${barWidth}" height="${hClicks}" fill="#B7791F" rx="2">
          <title>${d.date} - Clicks: ${d.result_clicks || 0}</title>
        </rect>
        <rect x="${barWidth * 2}" y="${yViews}" width="${barWidth}" height="${hViews}" fill="#2B6CB0" rx="2">
          <title>${d.date} - Views: ${d.document_views || 0}</title>
        </rect>
        ${showLabel ? `
          <text x="${barWidth * 1.5}" y="${topMargin + plotHeight + 18}" font-size="11" font-family="var(--font-ui)" text-anchor="middle" fill="#5E717D">${shortDate}</text>
        ` : ''}
      </g>
    `;
  }).join('');

  return `
    <div class="card" style="padding: 1.5rem; margin-bottom: 2rem;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem;">
        <h3 style="margin: 0; font-size: 1.1rem; font-family: var(--font-ui); font-weight: 600;">Interaction Volume Over Period</h3>
        <div style="display: flex; gap: 1.25rem; font-size: 0.825rem; font-weight: 500;">
          <span style="display: flex; align-items: center; gap: 0.4rem;"><span style="width: 10px; height: 10px; background: var(--color-accent); display: inline-block; border-radius: 2px;"></span> Search Requests</span>
          <span style="display: flex; align-items: center; gap: 0.4rem;"><span style="width: 10px; height: 10px; background: #B7791F; display: inline-block; border-radius: 2px;"></span> Result Clicks</span>
          <span style="display: flex; align-items: center; gap: 0.4rem;"><span style="width: 10px; height: 10px; background: #2B6CB0; display: inline-block; border-radius: 2px;"></span> Document Views</span>
        </div>
      </div>
      <div style="overflow-x: auto; padding-bottom: 0.5rem;">
        <svg viewBox="0 0 ${svgWidth} ${svgHeight}" style="min-width: ${Math.min(svgWidth, 1000)}px; width: 100%; height: ${svgHeight}px; display: block;">
          ${gridLines}
          ${bars}
        </svg>
      </div>
    </div>
  `;
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
