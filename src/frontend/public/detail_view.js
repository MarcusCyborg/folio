// src/frontend/public/detail_view.js
// Document Reading View, Provenance, View & Search Click Analytics, Like, and Discussions

import { api } from '../core/api.js';
import { getSession } from '../core/session.js';
import { notify, confirmAction, renderError } from '../core/ui.js';
import { navigate } from '../core/router.js';
import { attachMentionsAutocomplete } from './mentions.js';

function genUuid() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

function getSafeHttpUrl(url) {
  if (!url || typeof url !== 'string') return null;
  const trimmed = url.trim();
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }
  return null;
}

export async function renderDocumentDetail(container, routeContext) {
  const { params, query, signal } = routeContext;
  const docId = params.id;
  const searchEventId = query.get('search_event_id');
  const session = getSession();

  let cleanupMentions = null;
  let prevMetaDesc = '';
  let metaDescEl = document.querySelector('meta[name="description"]');
  if (metaDescEl) {
    prevMetaDesc = metaDescEl.getAttribute('content') || '';
  }

  container.innerHTML = `
    <div class="public-page" style="padding-top: 1rem;">
      <a href="#/library" class="back-link">← Back to Library Catalog</a>
      <div id="detailLoading" style="text-align: center; padding: 4rem;">
        <span class="spinner"></span>
        <p style="color: var(--color-muted); margin-top: 1rem;">Loading document...</p>
      </div>
      <div id="detailContent" style="display: none;"></div>
    </div>
  `;

  try {
    // Fetch document detail and public settings concurrently
    const [doc, publicSettings] = await Promise.all([
      api(`/documents/${docId}`, { signal }),
      api('/settings/public', { signal }).catch(() => ({ comments_enabled: true })),
    ]);

    const contentEl = container.querySelector('#detailContent');
    const loadingEl = container.querySelector('#detailLoading');
    if (loadingEl) loadingEl.style.display = 'none';
    if (!contentEl) return;
    contentEl.style.display = 'block';

    // Update document title and meta description for reading view (using SEO title when present)
    const siteTitle = publicSettings.site_name || 'Folio';
    document.title = `${doc.seo_title || doc.title} — ${siteTitle}`;
    if (!metaDescEl) {
      metaDescEl = document.createElement('meta');
      metaDescEl.setAttribute('name', 'description');
      document.head.appendChild(metaDescEl);
    }
    metaDescEl.setAttribute('content', doc.seo_description || doc.summary || 'Folio Research Library document');

    // 1. Record View Event (Idempotent per navigation)
    const navigationId = genUuid();
    api(`/documents/${doc.id}/views`, {
      method: 'POST',
      body: { navigation_id: navigationId },
    }).catch((err) => console.warn('View logging error (non-fatal):', err));

    const addedDate = new Date(doc.created_at).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

    const tagsHtml = (doc.tags || []).map(t =>
      `<a href="#/library?tag_ids=${t.id}" class="tag-chip">${escapeText(t.name)}</a>`
    ).join(' ');

    const safeSourceUrl = getSafeHttpUrl(doc.source_url);
    const safeCoverImageUrl = getSafeHttpUrl(doc.cover_image_url);

    // Check user suspension status
    const now = new Date();
    const userSuspensionDate = session.user && session.user.commenting_suspended_until
      ? new Date(session.user.commenting_suspended_until)
      : null;
    const isUserSuspended = userSuspensionDate && userSuspensionDate > now;

    contentEl.innerHTML = `
      <article class="document-detail-article">
        <!-- Header & Metadata -->
        <header class="detail-header">
          <div class="detail-meta-top">
            <span class="badge badge-teal">${escapeText(doc.category ? doc.category.name : 'Research')}</span>
            <span class="detail-date">Added ${addedDate}</span>
          </div>

          <h1 class="detail-title">${escapeText(doc.title)}</h1>

          <div class="detail-byline-bar">
            <div class="detail-byline-left">
              <span class="detail-author">By <strong>${escapeText(doc.author || 'Wikipedia contributors')}</strong></span>
              <span class="meta-dot">•</span>
              <span class="detail-date">Added ${addedDate}</span>
              ${safeSourceUrl ? `
                <span class="meta-dot">•</span>
                <a href="${escapeAttr(safeSourceUrl)}" target="_blank" rel="noopener noreferrer" class="byline-source-link">Source Article ↗</a>
              ` : ''}
            </div>
            <div class="detail-stats-bar">
              <span id="viewCountDisplay" class="counter-badge" title="${doc.views_count} views">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                <span>${doc.views_count} views</span>
              </span>
              <button id="likeBtn" class="like-btn ${doc.liked_by_me ? 'liked' : ''}" aria-label="${doc.liked_by_me ? 'Unlike document' : 'Like document'}" aria-pressed="${doc.liked_by_me ? 'true' : 'false'}">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="${doc.liked_by_me ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                <span id="likeCountText">${doc.likes_count}</span>
              </button>
            </div>
          </div>

          <div class="detail-summary-card">
            <strong class="summary-kicker">Summary:</strong>
            <p>${escapeText(doc.summary)}</p>
          </div>

          ${safeCoverImageUrl ? `
            <div class="detail-cover-container">
              <img src="${escapeAttr(safeCoverImageUrl)}" alt="${escapeAttr(doc.cover_image_alt || doc.title)}" class="detail-cover-image" loading="lazy" />
              ${doc.cover_image_alt ? `<div class="detail-cover-caption">${escapeText(doc.cover_image_alt)}</div>` : ''}
            </div>
          ` : ''}

          <div class="detail-tags-wrapper">
            ${tagsHtml}
          </div>
        </header>

        <!-- Sanitized Rendered Content Body (allowlisted server-side) -->
        <main class="document-reading-column markdown-body">
          ${doc.rendered_content}
        </main>

        <!-- Provenance & Source Attribution -->
        <footer class="detail-footer-provenance">
          <h4>Source & License Attribution</h4>
          <p>
            This article is part of Folio's verified research library. Source attribution:
            <strong>${escapeText(doc.source_attribution || 'Wikipedia contributors')}</strong>.
            Licensed under <em>${escapeText(doc.source_license || 'CC BY-SA 4.0')}</em>.
          </p>
          ${safeSourceUrl ? `
            <p>Original source repository:
              <a href="${escapeAttr(safeSourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeText(doc.source_url)}</a>
            </p>
          ` : (doc.source_url ? `
            <p>Original source record: <code>${escapeText(doc.source_url)}</code></p>
          ` : '')}
        </footer>
      </article>

      <!-- Comments & Discussion Section -->
      <section class="comments-section" aria-label="Comments and Discussion">
        <h3 class="comments-title">Discussion & Peer Notes (<span id="commentsCountHeader">${doc.comments_count}</span>)</h3>

        <!-- Status Warnings: Disabled Comments or User Suspension -->
        ${!publicSettings.comments_enabled ? `
          <div class="notice notice-warning" style="margin-bottom: 1.5rem;">
            <strong>Discussions Closed:</strong> Commenting is currently disabled library-wide by administrators. Existing notes remain readable.
          </div>
        ` : (isUserSuspended ? `
          <div class="notice notice-error" style="margin-bottom: 1.5rem;">
            <strong>Commenting Suspended:</strong> Your account's commenting privileges are suspended until ${userSuspensionDate.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}. You may read notes, but cannot post or edit notes.
          </div>
        ` : '')}

        <!-- Comment Compose Card -->
        ${publicSettings.comments_enabled && !isUserSuspended ? `
          <div class="comment-compose-card" id="commentComposeCard">
            ${session.user ? `
              <div class="comment-compose-header">Posting as <strong>${escapeText(session.user.display_name)}</strong> (@${escapeText(session.user.username)})</div>
              <div class="textarea-mentions-wrapper" style="position: relative;">
                <textarea id="commentBodyInput" class="textarea" rows="3" placeholder="Share a peer note or research insight (type @ to tag a researcher)..."></textarea>
              </div>
              <div class="comment-compose-actions">
                <span id="composeError" class="compose-error" style="display: none;"></span>
                <button class="btn btn-primary btn-sm" id="submitCommentBtn">Post Note</button>
              </div>
            ` : `
              <div class="comment-login-prompt">
                <p>Sign in to contribute research notes or mention colleagues in discussions.</p>
                <a href="#/login?next=/documents/${doc.id}" class="btn btn-primary btn-sm">Sign In to Comment</a>
              </div>
            `}
          </div>
        ` : ''}

        <!-- Comments Feed Container -->
        <div id="commentsFeedContainer" class="comments-feed">
          <div style="text-align: center; padding: 2rem;"><span class="spinner"></span></div>
        </div>

        <!-- Comments Pagination -->
        <div id="commentsPaginationContainer" class="comments-pagination-bar" style="margin-top: 1.5rem;"></div>
      </section>

      <!-- Modal Dialog Container for Reporting Comments -->
      <div id="reportModalContainer"></div>
    `;

    // Generate Table of Contents from headings (D5)
    const readingColumn = contentEl.querySelector('.document-reading-column');
    if (readingColumn) {
      const headings = readingColumn.querySelectorAll('h1, h2, h3');
      if (headings.length >= 2) {
        const tocItems = [];
        const usedSlugs = new Set();

        headings.forEach((h, idx) => {
          let slug = h.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
          if (!slug) slug = `section-${idx + 1}`;
          let finalSlug = slug;
          let counter = 1;
          while (usedSlugs.has(finalSlug)) {
            finalSlug = `${slug}-${counter++}`;
          }
          usedSlugs.add(finalSlug);
          h.id = finalSlug;
          h.classList.add('reading-section-anchor');

          const level = parseInt(h.tagName.substring(1), 10);
          tocItems.push(`
            <li class="toc-item toc-level-${level}">
              <a href="#${finalSlug}">${escapeText(h.textContent.trim())}</a>
            </li>
          `);
        });

        const tocBox = document.createElement('nav');
        tocBox.className = 'document-toc card';
        tocBox.setAttribute('aria-label', 'Table of Contents');
        tocBox.innerHTML = `
          <div class="toc-header">
            <span class="toc-title">Table of Contents</span>
          </div>
          <ol class="toc-list">
            ${tocItems.join('')}
          </ol>
        `;
        readingColumn.parentNode.insertBefore(tocBox, readingColumn);

        tocBox.querySelectorAll('a').forEach((link) => {
          link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('href').slice(1);
            const targetEl = document.getElementById(targetId);
            if (targetEl) {
              targetEl.scrollIntoView({ behavior: 'smooth' });
            }
          });
        });
      }
    }

    // Hook up Like / Unlike button with idempotency and pending state
    const likeBtn = contentEl.querySelector('#likeBtn');
    const likeCountText = contentEl.querySelector('#likeCountText');
    let isLiked = doc.liked_by_me;
    let likesCount = doc.likes_count;
    let likePending = false;

    if (likeBtn) {
      likeBtn.onclick = async () => {
        const currentSession = getSession();
        if (!currentSession.user) {
          notify('Please sign in to like documents.', { kind: 'info' });
          navigate(`/login?next=/documents/${doc.id}`);
          return;
        }
        if (likePending) return;
        likePending = true;
        likeBtn.disabled = true;

        const nextAction = !isLiked;
        try {
          const res = await api(`/documents/${doc.id}/like`, {
            method: nextAction ? 'PUT' : 'DELETE',
          });
          isLiked = res.liked_by_me;
          likesCount = res.likes_count;
          likeBtn.classList.toggle('liked', isLiked);
          likeBtn.setAttribute('aria-pressed', isLiked ? 'true' : 'false');
          likeBtn.setAttribute('aria-label', isLiked ? 'Unlike document' : 'Like document');
          likeBtn.querySelector('.heart-icon').textContent = isLiked ? '♥' : '♡';
          likeCountText.textContent = likesCount;
          notify(isLiked ? 'Added to your favorites' : 'Removed from favorites', { kind: 'success' });
        } catch (err) {
          notify(err.message || 'Failed to update like status', { kind: 'error' });
        } finally {
          likePending = false;
          likeBtn.disabled = false;
        }
      };
    }

    // Attach @mentions autocomplete to main compose textarea
    const mainCommentInput = contentEl.querySelector('#commentBodyInput');
    const mentionsWrapper = contentEl.querySelector('.textarea-mentions-wrapper');
    if (mainCommentInput && mentionsWrapper) {
      cleanupMentions = attachMentionsAutocomplete(mainCommentInput, mentionsWrapper);
    }

    // State for comments pagination
    let commentPage = 1;
    const commentPageSize = 10;

    async function fetchAndRenderComments(targetPage = 1) {
      commentPage = targetPage;
      const feed = contentEl.querySelector('#commentsFeedContainer');
      const countHeader = contentEl.querySelector('#commentsCountHeader');
      const paginationContainer = contentEl.querySelector('#commentsPaginationContainer');
      if (!feed) return;

      feed.innerHTML = '<div style="text-align: center; padding: 2rem;"><span class="spinner"></span></div>';

      try {
        const data = await api(`/documents/${doc.id}/comments`, {
          query: { page: commentPage, page_size: commentPageSize },
          signal,
        });

        if (countHeader) countHeader.textContent = data.total;

        if (data.items.length === 0) {
          feed.innerHTML = `
            <div class="empty-state" style="padding: 2.5rem 1rem;">
              <p>No research notes recorded yet. Be the first to share an insight!</p>
            </div>
          `;
          if (paginationContainer) paginationContainer.innerHTML = '';
          return;
        }

        feed.innerHTML = '';
        data.items.forEach((c) => {
          const itemEl = document.createElement('div');
          itemEl.className = 'comment-card';
          itemEl.setAttribute('id', `comment-${c.id}`);

          const cDate = new Date(c.created_at).toLocaleString('en-US', {
            dateStyle: 'medium',
            timeStyle: 'short',
          });

          const mentionsHtml = (c.mentions || []).map(m =>
            `<span class="mention-tag">@${escapeText(m.username)}</span>`
          ).join(' ');

          const isOwner = c.can_edit || c.can_delete;

          itemEl.innerHTML = `
            <div class="comment-header">
              <div class="comment-author-info">
                <strong>${escapeText(c.author.display_name)}</strong>
                <span class="comment-handle">@${escapeText(c.author.username)}</span>
                <span class="comment-time">${cDate}</span>
                ${c.updated_at && c.updated_at !== c.created_at ? '<span class="comment-edited-tag">(edited)</span>' : ''}
              </div>
              <div class="comment-actions">
                ${c.can_edit && !isUserSuspended ? `<button class="btn btn-secondary btn-sm edit-comment-btn">Edit</button>` : ''}
                ${c.can_delete ? `<button class="btn btn-secondary btn-sm delete-comment-btn">Delete</button>` : ''}
                ${!isOwner ? `<button class="btn btn-secondary btn-sm report-comment-btn" title="Report this note to moderators">Report</button>` : ''}
              </div>
            </div>
            <div class="comment-body-container">
              <div class="comment-body-text">${escapeText(c.body)}</div>
            </div>
            ${mentionsHtml ? `<div class="comment-mentions-bar">Mentioned: ${mentionsHtml}</div>` : ''}
          `;

          // Inline Owner Edit
          const editBtn = itemEl.querySelector('.edit-comment-btn');
          if (editBtn) {
            editBtn.onclick = () => {
              openInlineCommentEditor(itemEl, c, doc.id, () => fetchAndRenderComments(commentPage));
            };
          }

          // Owner Delete with modal confirmation
          const delBtn = itemEl.querySelector('.delete-comment-btn');
          if (delBtn) {
            delBtn.onclick = async () => {
              const confirmed = await confirmAction({
                title: 'Delete Research Note',
                message: 'Are you sure you want to delete this note? This action cannot be undone.',
                confirmLabel: 'Delete Note',
                destructive: true,
              });
              if (confirmed) {
                try {
                  await api(`/comments/${c.id}`, { method: 'DELETE' });
                  notify('Note deleted.', { kind: 'success' });
                  await fetchAndRenderComments(commentPage);
                } catch (delErr) {
                  notify(delErr.message || 'Failed to delete comment', { kind: 'error' });
                }
              }
            };
          }

          // Report Comment Modal
          const reportBtn = itemEl.querySelector('.report-comment-btn');
          if (reportBtn) {
            reportBtn.onclick = () => {
              const currentSess = getSession();
              if (!currentSess.user) {
                notify('Please sign in to report notes.', { kind: 'info' });
                navigate(`/login?next=/documents/${doc.id}`);
                return;
              }
              openReportModal(contentEl.querySelector('#reportModalContainer'), c.id);
            };
          }

          feed.appendChild(itemEl);
        });

        // Render Comments Pagination if multiple pages exist
        if (paginationContainer) {
          const totalPages = data.total_pages || Math.ceil(data.total / commentPageSize);
          if (totalPages > 1) {
            paginationContainer.innerHTML = `
              <div class="pagination" aria-label="Comments Pagination">
                <button class="page-btn" id="prevCommentsBtn" ${commentPage <= 1 ? 'disabled' : ''}>← Previous</button>
                <span class="page-info">Page ${commentPage} of ${totalPages} (${data.total} notes)</span>
                <button class="page-btn" id="nextCommentsBtn" ${commentPage >= totalPages ? 'disabled' : ''}>Next →</button>
              </div>
            `;
            const prevBtn = paginationContainer.querySelector('#prevCommentsBtn');
            const nextBtn = paginationContainer.querySelector('#nextCommentsBtn');
            if (prevBtn) prevBtn.onclick = () => fetchAndRenderComments(commentPage - 1);
            if (nextBtn) nextBtn.onclick = () => fetchAndRenderComments(commentPage + 1);
          } else {
            paginationContainer.innerHTML = '';
          }
        }

      } catch (commentsErr) {
        if (commentsErr.name === 'AbortError') return;
        feed.innerHTML = `
          <div class="notice notice-error" style="margin: 1rem 0;">
            <p>Failed to load discussions: ${escapeText(commentsErr.message || 'Network error')}</p>
            <button class="btn btn-secondary btn-sm" id="retryCommentsBtn">Retry</button>
          </div>
        `;
        const retryBtn = feed.querySelector('#retryCommentsBtn');
        if (retryBtn) retryBtn.onclick = () => fetchAndRenderComments(commentPage);
      }
    }

    // Load initial comments page
    await fetchAndRenderComments(1);

    // Comment submission handler
    const submitBtn = contentEl.querySelector('#submitCommentBtn');
    const commentInput = contentEl.querySelector('#commentBodyInput');
    const composeError = contentEl.querySelector('#composeError');

    if (submitBtn && commentInput) {
      submitBtn.onclick = async () => {
        const bodyText = commentInput.value.trim();
        if (!bodyText) {
          if (composeError) {
            composeError.textContent = 'Please enter note content before posting.';
            composeError.style.display = 'inline-block';
          }
          return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Posting...';
        if (composeError) composeError.style.display = 'none';

        try {
          await api(`/documents/${doc.id}/comments`, {
            method: 'POST',
            body: { body: bodyText },
          });
          commentInput.value = '';
          notify('Research note posted successfully.', { kind: 'success' });
          await fetchAndRenderComments(1);
        } catch (postErr) {
          if (composeError) {
            composeError.style.display = 'inline-block';
            composeError.textContent = postErr.message || 'Failed to submit comment.';
          } else {
            notify(postErr.message || 'Failed to submit comment.', { kind: 'error' });
          }
        } finally {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Post Note';
        }
      };
    }

  } catch (err) {
    if (err.name === 'AbortError') return;
    renderError(container, err, {
      onRetry: () => renderDocumentDetail(container, routeContext),
    });
  }

  // Cleanup handler called when route changes
  return function routeCleanup() {
    if (cleanupMentions) {
      cleanupMentions();
    }
    // Reset document title
    document.title = 'Folio — Knowledge & Research Library';
    // Restore or reset meta description
    if (metaDescEl) {
      if (prevMetaDesc) {
        metaDescEl.setAttribute('content', prevMetaDesc);
      } else {
        metaDescEl.remove();
      }
    }
  };
}

// Inline comment editing component with accessible @mentions
function openInlineCommentEditor(commentCardEl, comment, docId, onRefresh) {
  const bodyContainer = commentCardEl.querySelector('.comment-body-container');
  const actionsContainer = commentCardEl.querySelector('.comment-actions');
  if (!bodyContainer) return;

  const originalHtml = bodyContainer.innerHTML;
  if (actionsContainer) actionsContainer.style.display = 'none';

  bodyContainer.innerHTML = `
    <div class="inline-comment-editor">
      <div class="edit-textarea-wrapper" style="position: relative;">
        <textarea class="textarea edit-body-textarea" rows="3">${escapeText(comment.body)}</textarea>
      </div>
      <div class="edit-error-text notice notice-error" style="display: none; margin-top: 0.5rem; font-size: 0.85rem;"></div>
      <div class="inline-edit-actions">
        <button class="btn btn-secondary btn-sm cancel-edit-btn">Cancel</button>
        <button class="btn btn-primary btn-sm save-edit-btn">Save Changes</button>
      </div>
    </div>
  `;

  const textarea = bodyContainer.querySelector('.edit-body-textarea');
  const wrapper = bodyContainer.querySelector('.edit-textarea-wrapper');
  const cancelBtn = bodyContainer.querySelector('.cancel-edit-btn');
  const saveBtn = bodyContainer.querySelector('.save-edit-btn');
  const errorEl = bodyContainer.querySelector('.edit-error-text');

  const cleanupEditorMentions = attachMentionsAutocomplete(textarea, wrapper);
  textarea.focus();

  cancelBtn.onclick = () => {
    cleanupEditorMentions();
    bodyContainer.innerHTML = originalHtml;
    if (actionsContainer) actionsContainer.style.display = 'flex';
  };

  saveBtn.onclick = async () => {
    const updatedText = textarea.value.trim();
    if (!updatedText) {
      errorEl.textContent = 'Note body cannot be empty.';
      errorEl.style.display = 'block';
      return;
    }

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    errorEl.style.display = 'none';

    try {
      await api(`/comments/${comment.id}`, {
        method: 'PATCH',
        body: { body: updatedText },
      });
      cleanupEditorMentions();
      notify('Note updated successfully.', { kind: 'success' });
      onRefresh();
    } catch (err) {
      errorEl.textContent = err.message || 'Failed to update note.';
      errorEl.style.display = 'block';
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Changes';
    }
  };
}

// Accessible Modal Dialog for reporting comments
function openReportModal(containerEl, commentId) {
  if (!containerEl) return;

  containerEl.innerHTML = `
    <div class="dialog-backdrop" id="reportDialogBackdrop">
      <div class="dialog report-dialog" role="dialog" aria-modal="true" aria-labelledby="reportModalTitle">
        <h3 id="reportModalTitle" style="margin-top: 0;">Report Research Note</h3>
        <p style="color: var(--color-muted); font-size: 0.9rem; margin-bottom: 1rem;">
          Help maintain scientific integrity by identifying research notes that violate publication or community guidelines.
        </p>

        <form id="reportCommentForm">
          <div class="field">
            <label class="label" for="reportReasonSelect">Reason for report</label>
            <select id="reportReasonSelect" class="select" required>
              <option value="spam">Spam or Unsolicited Promotion</option>
              <option value="abuse">Abusive, Harassing, or Defamatory</option>
              <option value="other">Other Guideline Violation</option>
            </select>
          </div>

          <div class="field">
            <label class="label" for="reportDetailsInput">Additional Details (optional)</label>
            <textarea id="reportDetailsInput" class="textarea" rows="3" placeholder="Explain the issue for moderators..."></textarea>
          </div>

          <div id="reportErrorBox" class="notice notice-error" style="display: none; margin-bottom: 1rem;"></div>

          <div class="dialog-actions">
            <button type="button" class="btn btn-secondary" id="cancelReportBtn">Cancel</button>
            <button type="submit" class="btn btn-danger" id="submitReportBtn">Submit Report</button>
          </div>
        </form>
      </div>
    </div>
  `;

  const backdrop = containerEl.querySelector('#reportDialogBackdrop');
  const form = containerEl.querySelector('#reportCommentForm');
  const cancelBtn = containerEl.querySelector('#cancelReportBtn');
  const submitBtn = containerEl.querySelector('#submitReportBtn');
  const reasonSelect = containerEl.querySelector('#reportReasonSelect');
  const detailsInput = containerEl.querySelector('#reportDetailsInput');
  const errorBox = containerEl.querySelector('#reportErrorBox');

  function closeModal() {
    containerEl.innerHTML = '';
  }

  cancelBtn.onclick = closeModal;
  backdrop.onclick = (e) => {
    if (e.target === backdrop) closeModal();
  };

  form.onsubmit = async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';
    errorBox.style.display = 'none';

    try {
      await api(`/comments/${commentId}/reports`, {
        method: 'POST',
        body: {
          reason: reasonSelect.value,
          details: detailsInput.value.trim() || undefined,
        },
      });
      closeModal();
      notify('Report submitted for moderator review.', { kind: 'success' });
    } catch (err) {
      if (err.status === 409) {
        errorBox.textContent = 'You have already submitted an open report for this note.';
      } else {
        errorBox.textContent = err.message || 'Failed to submit report.';
      }
      errorBox.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit Report';
    }
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
