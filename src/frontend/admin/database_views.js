// src/frontend/admin/database_views.js
// Read-Only PostgreSQL Database Explorer for Folio Admin

import { api } from '../core/api.js';
import { can } from '../core/session.js';
import { renderPagination, renderError } from '../core/ui.js';
import { wrapAdminLayout } from './admin_shell.js';

export async function renderDatabaseExplorer(container, routeContext) {
  if (!can('settings:write') && !can('audit:read')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/database',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have permission to inspect the database.</p></div>'
    );
    return;
  }

  const { query, signal } = routeContext;
  const selectedTable = query.get('table') || '';
  const page = parseInt(query.get('page') || '1', 10);

  document.title = 'Database Explorer — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar" style="justify-content: space-between; gap: 1rem; flex-wrap: wrap;">
      <div id="dbSummaryMeta" style="font-size: 0.9rem; color: var(--color-muted);">
        Loading database metadata...
      </div>
      <div style="display: flex; gap: 0.5rem; align-items: center;">
        <a href="/docs" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm">
          Swagger UI (/docs) &nearr;
        </a>
        <a href="/health/ready" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm">
          Health JSON &nearr;
        </a>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: minmax(220px, 260px) 1fr; gap: 1.25rem; align-items: start;">
      <div class="card" style="padding: 0.75rem;">
        <div style="font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-muted); padding: 0.25rem 0.5rem 0.6rem;">
          Tables
        </div>
        <div id="dbTablesList">
          <div style="text-align: center; padding: 1.5rem;"><span class="spinner"></span></div>
        </div>
      </div>

      <div>
        <div id="dbRowsArea" class="table-container" style="overflow-x: auto;">
          <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
        </div>
        <div id="dbPagination"></div>
      </div>
    </div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/database', 'Database Explorer (Read-Only)', contentHtml);

  const summaryMeta = container.querySelector('#dbSummaryMeta');
  const tablesList = container.querySelector('#dbTablesList');
  const rowsArea = container.querySelector('#dbRowsArea');
  const paginationArea = container.querySelector('#dbPagination');

  function selectTable(tableName, targetPage = 1) {
    const params = new URLSearchParams();
    params.set('table', tableName);
    if (targetPage > 1) params.set('page', String(targetPage));
    window.location.hash = `#/admin/database?${params.toString()}`;
  }

  try {
    const meta = await api('/admin/database/tables', { signal });
    const tables = meta.tables || [];
    summaryMeta.innerHTML = `
      <strong>Dialect:</strong> ${escapeHtml(meta.dialect || 'unknown')}
      &nbsp;&middot;&nbsp;
      <strong>Database:</strong> ${escapeHtml(meta.database || 'default')}
      &nbsp;&middot;&nbsp;
      <strong>Tables:</strong> ${tables.length}
    `;

    if (tables.length === 0) {
      tablesList.innerHTML = '<p style="padding: 0.5rem; color: var(--color-muted); font-size: 0.875rem;">No tables found.</p>';
      rowsArea.innerHTML = '<div style="padding: 2rem; text-align: center; color: var(--color-muted);">No database tables available.</div>';
      return;
    }

    const activeTable = selectedTable && tables.some((t) => t.name === selectedTable)
      ? selectedTable
      : tables[0].name;

    tablesList.innerHTML = `
      <ul style="list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem;">
        ${tables.map((t) => {
          const isActive = t.name === activeTable;
          return `
            <li>
              <button
                type="button"
                class="btn btn-sm db-table-btn ${isActive ? 'btn-primary' : 'btn-secondary'}"
                data-table="${escapeAttr(t.name)}"
                style="width: 100%; display: flex; justify-content: space-between; align-items: center; text-align: left; font-family: monospace; font-size: 0.82rem;"
              >
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(t.name)}</span>
                <span style="opacity: 0.8; font-size: 0.75rem; margin-left: 0.5rem;">${t.row_count}</span>
              </button>
            </li>
          `;
        }).join('')}
      </ul>
    `;

    tablesList.querySelectorAll('.db-table-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        selectTable(btn.dataset.table, 1);
      });
    });

    const tableData = await api(`/admin/database/tables/${encodeURIComponent(activeTable)}`, {
      query: { page, page_size: 25 },
      signal,
    });

    renderTableRows(rowsArea, paginationArea, tableData, (newPage) => {
      selectTable(activeTable, newPage);
    });
  } catch (err) {
    if (signal?.aborted) return;
    renderError(rowsArea, err, { onRetry: () => renderDatabaseExplorer(container, routeContext) });
  }
}

function renderTableRows(rowsArea, paginationArea, data, onPageChange) {
  const columns = data.columns || [];
  const rows = data.rows || [];

  const headerInfo = `
    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1rem; border-bottom: 1px solid var(--color-border); background: var(--color-surface);">
      <div>
        <strong style="font-family: monospace;">${escapeHtml(data.table)}</strong>
        <span style="margin-left: 0.75rem; font-size: 0.85rem; color: var(--color-muted);">
          ${data.total} rows &middot; ${columns.length} columns
        </span>
      </div>
      <span style="font-size: 0.8rem; color: var(--color-muted);">Sensitive columns masked</span>
    </div>
  `;

  if (rows.length === 0) {
    rowsArea.innerHTML = `
      ${headerInfo}
      <div style="padding: 2.5rem; text-align: center; color: var(--color-muted);">
        Table <code>${escapeHtml(data.table)}</code> is empty (0 rows).
      </div>
    `;
    paginationArea.innerHTML = '';
    return;
  }

  const theadHtml = columns.map((c) => `
    <th style="white-space: nowrap; font-family: monospace; font-size: 0.8rem;">
      ${escapeHtml(c.name)}
      <div style="font-weight: 400; font-size: 0.7rem; color: var(--color-muted);">${escapeHtml(c.type)}</div>
    </th>
  `).join('');

  const tbodyHtml = rows.map((row) => `
    <tr>
      ${columns.map((c) => {
        const val = row[c.name];
        const display = val === null || val === undefined
          ? '<span style="color: var(--color-muted); font-style: italic;">NULL</span>'
          : typeof val === 'object'
            ? `<code style="font-size: 0.78rem;">${escapeHtml(JSON.stringify(val))}</code>`
            : escapeHtml(String(val));
        return `<td style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.82rem;" title="${escapeAttr(val === null || val === undefined ? 'NULL' : (typeof val === 'object' ? JSON.stringify(val) : String(val)))}">${display}</td>`;
      }).join('')}
    </tr>
  `).join('');

  rowsArea.innerHTML = `
    ${headerInfo}
    <table class="data-table">
      <thead><tr>${theadHtml}</tr></thead>
      <tbody>${tbodyHtml}</tbody>
    </table>
  `;

  renderPagination(paginationArea, {
    page: data.page,
    pageSize: data.page_size,
    total: data.total,
    onChange: onPageChange,
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
