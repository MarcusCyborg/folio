// src/frontend/admin/content_views.js
// Admin Content Management: Documents CRUD, Markdown Editor with Safe Preview & Dirty Guard, Taxonomy Manager

import { api, ApiError } from '../core/api.js';
import { can, getSession } from '../core/session.js';
import { navigate, registerLeaveGuard, clearLeaveGuard } from '../core/router.js';
import { notify, confirmAction, renderPagination, renderError } from '../core/ui.js';
import { renderMathInContainer } from '../core/math.js';
import { wrapAdminLayout } from './admin_shell.js';

// ==============================================================================
// 1. Documents Directory & Actions
// ==============================================================================

export async function renderAdminDocuments(container, routeContext) {
  if (!can('documents:write') && !can('seo:write')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/documents',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have permission to access document management.</p></div>'
    );
    return;
  }

  const { query, signal } = routeContext;
  const q = query.get('q') || '';
  const statusFilter = query.get('status') || '';
  const categoryFilter = query.get('category_id') || '';
  const page = parseInt(query.get('page') || '1', 10);

  document.title = 'Documents Management — Folio Admin';

  const contentHtml = `
    <div class="admin-toolbar">
      <div class="admin-filter-group" style="display: flex; gap: 0.5rem; flex-wrap: wrap; flex: 1; max-width: 800px;">
        <input type="search" id="adminDocSearchInput" class="input" style="flex: 2; min-width: 200px;" placeholder="Search documents by title..." value="${escapeAttr(q)}" />
        
        <select id="adminDocStatusSelect" class="select" style="flex: 1; min-width: 130px;">
          <option value="" ${!statusFilter ? 'selected' : ''}>All Status</option>
          <option value="published" ${statusFilter === 'published' ? 'selected' : ''}>Published</option>
          <option value="draft" ${statusFilter === 'draft' ? 'selected' : ''}>Draft</option>
        </select>

        <select id="adminDocCategorySelect" class="select" style="flex: 1; min-width: 150px;">
          <option value="">All Categories</option>
        </select>

        <button class="btn btn-secondary" id="adminDocFilterBtn">Filter</button>
      </div>

      ${can('documents:write') ? `
        <a href="#/admin/documents/new" class="btn btn-primary" id="createNewDocBtn">+ Create Document</a>
      ` : ''}
    </div>

    <div id="adminDocTableArea" class="table-container">
      <div style="text-align: center; padding: 3rem;"><span class="spinner"></span></div>
    </div>
    <div id="adminDocPagination"></div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/documents', 'Research Documents', contentHtml);

  const searchInput = container.querySelector('#adminDocSearchInput');
  const statusSelect = container.querySelector('#adminDocStatusSelect');
  const categorySelect = container.querySelector('#adminDocCategorySelect');
  const filterBtn = container.querySelector('#adminDocFilterBtn');

  // Load Categories for filter dropdown
  try {
    const catsRes = await api('/admin/categories', { query: { page: 1, page_size: 100 }, signal });
    if (catsRes && catsRes.items) {
      const catOptions = catsRes.items.map(c => `
        <option value="${c.id}" ${categoryFilter === c.id ? 'selected' : ''}>${escapeText(c.name)}</option>
      `).join('');
      categorySelect.innerHTML = `<option value="">All Categories</option>${catOptions}`;
    }
  } catch (err) {
    if (signal?.aborted) return;
    console.warn('Failed to load categories for filter:', err);
  }

  function updateParams(newParams) {
    const params = new URLSearchParams(query);
    Object.entries(newParams).forEach(([k, v]) => {
      if (v) params.set(k, v);
      else params.delete(k);
    });
    if (!('page' in newParams)) params.delete('page');
    navigate(`/admin/documents?${params.toString()}`);
  }

  filterBtn.onclick = () => {
    updateParams({
      q: searchInput.value.trim(),
      status: statusSelect.value,
      category_id: categorySelect.value,
    });
  };

  searchInput.onkeydown = (e) => {
    if (e.key === 'Enter') filterBtn.click();
  };

  let closeAllDropdowns = null;
  let escListener = null;

  try {
    const data = await api('/admin/documents', {
      query: {
        q: q || undefined,
        status: statusFilter || undefined,
        category_id: categoryFilter || undefined,
        page,
        page_size: 20
      },
      signal,
    });

    const tableArea = container.querySelector('#adminDocTableArea');
    const paginationArea = container.querySelector('#adminDocPagination');

    if (!data.items || data.items.length === 0) {
      tableArea.innerHTML = `
        <div class="empty-state" style="padding: 3rem 1rem; text-align: center;">
          <h3>No documents found</h3>
          <p class="text-muted">No documents match the current search or filter criteria.</p>
        </div>
      `;
      paginationArea.innerHTML = '';
      return;
    }

    const rowsHtml = data.items.map((doc) => {
      const isPub = doc.status === 'published';
      const statusBadge = isPub
        ? '<span class="badge badge-success">Published</span>'
        : '<span class="badge badge-warning">Draft</span>';
      const createdDate = new Date(doc.created_at).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
      });

      return `
        <tr data-doc-id="${doc.id}">
          <td style="font-weight: 600; min-width: 320px; max-width: 500px;">
            ${can('documents:write')
              ? `<a href="#/admin/documents/${doc.id}/edit" class="table-title-link" title="${escapeAttr(doc.title)}">${escapeText(doc.title)}</a>`
              : `<span class="table-title-static" title="${escapeAttr(doc.title)}">${escapeText(doc.title)}</span>`
            }
          </td>
          <td><span class="badge badge-teal">${escapeText(doc.category ? doc.category.name : '—')}</span></td>
          <td style="color: var(--color-muted);">${escapeText(doc.author || '—')}</td>
          <td>${statusBadge}</td>
          <td style="white-space: nowrap; font-size: 0.85rem; color: var(--color-muted);">${createdDate}</td>
          <td class="table-actions-cell" style="white-space: nowrap;">
            <div class="action-group">
              ${can('documents:write') ? `
                <a href="#/admin/documents/${doc.id}/edit" class="btn btn-primary btn-sm" title="Edit Document Content">Edit</a>
                <div class="action-menu-wrap">
                  <button type="button" class="btn btn-secondary btn-sm action-dropdown-trigger" aria-haspopup="true" aria-expanded="false" title="More options for ${escapeAttr(doc.title)}">•••</button>
                  <div class="action-menu-dropdown" role="menu">
                    <button type="button" class="action-menu-item toggle-status-btn" data-status="${doc.status}">
                      ${isPub ? 'Save & Unpublish' : 'Publish to Library'}
                    </button>
                    ${can('seo:write') ? `<a href="#/admin/seo/${doc.id}" class="action-menu-item">Configure SEO</a>` : ''}
                    <div class="action-menu-divider"></div>
                    <button type="button" class="action-menu-item danger-item delete-doc-btn">Delete Document</button>
                  </div>
                </div>
              ` : (can('seo:write') ? `
                <a href="#/admin/seo/${doc.id}" class="btn btn-secondary btn-sm">Configure SEO</a>
              ` : '')}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    tableArea.innerHTML = `
      <table class="table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Category</th>
            <th>Author</th>
            <th>Status</th>
            <th>Date</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;

    // Hook up Dropdown Menu Triggers
    tableArea.querySelectorAll('.action-dropdown-trigger').forEach((trigger) => {
      trigger.onclick = (e) => {
        e.stopPropagation();
        const dropdown = trigger.nextElementSibling;
        const isOpen = dropdown.classList.contains('open');
        tableArea.querySelectorAll('.action-menu-dropdown.open').forEach((d) => {
          d.classList.remove('open');
          if (d.previousElementSibling) d.previousElementSibling.setAttribute('aria-expanded', 'false');
        });
        if (!isOpen) {
          dropdown.classList.add('open');
          trigger.setAttribute('aria-expanded', 'true');
        }
      };
    });

    closeAllDropdowns = () => {
      tableArea.querySelectorAll('.action-menu-dropdown.open').forEach((d) => {
        d.classList.remove('open');
        if (d.previousElementSibling) d.previousElementSibling.setAttribute('aria-expanded', 'false');
      });
    };
    document.addEventListener('click', closeAllDropdowns);
    escListener = (e) => { if (e.key === 'Escape') closeAllDropdowns(); };
    document.addEventListener('keydown', escListener);

    // Hook up Publish/Unpublish toggle
    tableArea.querySelectorAll('.toggle-status-btn').forEach((btn) => {
      btn.onclick = async () => {
        const row = btn.closest('tr');
        const docId = row.getAttribute('data-doc-id');
        const currentStatus = btn.getAttribute('data-status');
        const nextStatus = currentStatus === 'published' ? 'draft' : 'published';

        try {
          btn.disabled = true;
          await api(`/admin/documents/${docId}/status`, {
            method: 'PATCH',
            body: { status: nextStatus },
          });
          notify(`Document marked as ${nextStatus}.`, { kind: 'success' });
          renderAdminDocuments(container, routeContext);
        } catch (err) {
          notify(err.message || 'Status transition failed', { kind: 'error' });
          btn.disabled = false;
        }
      };
    });

    // Hook up Soft Delete
    tableArea.querySelectorAll('.delete-doc-btn').forEach((btn) => {
      btn.onclick = async () => {
        const row = btn.closest('tr');
        const docId = row.getAttribute('data-doc-id');
        const titleEl = row.querySelector('.table-title-link, .table-title-static');
        const docTitle = titleEl ? titleEl.textContent : 'this document';

        const ok = await confirmAction({
          title: 'Soft-Delete Document',
          message: `Are you sure you want to delete "${docTitle}"? It will be excluded from public access immediately.`,
          confirmLabel: 'Delete Document',
          destructive: true,
        });

        if (ok) {
          try {
            btn.disabled = true;
            await api(`/admin/documents/${docId}`, { method: 'DELETE' });
            notify('Document deleted.', { kind: 'success' });
            renderAdminDocuments(container, routeContext);
          } catch (err) {
            notify(err.message || 'Delete failed', { kind: 'error' });
            btn.disabled = false;
          }
        }
      };
    });

    // Render pagination
    renderPagination(paginationArea, {
      page: data.page,
      pageSize: data.page_size,
      total: data.total,
      onChange: (newPage) => updateParams({ page: newPage }),
    });

  } catch (err) {
    if (signal?.aborted) return;
    renderError(container.querySelector('#adminDocTableArea'), err, {
      onRetry: () => renderAdminDocuments(container, routeContext)
    });
  }

  return () => {
    if (closeAllDropdowns) document.removeEventListener('click', closeAllDropdowns);
    if (escListener) document.removeEventListener('keydown', escListener);
  };
}

// ==============================================================================
// 2. Document Authoring Editor (Draft, Publish, Preview & Dirty Protection)
// ==============================================================================

export async function renderDocumentEditor(container, routeContext) {
  if (!can('documents:write')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/documents',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have permission to write or edit documents.</p></div>'
    );
    return;
  }

  const { params, signal } = routeContext;
  let isNew = !params.id;
  let docId = params.id;

  document.title = isNew ? 'New Document — Folio Admin' : 'Edit Document — Folio Admin';

  const formHtml = `
    <div style="margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
      <a href="#/admin/documents" class="back-link" id="editorBackLink">&larr; Back to Documents</a>
      <span id="dirtyIndicator" class="badge" style="display: none; background: #e2e8f0; color: #4a5568;">Unsaved changes</span>
    </div>

    <form id="docEditorForm" class="editor-card card" style="padding: 1.5rem;">
      <div id="editorErrorBox" class="notice notice-error" style="display: none; margin-bottom: 1.5rem;"></div>

      <div class="field" style="margin-bottom: 1.25rem;">
        <label class="label" for="editTitle">Document Title *</label>
        <input class="input" type="text" id="editTitle" required maxlength="240" placeholder="e.g. Asymmetric Weighted Reciprocal Rank Fusion" />
      </div>

      <div class="form-grid-2" style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.25rem;">
        <div class="field">
          <label class="label" for="editCategory">Category *</label>
          <select class="select" id="editCategory" required></select>
        </div>
        <div class="field">
          <label class="label" for="editAuthor">Author Attribution</label>
          <input class="input" type="text" id="editAuthor" placeholder="Leave blank to use your display name" />
        </div>
      </div>

      <div class="field" style="margin-bottom: 1.25rem;">
        <label class="label" for="editSummary">Executive Summary * (1–3 sentences)</label>
        <textarea class="textarea" id="editSummary" rows="3" required maxlength="1000" placeholder="Summarize the core thesis, methodology, and key findings..."></textarea>
      </div>

      <div class="field" style="margin-bottom: 1.25rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
          <label class="label" for="editContent" style="margin-bottom: 0;">Markdown Content *</label>
          <div class="editor-tabs" style="display: flex; gap: 0.25rem;">
            <button type="button" class="btn btn-secondary btn-sm active" id="tabWrite">Write</button>
            <button type="button" class="btn btn-secondary btn-sm" id="tabPreview">Preview</button>
          </div>
        </div>
        <textarea class="textarea" id="editContent" rows="15" required placeholder="# Title and Headings&#10;&#10;Write content here in Markdown..."></textarea>
        <div id="editorPreviewBox" class="markdown-preview-box" style="display: none; min-height: 250px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 1.25rem;"></div>
      </div>

      <div class="field" style="margin-bottom: 1.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
          <label class="label" style="margin-bottom: 0;">Assign Research Tags</label>
          <input type="search" id="editorTagSearch" class="input input-sm" placeholder="Filter tags..." style="max-width: 220px; padding: 0.2rem 0.5rem; font-size: 0.8rem;" />
        </div>
        <div id="editorTagsList" class="tags-checkbox-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0.5rem; max-height: 180px; overflow-y: auto; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-bg);">
          <span class="spinner"></span>
        </div>
      </div>

      <hr style="border: none; border-top: 1px solid var(--color-border); margin: 1.5rem 0;" />

      <h4 style="margin: 0 0 1rem 0; font-size: 1rem; color: var(--color-ink);">Provenance & Cover Image (Optional)</h4>

      <div class="form-grid-3" style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-bottom: 1.25rem;">
        <div class="field">
          <label class="label" for="editSourceUrl">Source URL</label>
          <input class="input" type="url" id="editSourceUrl" placeholder="https://arxiv.org/abs/..." />
        </div>
        <div class="field">
          <label class="label" for="editLicense">License</label>
          <input class="input" type="text" id="editLicense" placeholder="CC BY-SA 4.0" />
        </div>
        <div class="field">
          <label class="label" for="editAttribution">Source Attribution</label>
          <input class="input" type="text" id="editAttribution" placeholder="e.g. arXiv / Wikipedia" />
        </div>
      </div>

      <div class="form-grid-2" style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.75rem;">
        <div class="field">
          <label class="label" for="editCoverUrl">Cover Image URL</label>
          <input class="input" type="url" id="editCoverUrl" placeholder="https://example.com/cover.jpg" />
        </div>
        <div class="field">
          <label class="label" for="editCoverAlt">Cover Image Alt Text</label>
          <input class="input" type="text" id="editCoverAlt" placeholder="Short description of the cover image" />
        </div>
      </div>

      <div class="editor-actions-bar" style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--color-border); padding-top: 1.25rem;">
        <div style="display: flex; gap: 0.65rem;" id="editorBtnGroup">
          <button type="button" class="btn btn-secondary" id="saveDraftBtn">Save Draft</button>
          <button type="button" class="btn btn-primary" id="publishDocBtn">Publish to Library</button>
        </div>
        ${!isNew ? `<button type="button" class="btn btn-danger" id="deleteDocBtn">Delete Document</button>` : ''}
      </div>
    </form>
  `;

  container.innerHTML = wrapAdminLayout('/admin/documents', isNew ? 'Create New Document' : 'Edit Research Document', formHtml);

  // Form State & Dirty tracking
  let isDirty = false;
  const dirtyBadge = container.querySelector('#dirtyIndicator');

  function markDirty() {
    if (!isDirty) {
      isDirty = true;
      if (dirtyBadge) dirtyBadge.style.display = 'inline-block';
      registerLeaveGuard(async () => {
        if (!isDirty) return true;
        const ok = await confirmAction({
          title: 'Unsaved Changes',
          message: 'You have unsaved changes in this document. Are you sure you want to discard them and leave?',
          confirmLabel: 'Discard & Leave',
          destructive: true,
        });
        if (ok) {
          resetDirty();
          return true;
        }
        return false;
      });
    }
  }

  function resetDirty() {
    isDirty = false;
    clearLeaveGuard();
    if (dirtyBadge) dirtyBadge.style.display = 'none';
  }

  // Hook input changes to mark dirty
  const formEl = container.querySelector('#docEditorForm');
  formEl.addEventListener('input', markDirty);
  formEl.addEventListener('change', markDirty);

  // Warn on tab closing when dirty
  const beforeUnloadHandler = (e) => {
    if (isDirty) {
      e.preventDefault();
      e.returnValue = '';
    }
  };
  window.addEventListener('beforeunload', beforeUnloadHandler);

  // Intercept back link
  const backLink = container.querySelector('#editorBackLink');
  if (backLink) {
    backLink.addEventListener('click', (e) => {
      e.preventDefault();
      navigate('/admin/documents');
    });
  }

  function updateActionButtons(status) {
    const btnGroup = container.querySelector('#editorBtnGroup');
    if (!btnGroup) return;

    if (!isNew && status === 'published') {
      btnGroup.innerHTML = `
        <button type="button" class="btn btn-primary" id="savePublishedBtn">Save Changes</button>
        <button type="button" class="btn btn-secondary" id="unpublishDocBtn">Save & Unpublish</button>
      `;
      btnGroup.querySelector('#savePublishedBtn').onclick = () => saveDocument('save_published');
      btnGroup.querySelector('#unpublishDocBtn').onclick = () => saveDocument('unpublish');
    } else {
      btnGroup.innerHTML = `
        <button type="button" class="btn btn-primary" id="publishDocBtn">Publish to Library</button>
        <button type="button" class="btn btn-secondary" id="saveDraftBtn">Save Draft</button>
      `;
      btnGroup.querySelector('#publishDocBtn').onclick = () => saveDocument('publish');
      btnGroup.querySelector('#saveDraftBtn').onclick = () => saveDocument('draft');
    }
  }

  updateActionButtons(isNew ? 'draft' : 'draft');

  let selectedTagIds = new Set();
  let allLoadedTags = [];
  let taxonomyLoadFailed = false;
  let existingDoc = null;

  function renderTagsCheckboxList(filter = '') {
    const tagsContainer = container.querySelector('#editorTagsList');
    if (!tagsContainer) return;
    const q = (filter || '').trim().toLowerCase();
    const map = new Map();
    allLoadedTags.forEach(t => map.set(t.id, t));
    if (existingDoc && existingDoc.tags) {
      existingDoc.tags.forEach(t => {
        if (!map.has(t.id)) map.set(t.id, t);
      });
    }
    const list = Array.from(map.values()).filter(t => !q || t.name.toLowerCase().includes(q) || (t.slug && t.slug.toLowerCase().includes(q)));
    if (list.length === 0) {
      tagsContainer.innerHTML = '<div style="grid-column: 1 / -1; color: var(--color-muted); font-size: 0.85rem; padding: 0.5rem;">No tags matching filter.</div>';
      return;
    }
    tagsContainer.innerHTML = list.map(t => {
      const isChecked = selectedTagIds.has(t.id);
      return `
        <label class="tag-checkbox-item" style="display: flex; align-items: center; gap: 0.35rem; font-size: 0.85rem; cursor: pointer;">
          <input type="checkbox" value="${t.id}" class="tag-chk" ${isChecked ? 'checked' : ''} />
          <span>${escapeText(t.name)}</span>
        </label>
      `;
    }).join('');

    tagsContainer.querySelectorAll('.tag-chk').forEach(chk => {
      chk.onchange = () => {
        if (chk.checked) selectedTagIds.add(chk.value);
        else selectedTagIds.delete(chk.value);
        markDirty();
      };
    });
  }

  async function loadTaxonomies() {
    const tagsContainer = container.querySelector('#editorTagsList');
    const catSelect = container.querySelector('#editCategory');
    taxonomyLoadFailed = false;
    try {
      let allTags = [];
      let tagPage = 1;
      let totalTags = 1;
      while (allTags.length < totalTags) {
        const res = await api('/admin/tags', { query: { page: tagPage, page_size: 100 }, signal });
        if (!res.items || res.items.length === 0) break;
        allTags.push(...res.items);
        totalTags = res.total || allTags.length;
        tagPage++;
      }
      allLoadedTags = allTags;

      const catsRes = await api('/admin/categories', { query: { page: 1, page_size: 100 }, signal });
      const currentCatVal = catSelect.value || (existingDoc ? existingDoc.category_id : '');
      catSelect.innerHTML = (catsRes.items || []).map(c => `
        <option value="${c.id}" ${currentCatVal === c.id ? 'selected' : ''}>${escapeText(c.name)}</option>
      `).join('');

      renderTagsCheckboxList(container.querySelector('#editorTagSearch')?.value || '');
    } catch (err) {
      if (signal?.aborted) return;
      taxonomyLoadFailed = true;
      console.error('Failed to load taxonomies:', err);
      tagsContainer.innerHTML = `
        <div class="notice notice-error" style="grid-column: 1 / -1; padding: 0.5rem; margin: 0;">
          <p style="margin: 0 0 0.35rem 0;">Failed to load taxonomies: ${escapeText(err.message)}</p>
          <button type="button" class="btn btn-secondary btn-sm" id="retryEditorTaxonomyBtn">Retry Loading</button>
        </div>
      `;
      const retryBtn = tagsContainer.querySelector('#retryEditorTaxonomyBtn');
      if (retryBtn) retryBtn.onclick = () => loadTaxonomies();
    }
  }

  const tagSearchInput = container.querySelector('#editorTagSearch');
  if (tagSearchInput) {
    tagSearchInput.oninput = () => renderTagsCheckboxList(tagSearchInput.value);
  }

  // Markdown Write vs Preview tab (F1 Safe Markdown Preview via Sanitized Backend Endpoint)
  const writeTab = container.querySelector('#tabWrite');
  const previewTab = container.querySelector('#tabPreview');
  const contentInput = container.querySelector('#editContent');
  const previewBox = container.querySelector('#editorPreviewBox');

  writeTab.onclick = () => {
    writeTab.classList.add('active');
    previewTab.classList.remove('active');
    contentInput.style.display = 'block';
    previewBox.style.display = 'none';
  };

  previewTab.onclick = async () => {
    previewTab.classList.add('active');
    writeTab.classList.remove('active');
    contentInput.style.display = 'none';
    previewBox.style.display = 'block';
    previewBox.innerHTML = '<div style="text-align: center; padding: 2.5rem;"><span class="spinner"></span></div>';

    try {
      const res = await api('/admin/documents/preview', {
        method: 'POST',
        body: { content: contentInput.value || '' },
      });
      previewBox.innerHTML = `<div class="markdown-body" style="font-family: var(--font-ui); color: var(--color-text); line-height: 1.6;">${res.rendered_content || '<p class="text-muted" style="color: var(--color-muted);">No content to preview.</p>'}</div>`;
      renderMathInContainer(previewBox);
    } catch (err) {
      previewBox.innerHTML = `<div class="notice notice-error" style="margin: 1rem 0;"><p>Preview generation failed: ${escapeText(err.message)}</p></div>`;
    }
  };

  await loadTaxonomies();

  // Load existing document if editing
  if (!isNew) {
    try {
      existingDoc = await api(`/admin/documents/${docId}`, { signal });
      container.querySelector('#editTitle').value = existingDoc.title || '';
      container.querySelector('#editSummary').value = existingDoc.summary || '';
      container.querySelector('#editContent').value = existingDoc.content || '';
      container.querySelector('#editCategory').value = existingDoc.category_id || '';
      container.querySelector('#editAuthor').value = existingDoc.author || '';
      container.querySelector('#editSourceUrl').value = existingDoc.source_url || '';
      container.querySelector('#editLicense').value = existingDoc.source_license || '';
      container.querySelector('#editAttribution').value = existingDoc.source_attribution || '';
      container.querySelector('#editCoverUrl').value = existingDoc.cover_image_url || '';
      container.querySelector('#editCoverAlt').value = existingDoc.cover_image_alt || '';

      selectedTagIds = new Set((existingDoc.tags || []).map(t => t.id));
      renderTagsCheckboxList(tagSearchInput?.value || '');

      // Update button labels according to persisted status
      updateActionButtons(existingDoc.status);
      resetDirty();
    } catch (err) {
      if (signal?.aborted) return;
      renderError(container, err);
      return;
    }
  }



  // Save Document logic (F3 Persistent State & Status Alignment)
  async function saveDocument(desiredAction) {
    const errorBox = container.querySelector('#editorErrorBox');
    errorBox.style.display = 'none';

    const title = container.querySelector('#editTitle').value.trim();
    const summary = container.querySelector('#editSummary').value.trim();
    const content = container.querySelector('#editContent').value;
    const category_id = container.querySelector('#editCategory').value;
    if (taxonomyLoadFailed) {
      errorBox.innerHTML = '<strong>Error:</strong> Cannot save document because taxonomy failed to load. Please retry loading tags first.';
      errorBox.style.display = 'block';
      return;
    }

    const author = container.querySelector('#editAuthor').value.trim() || null;
    const source_url = container.querySelector('#editSourceUrl').value.trim() || null;
    const source_license = container.querySelector('#editLicense').value.trim() || null;
    const source_attribution = container.querySelector('#editAttribution').value.trim() || null;
    const cover_image_url = container.querySelector('#editCoverUrl').value.trim() || null;
    const cover_image_alt = container.querySelector('#editCoverAlt').value.trim() || null;

    const selectedTags = Array.from(selectedTagIds);

    // Validation
    if (!title || !summary || !content || !category_id) {
      errorBox.innerHTML = '<strong>Validation Error:</strong> Please fill in all required fields marked with * (Title, Category, Summary, and Content).';
      errorBox.style.display = 'block';
      return;
    }

    const payload = {
      title,
      summary,
      content,
      category_id,
      tag_ids: selectedTags,
      author,
      source_url,
      source_license,
      source_attribution,
      cover_image_url,
      cover_image_alt,
    };

    const actionBtns = container.querySelectorAll('#editorBtnGroup button');

    try {
      actionBtns.forEach(b => b.disabled = true);

      let savedDoc;
      if (isNew) {
        // Create document draft first
        savedDoc = await api('/admin/documents', {
          method: 'POST',
          body: payload,
        });

        // Update state to existing doc to ensure publish retries do not create duplicate drafts
        docId = savedDoc.id;
        isNew = false;
        try {
          window.history.replaceState(null, '', `#/admin/documents/${docId}/edit`);
        } catch (_) {}

        if (desiredAction === 'publish') {
          savedDoc = await api(`/admin/documents/${docId}/status`, {
            method: 'PATCH',
            body: { status: 'published' },
          });
        }
      } else {
        // Update document metadata & content
        savedDoc = await api(`/admin/documents/${docId}`, {
          method: 'PATCH',
          body: payload,
        });

        // Handle status transition explicitly
        if (desiredAction === 'publish' && savedDoc.status !== 'published') {
          savedDoc = await api(`/admin/documents/${docId}/status`, {
            method: 'PATCH',
            body: { status: 'published' },
          });
        } else if ((desiredAction === 'unpublish' || desiredAction === 'draft') && savedDoc.status !== 'draft') {
          savedDoc = await api(`/admin/documents/${docId}/status`, {
            method: 'PATCH',
            body: { status: 'draft' },
          });
        }
      }

      resetDirty();
      const statusLabel = savedDoc.status === 'published' ? 'published' : 'saved as draft';
      notify(`Document successfully ${statusLabel}.`, { kind: 'success' });
      navigate('/admin/documents');
    } catch (err) {
      // Keep form inputs intact! Do NOT clear fields.
      let errorMsg = err.message || 'Failed to save document.';
      if (err.fields && Object.keys(err.fields).length > 0) {
        const fieldDetails = Object.entries(err.fields)
          .map(([f, msgs]) => `<li><strong>${escapeText(f)}:</strong> ${escapeText(Array.isArray(msgs) ? msgs.join(', ') : msgs)}</li>`)
          .join('');
        errorMsg += `<ul style="margin: 0.5rem 0 0 1rem; padding: 0;">${fieldDetails}</ul>`;
      }
      errorBox.innerHTML = `<strong>Error:</strong> ${errorMsg}`;
      errorBox.style.display = 'block';
    } finally {
      actionBtns.forEach(b => b.disabled = false);
    }
  }

  // Delete button
  const delBtn = container.querySelector('#deleteDocBtn');
  if (delBtn) {
    delBtn.onclick = async () => {
      const ok = await confirmAction({
        title: 'Delete Document',
        message: 'Are you sure you want to soft-delete this document? It will be removed from the public library.',
        confirmLabel: 'Delete Document',
        destructive: true,
      });

      if (ok) {
        try {
          delBtn.disabled = true;
          await api(`/admin/documents/${docId}`, { method: 'DELETE' });
          resetDirty();
          notify('Document soft-deleted.', { kind: 'success' });
          navigate('/admin/documents');
        } catch (err) {
          notify(err.message || 'Failed to delete', { kind: 'error' });
          delBtn.disabled = false;
        }
      }
    };
  }

  // Cleanup on route unmount
  return () => {
    clearLeaveGuard();
    window.removeEventListener('beforeunload', beforeUnloadHandler);
  };
}

// ==============================================================================
// 3. Taxonomy Management: Categories & Tags (with Clean Modals & 409 Conflict Handling)
// ==============================================================================

export async function renderTaxonomyManager(container, routeContext) {
  if (!can('taxonomy:write')) {
    container.innerHTML = wrapAdminLayout(
      '/admin/taxonomy',
      'Access Forbidden',
      '<div class="notice notice-error"><h3>403 Forbidden</h3><p>Your account does not have permission to manage taxonomy.</p></div>'
    );
    return;
  }

  const { signal } = routeContext;
  document.title = 'Taxonomy Management — Folio Admin';

  const html = `
    <div class="taxonomy-grid">
      <!-- Categories Panel -->
      <div class="taxonomy-panel card" style="padding: 1.25rem;">
        <div class="panel-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
          <h3 style="margin: 0;">Categories</h3>
          <button class="btn btn-primary btn-sm" id="addCategoryBtn">+ New Category</button>
        </div>
        <div id="categoriesListArea" class="table-container">
          <div style="text-align: center; padding: 2rem;"><span class="spinner"></span></div>
        </div>
      </div>

      <!-- Tags Panel -->
      <div class="taxonomy-panel card" style="padding: 1.25rem;">
        <div class="panel-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <h3 style="margin: 0;">Tags</h3>
            <span class="badge badge-gray" id="tagsTotalBadge" style="display: none;">0</span>
          </div>
          <button class="btn btn-primary btn-sm" id="addTagBtn">+ New Tag</button>
        </div>
        <div style="margin-bottom: 0.75rem;">
          <input type="search" class="input input-sm" id="taxonomyTagSearchInput" placeholder="Filter tags by name..." aria-label="Filter tags" style="width: 100%;" />
        </div>
        <div id="tagsListArea" class="table-container">
          <div style="text-align: center; padding: 2rem;"><span class="spinner"></span></div>
        </div>
        <div id="tagsPaginationBar" style="margin-top: 0.75rem;"></div>
      </div>
    </div>

    <!-- Modal Root for Category/Tag CRUD Dialogs -->
    <div id="taxonomyModalRoot"></div>
  `;

  container.innerHTML = wrapAdminLayout('/admin/taxonomy', 'Taxonomy & Classification', html);

  const modalRoot = container.querySelector('#taxonomyModalRoot');
  const tagSearchInput = container.querySelector('#taxonomyTagSearchInput');
  const tagsTotalBadge = container.querySelector('#tagsTotalBadge');
  const tagsPaginationBar = container.querySelector('#tagsPaginationBar');

  let loadGeneration = 0;
  let tagPage = 1;
  const tagPageSize = 50;
  let tagQuery = '';
  let tagSearchTimer = null;

  async function loadTaxonomies(clampAttempt = 0) {
    const gen = ++loadGeneration;
    const catArea = container.querySelector('#categoriesListArea');
    const tagArea = container.querySelector('#tagsListArea');

    if (catArea && !catArea.querySelector('table')) {
      catArea.innerHTML = '<div style="text-align: center; padding: 2rem;"><span class="spinner" aria-label="Loading categories..."></span></div>';
    }
    if (tagArea && clampAttempt === 0) {
      tagArea.innerHTML = '<div style="text-align: center; padding: 2rem;"><span class="spinner" aria-label="Loading tags..."></span></div>';
    }

    try {
      const [catsRes, tagsRes] = await Promise.all([
        api('/admin/categories', { query: { page: 1, page_size: 100 }, signal }),
        api('/admin/tags', { query: { q: tagQuery || undefined, page: tagPage, page_size: tagPageSize }, signal }),
      ]);

      if (signal?.aborted || gen !== loadGeneration) return;

      const totalTags = Number(tagsRes.total ?? (tagsRes.items ? tagsRes.items.length : 0));
      const totalPages = totalTags > 0 ? Math.max(1, Math.ceil(totalTags / tagPageSize)) : 1;

      if (totalTags === 0) {
        tagPage = 1;
      } else if ((!tagsRes.items || tagsRes.items.length === 0) && tagPage > totalPages && clampAttempt < 2) {
        tagPage = totalPages;
        return await loadTaxonomies(clampAttempt + 1);
      }

      // Categories Table
      if (!catsRes.items || catsRes.items.length === 0) {
        catArea.innerHTML = '<div class="empty-state" style="padding: 1.5rem; text-align: center;">No categories configured.</div>';
      } else {
        const catRows = catsRes.items.map(c => `
          <tr data-cat-id="${c.id}" data-cat-name="${escapeAttr(c.name)}" data-cat-slug="${escapeAttr(c.slug)}" data-cat-desc="${escapeAttr(c.description || '')}">
            <td>
              <strong>${escapeText(c.name)}</strong>
              <div style="font-size: 0.75rem; color: var(--color-muted); font-family: monospace;">${escapeText(c.slug)}</div>
              ${c.description ? `<div style="font-size: 0.8rem; color: var(--color-muted);">${escapeText(c.description)}</div>` : ''}
            </td>
            <td><span class="badge badge-info">${c.document_count}</span></td>
            <td style="white-space: nowrap;">
              <div style="display: flex; gap: 0.25rem;">
                <button class="btn btn-secondary btn-sm edit-cat-btn">Edit</button>
                <button class="btn btn-danger btn-sm del-cat-btn">Delete</button>
              </div>
            </td>
          </tr>
        `).join('');

        catArea.innerHTML = `
          <table class="table">
            <thead><tr><th>Category</th><th>Docs</th><th>Actions</th></tr></thead>
            <tbody>${catRows}</tbody>
          </table>
        `;
      }

      // Tags Table & Pagination (R07 / R3-03 clamped)
      if (tagsTotalBadge) {
        tagsTotalBadge.textContent = String(totalTags);
        tagsTotalBadge.style.display = 'inline-block';
      }

      if (!tagsRes.items || tagsRes.items.length === 0) {
        tagArea.innerHTML = `<div class="empty-state" style="padding: 1.5rem; text-align: center;">${tagQuery ? 'No tags match your filter.' : 'No tags configured.'}</div>`;
        if (tagsPaginationBar) tagsPaginationBar.innerHTML = '';
      } else {
        const tagRows = tagsRes.items.map(t => `
          <tr data-tag-id="${t.id}" data-tag-name="${escapeAttr(t.name)}" data-tag-slug="${escapeAttr(t.slug)}">
            <td>
              <strong>${escapeText(t.name)}</strong>
              <div style="font-size: 0.75rem; color: var(--color-muted); font-family: monospace;">${escapeText(t.slug)}</div>
            </td>
            <td><span class="badge badge-gray">${t.document_count}</span></td>
            <td style="white-space: nowrap;">
              <div style="display: flex; gap: 0.25rem;">
                <button class="btn btn-secondary btn-sm edit-tag-btn">Edit</button>
                <button class="btn btn-danger btn-sm del-tag-btn">Delete</button>
              </div>
            </td>
          </tr>
        `).join('');

        tagArea.innerHTML = `
          <table class="table">
            <thead><tr><th>Tag</th><th>Docs</th><th>Actions</th></tr></thead>
            <tbody>${tagRows}</tbody>
          </table>
        `;

        if (tagsPaginationBar) {
          if (totalPages > 1) {
            tagsPaginationBar.innerHTML = `
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                <span style="font-size: 0.8rem; color: var(--color-muted);">Page ${tagPage} of ${totalPages} (${totalTags} tags)</span>
                <div style="display: flex; gap: 0.35rem;">
                  <button type="button" class="btn btn-secondary btn-sm" id="tagsPrevPageBtn" ${tagPage <= 1 ? 'disabled' : ''}>Previous</button>
                  <button type="button" class="btn btn-secondary btn-sm" id="tagsNextPageBtn" ${tagPage >= totalPages ? 'disabled' : ''}>Next</button>
                </div>
              </div>
            `;
            const prevBtn = tagsPaginationBar.querySelector('#tagsPrevPageBtn');
            const nextBtn = tagsPaginationBar.querySelector('#tagsNextPageBtn');
            if (prevBtn) prevBtn.onclick = () => { if (tagPage > 1) { tagPage -= 1; loadTaxonomies(); } };
            if (nextBtn) nextBtn.onclick = () => { if (tagPage < totalPages) { tagPage += 1; loadTaxonomies(); } };
          } else {
            tagsPaginationBar.innerHTML = '';
          }
        }
      }

      // Bind Category Edit
      catArea.querySelectorAll('.edit-cat-btn').forEach(btn => {
        btn.onclick = () => {
          const tr = btn.closest('tr');
          showCategoryModal({
            id: tr.getAttribute('data-cat-id'),
            name: tr.getAttribute('data-cat-name'),
            slug: tr.getAttribute('data-cat-slug'),
            description: tr.getAttribute('data-cat-desc'),
          });
        };
      });

      // Bind Category Delete with 409 Conflict Protection
      catArea.querySelectorAll('.del-cat-btn').forEach(btn => {
        btn.onclick = async () => {
          const tr = btn.closest('tr');
          const id = tr.getAttribute('data-cat-id');
          const name = tr.getAttribute('data-cat-name');

          const ok = await confirmAction({
            title: `Delete Category "${name}"`,
            message: `Are you sure you want to delete category "${name}"? Categories in use by documents cannot be deleted.`,
            confirmLabel: 'Delete Category',
            destructive: true,
          });

          if (ok) {
            try {
              btn.disabled = true;
              await api(`/admin/categories/${id}`, { method: 'DELETE' });
              notify('Category deleted successfully.', { kind: 'success' });
              loadTaxonomies();
            } catch (err) {
              // 409 Conflict or other errors
              notify(err.message || 'Cannot delete category: it is currently assigned to documents.', { kind: 'error' });
              btn.disabled = false;
            }
          }
        };
      });

      // Bind Tag Edit
      tagArea.querySelectorAll('.edit-tag-btn').forEach(btn => {
        btn.onclick = () => {
          const tr = btn.closest('tr');
          showTagModal({
            id: tr.getAttribute('data-tag-id'),
            name: tr.getAttribute('data-tag-name'),
            slug: tr.getAttribute('data-tag-slug'),
          });
        };
      });

      // Bind Tag Delete with 409 Conflict Protection
      tagArea.querySelectorAll('.del-tag-btn').forEach(btn => {
        btn.onclick = async () => {
          const tr = btn.closest('tr');
          const id = tr.getAttribute('data-tag-id');
          const name = tr.getAttribute('data-tag-name');

          const ok = await confirmAction({
            title: `Delete Tag "${name}"`,
            message: `Are you sure you want to delete tag "${name}"? Tags assigned to documents cannot be deleted.`,
            confirmLabel: 'Delete Tag',
            destructive: true,
          });

          if (ok) {
            try {
              btn.disabled = true;
              await api(`/admin/tags/${id}`, { method: 'DELETE' });
              notify('Tag deleted successfully.', { kind: 'success' });
              loadTaxonomies();
            } catch (err) {
              // 409 Conflict or other errors
              notify(err.message || 'Cannot delete tag: it is currently assigned to documents.', { kind: 'error' });
              btn.disabled = false;
            }
          }
        };
      });

    } catch (err) {
      if (signal?.aborted || gen !== loadGeneration) return;
      console.error('Failed to load taxonomies:', err);
      const errMsg = escapeText(err?.message || 'Unable to load taxonomy items.');
      const renderPanelError = (panelId, retryBtnId) => {
        const area = container.querySelector(panelId);
        if (!area) return;
        area.innerHTML = `
          <div class="notice notice-error" role="alert" style="margin: 0.75rem;">
            <p style="margin: 0 0 0.5rem 0;"><strong>Failed to load taxonomy:</strong> ${errMsg}</p>
            <button type="button" class="btn btn-secondary btn-sm" id="${retryBtnId}">Retry Loading</button>
          </div>
        `;
        const retryBtn = area.querySelector(`#${retryBtnId}`);
        if (retryBtn) retryBtn.onclick = () => loadTaxonomies();
      };
      renderPanelError('#categoriesListArea', 'retryCategoriesLoadBtn');
      renderPanelError('#tagsListArea', 'retryTagsLoadBtn');
      if (tagsPaginationBar) tagsPaginationBar.innerHTML = '';
    }
  }

  if (tagSearchInput) {
    tagSearchInput.oninput = () => {
      clearTimeout(tagSearchTimer);
      tagSearchTimer = setTimeout(() => {
        tagQuery = tagSearchInput.value.trim();
        tagPage = 1;
        loadTaxonomies();
      }, 150);
    };
  }

  // Modal helper for Category Create/Edit
  function showCategoryModal(category = null) {
    const isEdit = !!category;
    modalRoot.innerHTML = `
      <div class="modal-backdrop" id="catModalBackdrop">
        <div class="modal-dialog card" style="max-width: 480px; margin: 10vh auto; padding: 1.5rem;">
          <h3 style="margin-top: 0;">${isEdit ? 'Edit Category' : 'Create New Category'}</h3>
          
          <div id="catModalError" class="notice notice-error" style="display: none; margin-bottom: 1rem;"></div>

          <div class="field" style="margin-bottom: 1rem;">
            <label class="label" for="catModalName">Category Name *</label>
            <input type="text" id="catModalName" class="input" value="${escapeAttr(category?.name || '')}" placeholder="e.g. Machine Learning" required />
          </div>

          <div class="field" style="margin-bottom: 1rem;">
            <label class="label" for="catModalSlug">Slug (Optional)</label>
            <input type="text" id="catModalSlug" class="input" value="${escapeAttr(category?.slug || '')}" placeholder="e.g. machine-learning" />
          </div>

          <div class="field" style="margin-bottom: 1.5rem;">
            <label class="label" for="catModalDesc">Description (Optional)</label>
            <textarea id="catModalDesc" class="textarea" rows="3" placeholder="Brief description of this category...">${escapeText(category?.description || '')}</textarea>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 0.5rem;">
            <button type="button" class="btn btn-secondary" id="cancelCatModalBtn">Cancel</button>
            <button type="button" class="btn btn-primary" id="saveCatModalBtn">${isEdit ? 'Save Changes' : 'Create Category'}</button>
          </div>
        </div>
      </div>
    `;

    const backdrop = modalRoot.querySelector('#catModalBackdrop');
    const cancelBtn = modalRoot.querySelector('#cancelCatModalBtn');
    const saveBtn = modalRoot.querySelector('#saveCatModalBtn');
    const errBox = modalRoot.querySelector('#catModalError');

    function closeModal() {
      modalRoot.innerHTML = '';
    }

    cancelBtn.onclick = closeModal;
    backdrop.onclick = (e) => {
      if (e.target === backdrop) closeModal();
    };

    saveBtn.onclick = async () => {
      const name = modalRoot.querySelector('#catModalName').value.trim();
      const slug = modalRoot.querySelector('#catModalSlug').value.trim() || undefined;
      const description = modalRoot.querySelector('#catModalDesc').value.trim() || null;

      if (!name) {
        errBox.textContent = 'Category Name is required.';
        errBox.style.display = 'block';
        return;
      }

      try {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
        if (isEdit) {
          await api(`/admin/categories/${category.id}`, {
            method: 'PATCH',
            body: { name, slug, description }
          });
          notify('Category updated.', { kind: 'success' });
        } else {
          await api('/admin/categories', {
            method: 'POST',
            body: { name, slug, description }
          });
          notify('Category created.', { kind: 'success' });
        }
        closeModal();
        loadTaxonomies();
      } catch (err) {
        errBox.textContent = err.message || 'Operation failed.';
        errBox.style.display = 'block';
        saveBtn.disabled = false;
        saveBtn.textContent = isEdit ? 'Save Changes' : 'Create Category';
      }
    };
  }

  // Modal helper for Tag Create/Edit
  function showTagModal(tag = null) {
    const isEdit = !!tag;
    modalRoot.innerHTML = `
      <div class="modal-backdrop" id="tagModalBackdrop">
        <div class="modal-dialog card" style="max-width: 440px; margin: 10vh auto; padding: 1.5rem;">
          <h3 style="margin-top: 0;">${isEdit ? 'Edit Tag' : 'Create New Tag'}</h3>
          
          <div id="tagModalError" class="notice notice-error" style="display: none; margin-bottom: 1rem;"></div>

          <div class="field" style="margin-bottom: 1rem;">
            <label class="label" for="tagModalName">Tag Name *</label>
            <input type="text" id="tagModalName" class="input" value="${escapeAttr(tag?.name || '')}" placeholder="e.g. Deep Learning" required />
          </div>

          <div class="field" style="margin-bottom: 1.5rem;">
            <label class="label" for="tagModalSlug">Slug (Optional)</label>
            <input type="text" id="tagModalSlug" class="input" value="${escapeAttr(tag?.slug || '')}" placeholder="e.g. deep-learning" />
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 0.5rem;">
            <button type="button" class="btn btn-secondary" id="cancelTagModalBtn">Cancel</button>
            <button type="button" class="btn btn-primary" id="saveTagModalBtn">${isEdit ? 'Save Changes' : 'Create Tag'}</button>
          </div>
        </div>
      </div>
    `;

    const backdrop = modalRoot.querySelector('#tagModalBackdrop');
    const cancelBtn = modalRoot.querySelector('#cancelTagModalBtn');
    const saveBtn = modalRoot.querySelector('#saveTagModalBtn');
    const errBox = modalRoot.querySelector('#tagModalError');

    function closeModal() {
      modalRoot.innerHTML = '';
    }

    cancelBtn.onclick = closeModal;
    backdrop.onclick = (e) => {
      if (e.target === backdrop) closeModal();
    };

    saveBtn.onclick = async () => {
      const name = modalRoot.querySelector('#tagModalName').value.trim();
      const slug = modalRoot.querySelector('#tagModalSlug').value.trim() || undefined;

      if (!name) {
        errBox.textContent = 'Tag Name is required.';
        errBox.style.display = 'block';
        return;
      }

      try {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
        if (isEdit) {
          await api(`/admin/tags/${tag.id}`, {
            method: 'PATCH',
            body: { name, slug }
          });
          notify('Tag updated.', { kind: 'success' });
        } else {
          await api('/admin/tags', {
            method: 'POST',
            body: { name, slug }
          });
          notify('Tag created.', { kind: 'success' });
        }
        closeModal();
        loadTaxonomies();
      } catch (err) {
        errBox.textContent = err.message || 'Operation failed.';
        errBox.style.display = 'block';
        saveBtn.disabled = false;
        saveBtn.textContent = isEdit ? 'Save Changes' : 'Create Tag';
      }
    };
  }

  // Hook toolbar buttons
  container.querySelector('#addCategoryBtn').onclick = () => showCategoryModal();
  container.querySelector('#addTagBtn').onclick = () => showTagModal();



  await loadTaxonomies();
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
