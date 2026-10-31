// src/frontend/admin/moderation_views.js
// Moderation Queue: Comments moderation, Flagged reports, and commenting suspension

import { api, ApiError } from '../core/api.js';
import { can } from '../core/session.js';
import { notify, confirmAction, renderPagination, renderError } from '../core/ui.js';
import { wrapAdminLayout } from './admin_shell.js';

// ==============================================================================
// 1. Comments Moderation Queue
// ==============================================================================

export async function renderCommentsQueue(container, routeContext) {
  if (!can('moderation:manage')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/comments',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have moderation permissions.</p></div>'
    );
    return;
  }

  const { query, signal } = routeContext;
  const statusFilter = query.get('status') || '';
  const q = query.get('q') || '';
  const page = parseInt(query.get('page') || '1', 10);

  document.title = 'Comments Moderation — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; flex: 1; max-width: 700px;">
        <input type="search" id="commentSearchInput" class="input" style="flex: 2; min-width: 200px;" placeholder="Search comments by text..." value="${escapeAttr(q)}" />
        <select id="commentStatusSelect" class="select" style="flex: 1; min-width: 140px;">
          <option value="" ${!statusFilter ? 'selected' : ''}>All Statuses</option>
          <option value="visible" ${statusFilter === 'visible' ? 'selected' : ''}>Visible</option>
          <option value="hidden" ${statusFilter === 'hidden' ? 'selected' : ''}>Hidden</option>
          <option value="spam" ${statusFilter === 'spam' ? 'selected' : ''}>Spam</option>
          <option value="deleted" ${statusFilter === 'deleted' ? 'selected' : ''}>Deleted by User</option>
        </select>
        <button class="btn btn-secondary" id="commentFilterBtn">Filter</button>
      </div>
      <a href="#/admin/reports" class="btn btn-secondary">View Reports Queue &rarr;</a>
    </div>

    <div id="commentsTableArea" class="table-container">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
    <div id="commentsPagination"></div>

    <!-- Suspension Modal Container -->
    <div id="suspendModalRoot"></div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/comments', 'Comments Moderation Queue', contentHtml);

  const searchInput = container.querySelector('#commentSearchInput');
  const statusSelect = container.querySelector('#commentStatusSelect');
  const filterBtn = container.querySelector('#commentFilterBtn');

  function updateParams(newParams) {
    const params = new URLSearchParams(query);
    Object.entries(newParams).forEach(([k, v]) => {
      if (v) params.set(k, v);
      else params.delete(k);
    });
    if (!('page' in newParams)) params.delete('page');
    window.location.hash = `#/admin/comments?${params.toString()}`;
  }

  filterBtn.addEventListener('click', () => {
    updateParams({ q: searchInput.value.trim(), status: statusSelect.value });
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      updateParams({ q: searchInput.value.trim(), status: statusSelect.value });
    }
  });

  // Load comments
  const tableArea = container.querySelector('#commentsTableArea');
  const paginationArea = container.querySelector('#commentsPagination');

  try {
    const queryParams = { page, page_size: 20 };
    if (statusFilter) queryParams.status = statusFilter;
    if (q) queryParams.q = q;

    const res = await api('/admin/comments', { query: queryParams, signal });
    renderCommentsTable(tableArea, paginationArea, res, (newPage) => {
      updateParams({ page: newPage });
    }, container);
  } catch (err) {
    if (signal?.aborted) return;
    renderError(tableArea, err, { onRetry: () => renderCommentsQueue(container, routeContext) });
  }
}

function renderCommentsTable(tableArea, paginationArea, data, onPageChange, container) {
  if (!data.items || data.items.length === 0) {
    tableArea.innerHTML = `
      <div class="empty-state" style="padding: 3rem; text-align: center;">
        <h3>No comments found</h3>
        <p class="text-muted">No comments match the search or status filter criteria.</p>
      </div>
    `;
    paginationArea.innerHTML = '';
    return;
  }

  const rowsHtml = data.items.map((c) => {
    const statusBadge = getCommentStatusBadge(c.status);
    const dateStr = new Date(c.created_at).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
    const isOwnerDeleted = c.status === 'deleted';
    const author = c.author || {};
    const authorId = author.id || c.user_id || '';
    const authorName = author.display_name || author.username || c.author_name || 'Anonymous';
    const authorUsername = author.username || c.author_username || 'user';

    return `
      <tr data-comment-id="${c.id}" data-user-id="${authorId}">
        <td style="max-width: 250px;">
          <div style="font-weight: 600; margin-bottom: 0.25rem;">
            <a href="#/documents/${c.document_id}" target="_blank" title="View Document in Library" style="color: var(--color-ink); text-decoration: underline;">
              ${escapeText(c.document_title || 'Untitled Document')}
            </a>
          </div>
          <div style="font-size: 0.75rem; color: var(--color-muted); font-family: monospace;">Doc ID: ${c.document_id.substring(0, 8)}...</div>
        </td>
        <td style="white-space: nowrap;">
          <div style="font-weight: 600;">${escapeText(authorName)}</div>
          <div style="font-size: 0.8rem; color: var(--color-muted);">@${escapeText(authorUsername)}</div>
        </td>
        <td style="max-width: 360px;">
          <div class="comment-body-preview" style="white-space: pre-wrap; font-size: 0.9rem; max-height: 90px; overflow-y: auto; background: var(--color-bg); padding: 0.5rem; border-radius: 4px; border: 1px solid var(--color-border);">
            ${escapeText(c.body)}
          </div>
        </td>
        <td>${statusBadge}</td>
        <td style="font-size: 0.8rem; color: var(--color-muted); white-space: nowrap;">${dateStr}</td>
        <td style="white-space: nowrap;">
          ${!isOwnerDeleted ? `
            <div class="btn-group" style="display: flex; gap: 0.25rem; flex-wrap: wrap;">
              ${c.status !== 'visible' ? `
                <button class="btn btn-sm btn-secondary btn-action-status" data-status="visible" title="Restore visibility">Visible</button>
              ` : ''}
              ${c.status !== 'hidden' ? `
                <button class="btn btn-sm btn-secondary btn-action-status" data-status="hidden" title="Hide from public view">Hide</button>
              ` : ''}
              ${c.status !== 'spam' ? `
                <button class="btn btn-sm btn-danger btn-action-status" data-status="spam" title="Flag as spam">Spam</button>
              ` : ''}
              <button class="btn btn-sm btn-secondary btn-suspend-user" title="Suspend commenting for author">Suspend</button>
            </div>
          ` : `
            <span class="badge" title="Owner deleted comments cannot be resurrected">Deleted by author</span>
          `}
        </td>
      </tr>
    `;
  }).join('');

  tableArea.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Document</th>
          <th>Author</th>
          <th>Comment Content</th>
          <th>Status</th>
          <th>Date</th>
          <th>Actions</th>
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

  // Bind comment status buttons
  tableArea.querySelectorAll('.btn-action-status').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const row = e.target.closest('tr');
      const commentId = row.dataset.commentId;
      const targetStatus = e.target.dataset.status;

      try {
        btn.disabled = true;
        await api(`/admin/comments/${commentId}/status`, {
          method: 'PATCH',
          body: {
            status: targetStatus,
            reason: `Moderation action changed status to ${targetStatus}`
          }
        });
        notify(`Comment marked as ${targetStatus}.`, { kind: 'success' });
        renderCommentsQueue(container, { query: new URLSearchParams(window.location.hash.split('?')[1] || '') });
      } catch (err) {
        notify(err.message || 'Failed to update comment status', { kind: 'error' });
        btn.disabled = false;
      }
    });
  });

  // Bind suspend user button
  tableArea.querySelectorAll('.btn-suspend-user').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const row = e.target.closest('tr');
      const userId = row.dataset.userId;
      const authorName = row.cells[1].querySelector('div').textContent.trim();
      showSuspendModal(container, userId, authorName);
    });
  });
}

function showSuspendModal(container, userId, authorName) {
  const modalRoot = container.querySelector('#suspendModalRoot');
  modalRoot.innerHTML = `
    <div class="modal-backdrop" id="suspendBackdrop">
      <div class="modal-dialog card" style="max-width: 480px; margin: 10vh auto; padding: 1.5rem;">
        <h3 style="margin-top: 0;">Suspend Commenting Privileges</h3>
        <p style="color: var(--color-muted); font-size: 0.9rem;">
          Configure commenting restriction for user <strong>${escapeText(authorName)}</strong>.
        </p>
        
        <div class="field" style="margin-bottom: 1rem;">
          <label class="label" for="suspendDuration">Suspension Duration</label>
          <select id="suspendDuration" class="select">
            <option value="1">1 Day</option>
            <option value="3">3 Days</option>
            <option value="7" selected>7 Days (Standard)</option>
            <option value="30">30 Days</option>
            <option value="0">Restore Privileges (Lift Suspension)</option>
          </select>
        </div>

        <div class="field" style="margin-bottom: 1.5rem;">
          <label class="label" for="suspendReason">Audit Reason *</label>
          <input type="text" id="suspendReason" class="input" placeholder="e.g. Repeated abusive comments or spam activity" required />
          <div class="form-help">This reason is logged in the system audit trail.</div>
        </div>

        <div id="suspendModalError" class="notice notice-error" style="display: none; margin-bottom: 1rem;"></div>

        <div style="display: flex; justify-content: flex-end; gap: 0.5rem;">
          <button class="btn btn-secondary" id="cancelSuspendBtn">Cancel</button>
          <button class="btn btn-danger" id="confirmSuspendBtn">Apply Suspension</button>
        </div>
      </div>
    </div>
  `;

  const backdrop = modalRoot.querySelector('#suspendBackdrop');
  const cancelBtn = modalRoot.querySelector('#cancelSuspendBtn');
  const confirmBtn = modalRoot.querySelector('#confirmSuspendBtn');
  const durationSelect = modalRoot.querySelector('#suspendDuration');
  const reasonInput = modalRoot.querySelector('#suspendReason');
  const errorBox = modalRoot.querySelector('#suspendModalError');

  function closeModal() {
    modalRoot.innerHTML = '';
  }

  cancelBtn.addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeModal();
  });

  confirmBtn.addEventListener('click', async () => {
    const days = parseInt(durationSelect.value, 10);
    const reason = reasonInput.value.trim();

    if (!reason) {
      errorBox.textContent = 'Please provide an audit reason for this moderation action.';
      errorBox.style.display = 'block';
      return;
    }

    let suspendedUntil = null;
    if (days > 0) {
      const targetDate = new Date();
      targetDate.setDate(targetDate.getDate() + days);
      suspendedUntil = targetDate.toISOString();
    }

    try {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Saving...';
      await api(`/admin/users/${userId}/commenting`, {
        method: 'PATCH',
        body: {
          suspended_until: suspendedUntil,
          reason
        }
      });
      notify(days > 0 ? `User commenting suspended for ${days} days.` : 'User commenting suspension lifted.', { kind: 'success' });
      closeModal();
    } catch (err) {
      errorBox.textContent = err.message || 'Failed to update commenting suspension.';
      errorBox.style.display = 'block';
      confirmBtn.disabled = false;
      confirmBtn.textContent = 'Apply Suspension';
    }
  });
}

// ==============================================================================
// 2. Flagged Reports Queue
// ==============================================================================

export async function renderReportsQueue(container, routeContext) {
  if (!can('moderation:manage')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/reports',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have moderation permissions.</p></div>'
    );
    return;
  }

  const { query, signal } = routeContext;
  const statusFilter = query.get('status') || 'open';
  const page = parseInt(query.get('page') || '1', 10);

  document.title = 'Content Flags & Reports — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div style="display: flex; gap: 0.5rem; flex: 1; max-width: 500px;">
        <select id="reportStatusSelect" class="select" style="width: 170px;">
          <option value="open" ${statusFilter === 'open' ? 'selected' : ''}>Open Reports</option>
          <option value="resolved" ${statusFilter === 'resolved' ? 'selected' : ''}>Resolved Reports</option>
          <option value="dismissed" ${statusFilter === 'dismissed' ? 'selected' : ''}>Dismissed Reports</option>
        </select>
        <button class="btn btn-secondary" id="reportFilterBtn">Filter</button>
      </div>
      <a href="#/admin/comments" class="btn btn-secondary">&larr; Back to Comments</a>
    </div>

    <div id="reportsTableArea" class="table-container">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
    <div id="reportsPagination"></div>

    <div id="reportActionModalRoot"></div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/reports', 'Content Flags & Reports', contentHtml);

  const statusSelect = container.querySelector('#reportStatusSelect');
  const filterBtn = container.querySelector('#reportFilterBtn');

  function updateParams(newParams) {
    const params = new URLSearchParams(query);
    Object.entries(newParams).forEach(([k, v]) => {
      if (v) params.set(k, v);
      else params.delete(k);
    });
    if (!('page' in newParams)) params.delete('page');
    window.location.hash = `#/admin/reports?${params.toString()}`;
  }

  filterBtn.addEventListener('click', () => {
    updateParams({ status: statusSelect.value });
  });

  const tableArea = container.querySelector('#reportsTableArea');
  const paginationArea = container.querySelector('#reportsPagination');

  try {
    const res = await api('/admin/reports', {
      query: { status: statusFilter, page, page_size: 20 },
      signal
    });
    renderReportsTable(tableArea, paginationArea, res, (newPage) => {
      updateParams({ page: newPage });
    }, container);
  } catch (err) {
    if (signal?.aborted) return;
    renderError(tableArea, err, { onRetry: () => renderReportsQueue(container, routeContext) });
  }
}

function renderReportsTable(tableArea, paginationArea, data, onPageChange, container) {
  if (!data.items || data.items.length === 0) {
    tableArea.innerHTML = `
      <div class="empty-state" style="padding: 3rem; text-align: center;">
        <h3>No reports in this queue</h3>
        <p class="text-muted">No content reports match the selected status.</p>
      </div>
    `;
    paginationArea.innerHTML = '';
    return;
  }

  const rowsHtml = data.items.map((r) => {
    const statusBadge = getReportStatusBadge(r.status);
    const dateStr = new Date(r.created_at).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
    const commentBody = r.comment_body || (r.comment && r.comment.body) || '[Comment no longer available]';
    const commentAuthor = r.comment_author || (r.comment && r.comment.author) || {};
    const reporter = r.reporter || {};

    return `
      <tr data-report-id="${r.id}" data-comment-id="${r.comment_id || (r.comment && r.comment.id) || ''}">
        <td>
          <div style="font-weight: 600; color: var(--color-ink); text-transform: capitalize;">${escapeText(r.reason)}</div>
          <div style="font-size: 0.85rem; color: var(--color-muted); margin-top: 0.15rem;">${escapeText(r.details || 'No additional details provided.')}</div>
          <div style="font-size: 0.75rem; color: var(--color-muted); margin-top: 0.25rem; font-family: monospace;">Report ID: ${r.id.substring(0, 8)}...</div>
        </td>
        <td style="max-width: 320px;">
          <div style="background: var(--color-bg); border: 1px solid var(--color-border); border-radius: 4px; padding: 0.5rem; font-size: 0.85rem;">
            <div style="font-weight: 600; margin-bottom: 0.25rem;">
              @${escapeText(commentAuthor.username || 'user')}:
            </div>
            <div style="white-space: pre-wrap; max-height: 80px; overflow-y: auto;">
              ${escapeText(commentBody)}
            </div>
          </div>
        </td>
        <td>
          <div style="font-size: 0.9rem; font-weight: 500;">${escapeText(reporter.display_name || reporter.username || 'Anonymous')}</div>
          <div style="font-size: 0.8rem; color: var(--color-muted);">@${escapeText(reporter.username || 'user')}</div>
        </td>
        <td>${statusBadge}</td>
        <td style="font-size: 0.8rem; color: var(--color-muted); white-space: nowrap;">${dateStr}</td>
        <td style="white-space: nowrap;">
          ${r.status === 'open' ? `
            <div class="btn-group" style="display: flex; gap: 0.25rem;">
              <button class="btn btn-sm btn-secondary btn-action-report" data-action="dismiss" title="Dismiss report without altering comment">Dismiss</button>
              <button class="btn btn-sm btn-secondary btn-action-report" data-action="hide_comment" title="Hide comment and mark report resolved">Hide Comment</button>
              <button class="btn btn-sm btn-danger btn-action-report" data-action="mark_spam" title="Flag comment as spam and mark resolved">Mark Spam</button>
            </div>
          ` : `
            <div style="font-size: 0.85rem; color: var(--color-muted);">
              <strong>${escapeText(r.status)}</strong>: ${escapeText(r.resolution || 'Handled')}
            </div>
          `}
        </td>
      </tr>
    `;
  }).join('');

  tableArea.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Report Reason</th>
          <th>Comment Context</th>
          <th>Reported By</th>
          <th>Status</th>
          <th>Date</th>
          <th>Actions</th>
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

  tableArea.querySelectorAll('.btn-action-report').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const row = e.target.closest('tr');
      const reportId = row.dataset.reportId;
      const action = e.target.dataset.action;

      let resolutionNote = '';
      if (action === 'dismiss') {
        resolutionNote = 'Report dismissed upon review';
      } else if (action === 'hide_comment') {
        resolutionNote = 'Comment hidden due to policy violation';
      } else if (action === 'mark_spam') {
        resolutionNote = 'Comment marked as spam';
      }

      try {
        btn.disabled = true;
        await api(`/admin/reports/${reportId}`, {
          method: 'PATCH',
          body: {
            action,
            resolution: resolutionNote
          }
        });
        notify(`Report successfully processed (${action}).`, { kind: 'success' });
        renderReportsQueue(container, { query: new URLSearchParams(window.location.hash.split('?')[1] || '') });
      } catch (err) {
        notify(err.message || 'Failed to resolve report', { kind: 'error' });
        btn.disabled = false;
      }
    });
  });
}

// ==============================================================================
// Badges and Text Helpers
// ==============================================================================

function getCommentStatusBadge(status) {
  switch (status) {
    case 'visible':
      return '<span class="badge badge-success">Visible</span>';
    case 'hidden':
      return '<span class="badge badge-warning">Hidden</span>';
    case 'spam':
      return '<span class="badge badge-danger">Spam</span>';
    case 'deleted':
      return '<span class="badge">Deleted</span>';
    default:
      return `<span class="badge">${escapeText(status)}</span>`;
  }
}

function getReportStatusBadge(status) {
  switch (status) {
    case 'open':
      return '<span class="badge badge-warning">Open</span>';
    case 'resolved':
      return '<span class="badge badge-success">Resolved</span>';
    case 'dismissed':
      return '<span class="badge">Dismissed</span>';
    default:
      return `<span class="badge">${escapeText(status)}</span>`;
  }
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
