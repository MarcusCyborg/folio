// src/frontend/admin/governance_views.js
// Governance: User Directory, RBAC Permissions Matrix, Audit Trail, Global Settings

import { api, ApiError } from '../core/api.js';
import { can, refreshSession } from '../core/session.js';
import { notify, confirmAction, renderPagination, renderError } from '../core/ui.js';
import { wrapAdminLayout } from './admin_shell.js';
import { loadPublicSettings } from '../app.js';

// ==============================================================================
// 1. Users & Staff Management (with Last Super Admin Protection)
// ==============================================================================

export async function renderUsersManager(container, routeContext) {
  if (!can('users:manage')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/users',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have user management permissions.</p></div>'
    );
    return;
  }

  const { query, signal } = routeContext;
  const q = query.get('q') || '';
  const roleFilter = query.get('role') || '';
  const page = parseInt(query.get('page') || '1', 10);

  document.title = 'User Directory — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; flex: 1; max-width: 650px;">
        <input type="search" id="userSearchInput" class="input" style="flex: 2; min-width: 200px;" placeholder="Search by username or email..." value="${escapeAttr(q)}" />
        <select id="userRoleFilter" class="select" style="flex: 1; min-width: 160px;">
          <option value="" ${!roleFilter ? 'selected' : ''}>All Roles</option>
          <option value="super_admin" ${roleFilter === 'super_admin' ? 'selected' : ''}>Super Admin</option>
          <option value="content_manager" ${roleFilter === 'content_manager' ? 'selected' : ''}>Content Manager</option>
          <option value="moderator" ${roleFilter === 'moderator' ? 'selected' : ''}>Moderator</option>
          <option value="data_seo" ${roleFilter === 'data_seo' ? 'selected' : ''}>Data & SEO</option>
          <option value="member" ${roleFilter === 'member' ? 'selected' : ''}>Member</option>
        </select>
        <button class="btn btn-secondary" id="userFilterBtn">Filter</button>
      </div>
      ${can('roles:manage') ? `<a href="#/admin/roles" class="btn btn-secondary">Permissions Matrix &rarr;</a>` : ''}
    </div>

    <div id="usersTableArea" class="table-container">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
    <div id="usersPagination"></div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/users', 'Users & Staff Directory', contentHtml);

  const searchInput = container.querySelector('#userSearchInput');
  const roleSelect = container.querySelector('#userRoleFilter');
  const filterBtn = container.querySelector('#userFilterBtn');

  function updateParams(newParams) {
    const params = new URLSearchParams(query);
    Object.entries(newParams).forEach(([k, v]) => {
      if (v) params.set(k, v);
      else params.delete(k);
    });
    if (!('page' in newParams)) params.delete('page');
    window.location.hash = `#/admin/users?${params.toString()}`;
  }

  filterBtn.addEventListener('click', () => {
    updateParams({ q: searchInput.value.trim(), role: roleSelect.value });
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      updateParams({ q: searchInput.value.trim(), role: roleSelect.value });
    }
  });

  const tableArea = container.querySelector('#usersTableArea');
  const paginationArea = container.querySelector('#usersPagination');

  try {
    const queryParams = { page, page_size: 20 };
    if (q) queryParams.q = q;
    if (roleFilter) queryParams.role_key = roleFilter;

    const res = await api('/admin/users', { query: queryParams, signal });
    renderUsersTable(tableArea, paginationArea, res, (newPage) => {
      updateParams({ page: newPage });
    }, container);
  } catch (err) {
    if (signal?.aborted) return;
    renderError(tableArea, err, { onRetry: () => renderUsersManager(container, routeContext) });
  }
}

function renderUsersTable(tableArea, paginationArea, data, onPageChange, container) {
  if (!data.items || data.items.length === 0) {
    tableArea.innerHTML = `
      <div class="empty-state" style="padding: 3rem; text-align: center;">
        <h3>No users found</h3>
        <p class="text-muted">No accounts match the selected search or role criteria.</p>
      </div>
    `;
    paginationArea.innerHTML = '';
    return;
  }

  const roleOptions = [
    { key: 'super_admin', label: 'Super Admin' },
    { key: 'content_manager', label: 'Content Manager' },
    { key: 'moderator', label: 'Moderator' },
    { key: 'data_seo', label: 'Data & SEO' },
    { key: 'member', label: 'Member' },
  ];

  const rowsHtml = data.items.map((u) => {
    const isSuspended = u.commenting_suspended_until && new Date(u.commenting_suspended_until) > new Date();
    const createdDate = new Date(u.created_at).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });

    const roleSelectHtml = `
      <select class="select select-sm user-role-select" data-user-id="${u.id}" data-current-role="${u.role_key}">
        ${roleOptions.map((opt) => `
          <option value="${opt.key}" ${u.role_key === opt.key ? 'selected' : ''}>${opt.label}</option>
        `).join('')}
      </select>
    `;

    return `
      <tr data-user-id="${u.id}">
        <td>
          <div style="font-weight: 600; color: var(--color-ink);">${escapeText(u.display_name || u.username)}</div>
          <div style="font-size: 0.8rem; color: var(--color-muted);">@${escapeText(u.username)}</div>
        </td>
        <td>
          <span style="font-family: monospace; font-size: 0.85rem;">${escapeText(u.email)}</span>
        </td>
        <td>${roleSelectHtml}</td>
        <td>
          <label style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer;">
            <input type="checkbox" class="user-active-toggle" data-user-id="${u.id}" ${u.is_active ? 'checked' : ''} />
            <span class="badge ${u.is_active ? 'badge-success' : 'badge-danger'}">
              ${u.is_active ? 'Active' : 'Disabled'}
            </span>
          </label>
        </td>
        <td>
          ${isSuspended
            ? `<span class="badge badge-warning" title="Suspended until ${u.commenting_suspended_until}">Suspended</span>`
            : '<span class="badge badge-success">Normal</span>'
          }
        </td>
        <td style="font-size: 0.85rem; color: var(--color-muted); white-space: nowrap;">${createdDate}</td>
      </tr>
    `;
  }).join('');

  tableArea.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>User</th>
          <th>Email</th>
          <th>Role</th>
          <th>Status</th>
          <th>Commenting</th>
          <th>Joined</th>
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

  // Handle Role Change with Last Super Admin Protection
  tableArea.querySelectorAll('.user-role-select').forEach((sel) => {
    sel.addEventListener('change', async (e) => {
      const userId = e.target.dataset.userId;
      const prevRole = e.target.dataset.currentRole;
      const newRole = e.target.value;

      try {
        sel.disabled = true;
        await api(`/admin/users/${userId}`, {
          method: 'PATCH',
          body: { role_key: newRole }
        });
        e.target.dataset.currentRole = newRole;
        notify('User role updated successfully.', { kind: 'success' });
      } catch (err) {
        // Handle 409 Conflict (e.g. Cannot demote last active super admin) or any error
        notify(err.message || 'Failed to update user role', { kind: 'error' });
        // Revert select back to prevRole
        e.target.value = prevRole;
      } finally {
        sel.disabled = false;
      }
    });
  });

  // Handle Active Toggle with Last Super Admin Protection
  tableArea.querySelectorAll('.user-active-toggle').forEach((chk) => {
    chk.addEventListener('change', async (e) => {
      const userId = e.target.dataset.userId;
      const newActive = e.target.checked;
      const badge = e.target.parentElement.querySelector('.badge');

      try {
        chk.disabled = true;
        await api(`/admin/users/${userId}`, {
          method: 'PATCH',
          body: { is_active: newActive }
        });
        badge.className = `badge ${newActive ? 'badge-success' : 'badge-danger'}`;
        badge.textContent = newActive ? 'Active' : 'Disabled';
        notify(newActive ? 'User account activated.' : 'User account disabled.', { kind: 'success' });
      } catch (err) {
        // Handle 409 Conflict (e.g. Cannot deactivate last active super admin)
        notify(err.message || 'Failed to update account status', { kind: 'error' });
        e.target.checked = !newActive;
      } finally {
        chk.disabled = false;
      }
    });
  });
}

// ==============================================================================
// 2. Roles & Permissions Matrix
// ==============================================================================

export async function renderRolesMatrix(container, routeContext) {
  if (!can('roles:manage')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/roles',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have role management permissions.</p></div>'
    );
    return;
  }

  const { signal } = routeContext;
  document.title = 'Roles & Permissions Matrix — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div>
        <p style="margin: 0; color: var(--color-muted); font-size: 0.9rem;">
          Configure granular capability permissions for each role. Note: <strong>super_admin</strong> permissions are protected.
        </p>
      </div>
      <a href="#/admin/users" class="btn btn-secondary">&larr; User Directory</a>
    </div>

    <div id="rolesMatrixArea" class="table-container">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/roles', 'Roles & Permissions Matrix', contentHtml);

  const matrixArea = container.querySelector('#rolesMatrixArea');

  try {
    const [rolesData, permsData] = await Promise.all([
      api('/admin/roles', { signal }),
      api('/admin/permissions', { signal }),
    ]);

    renderMatrixTable(matrixArea, rolesData.items, permsData.items, container);
  } catch (err) {
    if (signal?.aborted) return;
    renderError(matrixArea, err, { onRetry: () => renderRolesMatrix(container, routeContext) });
  }
}

function renderMatrixTable(matrixArea, roles, permissions, container) {
  const roleOrder = ['super_admin', 'content_manager', 'moderator', 'data_seo', 'member'];
  roles.sort((a, b) => {
    const idxA = roleOrder.indexOf(a.key);
    const idxB = roleOrder.indexOf(b.key);
    return (idxA !== -1 ? idxA : 99) - (idxB !== -1 ? idxB : 99);
  });

  const headersHtml = roles.map((r) => `
    <th style="text-align: center; min-width: 140px;">
      <div>${escapeText(r.label || r.key)}</div>
      <div style="font-size: 0.75rem; font-weight: normal; color: var(--color-muted); margin-top: 0.15rem;">
        ${r.protected || r.key === 'super_admin' ? '<span class="badge badge-sm badge-info">Protected</span>' : `<code>${escapeText(r.key)}</code>`}
      </div>
    </th>
  `).join('');

  const rowsHtml = permissions.map((p) => {
    const cellsHtml = roles.map((r) => {
      const hasPerm = r.permissions && r.permissions.includes(p.key);
      const isProtected = r.protected || r.key === 'super_admin';

      return `
        <td style="text-align: center;">
          <input 
            type="checkbox" 
            class="matrix-perm-check" 
            data-role-key="${r.key}" 
            data-perm-key="${p.key}"
            ${hasPerm ? 'checked' : ''}
            ${isProtected ? 'disabled title="Protected Super Admin permission"' : ''}
          />
        </td>
      `;
    }).join('');

    return `
      <tr>
        <td>
          <div style="font-weight: 600;"><code>${escapeText(p.key)}</code></div>
          <div style="font-size: 0.8rem; color: var(--color-muted);">${escapeText(p.description || '')}</div>
        </td>
        ${cellsHtml}
      </tr>
    `;
  }).join('');

  const actionFootersHtml = roles.map((r) => {
    if (r.protected || r.key === 'super_admin') {
      return '<td style="text-align: center;"><span class="text-muted" style="font-size: 0.8rem; color: var(--color-muted);">Protected</span></td>';
    }
    return `
      <td style="text-align: center;">
        <button class="btn btn-sm btn-primary btn-save-role-perms" data-role-key="${r.key}">Save ${escapeText(r.label || r.key)}</button>
      </td>
    `;
  }).join('');

  matrixArea.innerHTML = `
    <table class="table matrix-table">
      <thead>
        <tr>
          <th style="min-width: 260px;">Permission Capability</th>
          ${headersHtml}
        </tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
      <tfoot>
        <tr style="background: var(--color-bg);">
          <td style="font-weight: 600;">Save Action</td>
          ${actionFootersHtml}
        </tr>
      </tfoot>
    </table>
  `;

  // Bind Save Buttons per role
  matrixArea.querySelectorAll('.btn-save-role-perms').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const roleKey = e.target.dataset.roleKey;
      const checkedBoxes = matrixArea.querySelectorAll(`.matrix-perm-check[data-role-key="${roleKey}"]:checked`);
      const selectedPerms = Array.from(checkedBoxes).map((chk) => chk.dataset.permKey);

      try {
        btn.disabled = true;
        btn.textContent = 'Saving...';
        await api(`/admin/roles/${roleKey}/permissions`, {
          method: 'PUT',
          body: { permissions: selectedPerms }
        });
        notify(`Permissions saved for ${roleKey}.`, { kind: 'success' });
        // Refresh session context in case current user's active permissions changed
        await refreshSession();
      } catch (err) {
        notify(err.message || `Failed to update permissions for ${roleKey}`, { kind: 'error' });
      } finally {
        btn.disabled = false;
        btn.textContent = `Save ${roleKey}`;
      }
    });
  });
}

// ==============================================================================
// 3. Audit Trail Viewer (with Safe Redacted Diff Viewer)
// ==============================================================================

export async function renderAuditLogs(container, routeContext) {
  if (!can('audit:read')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/audit',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have audit read permissions.</p></div>'
    );
    return;
  }

  const { query, signal } = routeContext;
  const actionFilter = query.get('action') || '';
  const dateFrom = query.get('date_from') || '';
  const dateTo = query.get('date_to') || '';
  const page = parseInt(query.get('page') || '1', 10);

  document.title = 'Audit Trail — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; flex: 1;">
        <input type="text" id="auditActionInput" class="input" style="max-width: 220px;" placeholder="Filter by action (e.g. document:)" value="${escapeAttr(actionFilter)}" />
        <input type="date" id="auditDateFrom" class="input" style="max-width: 160px;" value="${escapeAttr(dateFrom)}" title="Date From" />
        <input type="date" id="auditDateTo" class="input" style="max-width: 160px;" value="${escapeAttr(dateTo)}" title="Date To" />
        <button class="btn btn-secondary" id="auditFilterBtn">Filter Logs</button>
      </div>
    </div>

    <div id="auditTableArea" class="table-container">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
    <div id="auditPagination"></div>

    <div id="auditModalRoot"></div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/audit', 'Administrative Audit Trail', contentHtml);

  const actionInput = container.querySelector('#auditActionInput');
  const dateFromInput = container.querySelector('#auditDateFrom');
  const dateToInput = container.querySelector('#auditDateTo');
  const filterBtn = container.querySelector('#auditFilterBtn');

  function updateParams(newParams) {
    const params = new URLSearchParams(query);
    Object.entries(newParams).forEach(([k, v]) => {
      if (v) params.set(k, v);
      else params.delete(k);
    });
    if (!('page' in newParams)) params.delete('page');
    window.location.hash = `#/admin/audit?${params.toString()}`;
  }

  filterBtn.addEventListener('click', () => {
    updateParams({
      action: actionInput.value.trim(),
      date_from: dateFromInput.value,
      date_to: dateToInput.value,
    });
  });

  const tableArea = container.querySelector('#auditTableArea');
  const paginationArea = container.querySelector('#auditPagination');

  try {
    const queryParams = { page, page_size: 25 };
    if (actionFilter) queryParams.action = actionFilter;
    if (dateFrom) queryParams.date_from = dateFrom;
    if (dateTo) queryParams.date_to = dateTo;

    const res = await api('/admin/audit-logs', { query: queryParams, signal });
    renderAuditTable(tableArea, paginationArea, res, (newPage) => {
      updateParams({ page: newPage });
    }, container);
  } catch (err) {
    if (signal?.aborted) return;
    renderError(tableArea, err, { onRetry: () => renderAuditLogs(container, routeContext) });
  }
}

function renderAuditTable(tableArea, paginationArea, data, onPageChange, container) {
  if (!data.items || data.items.length === 0) {
    tableArea.innerHTML = `
      <div class="empty-state" style="padding: 3rem; text-align: center;">
        <h3>No audit logs found</h3>
        <p class="text-muted">No log entries recorded for this filter criteria.</p>
      </div>
    `;
    paginationArea.innerHTML = '';
    return;
  }

  const rowsHtml = data.items.map((log) => {
    const rawDate = log.timestamp || log.created_at;
    const dateStr = rawDate ? new Date(rawDate).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    }) : '—';
    const beforeData = log.before || log.before_state;
    const afterData = log.after || log.after_state;
    const hasDiff = Boolean((beforeData && Object.keys(beforeData).length > 0) || (afterData && Object.keys(afterData).length > 0));

    return `
      <tr data-log-id="${log.id}">
        <td style="white-space: nowrap; font-size: 0.85rem; color: var(--color-muted);">${dateStr}</td>
        <td>
          <div style="font-weight: 500;">${escapeText(log.actor_name || log.actor_username || 'System')}</div>
          <div style="font-size: 0.8rem; color: var(--color-muted);">@${escapeText(log.actor_username || 'system')}</div>
        </td>
        <td>
          <span class="badge badge-sm badge-info" style="font-family: monospace;">${escapeText(log.action)}</span>
        </td>
        <td>
          <div style="font-size: 0.85rem; font-weight: 500;">${escapeText(log.entity_type)}</div>
          <div style="font-size: 0.75rem; color: var(--color-muted); font-family: monospace;">${escapeText(log.entity_id || '—')}</div>
        </td>
        <td>
          ${hasDiff ? `
            <button class="btn btn-sm btn-secondary btn-view-diff" data-log-id="${log.id}">Inspect Payload</button>
          ` : '<span class="text-muted" style="font-size: 0.8rem; color: var(--color-muted);">No payload diff</span>'}
        </td>
      </tr>
    `;
  }).join('');

  tableArea.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Timestamp (UTC)</th>
          <th>Actor</th>
          <th>Action</th>
          <th>Entity</th>
          <th>State Diff</th>
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

  const logMap = new Map();
  data.items.forEach((item) => logMap.set(item.id, item));

  tableArea.querySelectorAll('.btn-view-diff').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const logId = e.target.dataset.logId;
      const log = logMap.get(logId);
      if (log) showDiffModal(container, log);
    });
  });
}

function showDiffModal(container, log) {
  const modalRoot = container.querySelector('#auditModalRoot');
  const beforeData = log.before || log.before_state;
  const afterData = log.after || log.after_state;
  const rawDate = log.timestamp || log.created_at;

  const beforeJson = beforeData ? JSON.stringify(beforeData, null, 2) : 'None';
  const afterJson = afterData ? JSON.stringify(afterData, null, 2) : 'None';
  const dateFormatted = rawDate ? new Date(rawDate).toLocaleString() : 'Recorded';

  modalRoot.innerHTML = `
    <div class="modal-backdrop" id="diffBackdrop">
      <div class="modal-dialog card" style="max-width: 780px; margin: 6vh auto; padding: 1.5rem; max-height: 88vh; display: flex; flex-direction: column;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
          <h3 style="margin: 0;">Audit Log State: ${escapeText(log.action)} (${escapeText(log.entity_type)})</h3>
          <button class="btn btn-sm btn-secondary" id="closeDiffBtn">&times;</button>
        </div>
        
        <div style="font-size: 0.85rem; color: var(--color-muted); margin-bottom: 1rem;">
          Recorded on ${dateFormatted} by ${escapeText(log.actor_name || log.actor_username || 'System')} (Entity ID: <code>${escapeText(log.entity_id || '')}</code>)
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; overflow-y: auto; flex: 1;">
          <div>
            <div style="font-weight: 600; font-size: 0.85rem; margin-bottom: 0.25rem;">Before State:</div>
            <pre style="background: var(--color-bg); border: 1px solid var(--color-border); padding: 0.75rem; border-radius: 4px; font-size: 0.8rem; overflow-x: auto; white-space: pre-wrap; font-family: monospace;">${escapeText(beforeJson)}</pre>
          </div>
          <div>
            <div style="font-weight: 600; font-size: 0.85rem; margin-bottom: 0.25rem;">After State:</div>
            <pre style="background: var(--color-bg); border: 1px solid var(--color-border); padding: 0.75rem; border-radius: 4px; font-size: 0.8rem; overflow-x: auto; white-space: pre-wrap; font-family: monospace;">${escapeText(afterJson)}</pre>
          </div>
        </div>

        <div style="text-align: right; margin-top: 1rem;">
          <button class="btn btn-secondary" id="closeDiffBtnBottom">Close</button>
        </div>
      </div>
    </div>
  `;

  const backdrop = modalRoot.querySelector('#diffBackdrop');
  const closeBtn = modalRoot.querySelector('#closeDiffBtn');
  const closeBtnBottom = modalRoot.querySelector('#closeDiffBtnBottom');

  function closeModal() {
    modalRoot.innerHTML = '';
  }

  closeBtn.addEventListener('click', closeModal);
  closeBtnBottom.addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeModal();
  });
}

// ==============================================================================
// 4. Global Settings Management
// ==============================================================================

export async function renderSettingsManager(container, routeContext) {
  if (!can('settings:write')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/settings',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have settings write permissions.</p></div>'
    );
    return;
  }

  const { signal } = routeContext;
  document.title = 'Global Settings — Folio Admin';

  const contentHtml = `
    <div id="settingsFormArea" style="max-width: 680px;">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/settings', 'Global System Settings', contentHtml);

  const formArea = container.querySelector('#settingsFormArea');

  try {
    const settings = await api('/admin/settings', { signal });
    renderSettingsForm(formArea, settings);
  } catch (err) {
    if (signal?.aborted) return;
    renderError(formArea, err, { onRetry: () => renderSettingsManager(container, routeContext) });
  }
}

function renderSettingsForm(formArea, settings) {
  formArea.innerHTML = `
    <form id="globalSettingsForm" class="card" style="padding: 1.5rem;">
      <div class="field" style="margin-bottom: 1.25rem;">
        <label class="label" for="settingSiteName">Repository Name *</label>
        <input type="text" id="settingSiteName" class="input" value="${escapeAttr(settings.site_name || '')}" required />
        <div class="form-help">Displayed across library headers, meta titles, and public navigation.</div>
      </div>

      <div class="field" style="margin-bottom: 1.25rem;">
        <label class="label" for="settingSiteDesc">Library Description</label>
        <textarea id="settingSiteDesc" class="textarea" rows="3">${escapeText(settings.site_description || '')}</textarea>
        <div class="form-help">Shown on the library homepage banner and default search description.</div>
      </div>

      <div class="field" style="margin-bottom: 1.25rem;">
        <label style="display: flex; align-items: center; gap: 0.75rem; cursor: pointer;">
          <input type="checkbox" id="settingRegEnabled" ${settings.registration_enabled ? 'checked' : ''} />
          <div>
            <div style="font-weight: 600;">Allow Public User Registration</div>
            <div class="form-help">When disabled, new visitors cannot self-register member accounts.</div>
          </div>
        </label>
      </div>

      <div class="field" style="margin-bottom: 1.75rem;">
        <label style="display: flex; align-items: center; gap: 0.75rem; cursor: pointer;">
          <input type="checkbox" id="settingCommentsEnabled" ${settings.comments_enabled ? 'checked' : ''} />
          <div>
            <div style="font-weight: 600;">Allow Document Discussions & Comments</div>
            <div class="form-help">When disabled, document reading is active but new comments are deactivated globally.</div>
          </div>
        </label>
      </div>

      <div style="display: flex; justify-content: flex-end;">
        <button type="submit" id="saveSettingsBtn" class="btn btn-primary">Save Settings</button>
      </div>
    </form>
  `;

  const form = formArea.querySelector('#globalSettingsForm');
  const saveBtn = formArea.querySelector('#saveSettingsBtn');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const siteName = formArea.querySelector('#settingSiteName').value.trim();
    const siteDesc = formArea.querySelector('#settingSiteDesc').value.trim();
    const regEnabled = formArea.querySelector('#settingRegEnabled').checked;
    const commentsEnabled = formArea.querySelector('#settingCommentsEnabled').checked;

    try {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';
      await api('/admin/settings', {
        method: 'PATCH',
        body: {
          site_name: siteName,
          site_description: siteDesc,
          registration_enabled: regEnabled,
          comments_enabled: commentsEnabled,
        }
      });
      await loadPublicSettings();
      notify('Settings updated successfully.', { kind: 'success' });
    } catch (err) {
      notify(err.message || 'Failed to update settings', { kind: 'error' });
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Settings';
    }
  });
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
