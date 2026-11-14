// src/frontend/public/detail_view.js
// Document Reading View, Provenance, View & Search Click Analytics, Like, and Discussions

import { api } from '../core/api.js';
import { getSession } from '../core/session.js';
import { notify, confirmAction, renderError } from '../core/ui.js';
import { navigate } from '../core/router.js';
import { attachMentionsAutocomplete } from './mentions.js';
import { renderMathInContainer } from '../core/math.js';
import {
  prefetchedDocCache,
  clickedDocHint,
  claimPrefetchedDocument,
} from './library_view.js';
import {
  prefersReducedMotion,
  setSharedTitle,
  safeScrollIntoView,
} from '../core/motion.js';

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
  if ((trimmed.startsWith('/') || trimmed.startsWith('./')) && !/^[a-z0-9+.-]+:/i.test(trimmed)) {
    return trimmed;
  }
  return null;
}

function extractHeadingLabel(headingEl) {
  if (!headingEl) return '';
  const clone = headingEl.cloneNode(true);
  // Defense-in-depth: collapse any pre-rendered KaTeX DOM into a single TeX/visual representation
  clone.querySelectorAll('.katex').forEach((katexEl) => {
    const texAnn = katexEl.querySelector('annotation[encoding="application/x-tex"]');
    const katexHtml = katexEl.querySelector('.katex-html');
    const replacementText = texAnn ? texAnn.textContent : (katexHtml ? katexHtml.textContent : '');
    katexEl.replaceWith(document.createTextNode(replacementText || ''));
  });
  // Unwrap sanitizer math delimiters so TOC labels and slugs remain clean without TeX delimiter noise
  clone.querySelectorAll('.math-inline, .math-display').forEach((mathEl) => {
    let text = (mathEl.textContent || '').trim();
    if (mathEl.classList.contains('math-inline') && text.startsWith('\\(') && text.endsWith('\\)') && text.length >= 4) {
      text = text.slice(2, -2).trim();
    } else if (mathEl.classList.contains('math-display')) {
      if ((text.startsWith('$$') && text.endsWith('$$') && text.length >= 4) ||
          (text.startsWith('\\[') && text.endsWith('\\]') && text.length >= 4)) {
        text = text.slice(2, -2).trim();
      }
    }
    mathEl.replaceWith(document.createTextNode(text));
  });
  return (clone.textContent || '').replace(/\s+/g, ' ').trim();
}

export async function renderDocumentDetail(container, routeContext) {
  const { params, query, signal, navId, isStale } = routeContext;
  const docId = params.id;
  const searchEventId = query.get('search_event_id');
  const session = getSession();

  let cleanupMentions = null;
  let cleanupReadingProgress = null;
  let cleanedUp = false;
  let viewLogged = false;
  let prevMetaDesc = '';
  let metaDescEl = document.querySelector('meta[name="description"]');
  if (metaDescEl) {
    prevMetaDesc = metaDescEl.getAttribute('content') || '';
  }

  function detailCleanup() {
    if (cleanedUp) return;
    cleanedUp = true;
    if (cleanupReadingProgress) {
      cleanupReadingProgress();
      cleanupReadingProgress = null;
    }
    if (cleanupMentions) {
      cleanupMentions();
      cleanupMentions = null;
    }
    if (metaDescEl && prevMetaDesc) {
      metaDescEl.setAttribute('content', prevMetaDesc);
    }
  }

  if (typeof routeContext.registerCleanup === 'function') {
    routeContext.registerCleanup(detailCleanup);
  }

  // Create isolated root element for this render to prevent stale async renders from mutating newer routes
  const detailPageRoot = document.createElement('div');
  detailPageRoot.className = 'public-page detail-page-container';
  detailPageRoot.style.paddingTop = '1rem';
  detailPageRoot.setAttribute('data-doc-id', docId);

  // Synchronous shell mount (Phase B & C):
  // Check if we have a title hint from a clicked card link for shared-element title transition
  const hasMatchingHint = Boolean(
    clickedDocHint &&
    clickedDocHint.id === docId &&
    (Date.now() - clickedDocHint.timestamp < 10000)
  );
  const initialTitle = hasMatchingHint ? clickedDocHint.title : '';

  function renderLoadingShell() {
    detailPageRoot.innerHTML = `
      <a href="#/library" class="back-link" id="detailBackLink">← Back to Library Catalog</a>
      ${initialTitle ? `
        <div class="detail-header-wrapper" id="detailHeaderWrapper">
          <h1 class="detail-title" id="detailInitialTitle" style="${hasMatchingHint && !prefersReducedMotion() ? 'view-transition-name: folio-doc-title;' : ''}">${escapeText(initialTitle)}</h1>
        </div>
      ` : ''}
      <div id="detailLoading" style="text-align: center; padding: 4rem;">
        <span class="spinner" aria-label="Loading document..."></span>
        <p style="color: var(--color-muted); margin-top: 1rem;">Loading document...</p>
      </div>
      <div id="detailContent" style="display: none;"></div>
    `;
  }

  renderLoadingShell();
  container.appendChild(detailPageRoot);

  if (hasMatchingHint && !prefersReducedMotion()) {
    const initialTitleEl = detailPageRoot.querySelector('#detailInitialTitle');
    if (initialTitleEl) {
      setSharedTitle(initialTitleEl, docId);
    }
  }

  // Background async data fetching (Phase B & Finding C: outside of View Transitions callback)
  async function loadDetailContent() {
    try {
      const claimedPromise = claimPrefetchedDocument(docId, signal);
      const docPromise = claimedPromise || api(`/documents/${docId}`, { signal });
      docPromise.catch(() => {});

      const [doc, publicSettings] = await Promise.all([
        docPromise,
        api('/settings/public', { signal }).catch(() => ({ comments_enabled: true })),
      ]);

      // STRICT OWNERSHIP VERIFICATION (Phase A & Finding C):
      // If navigation was aborted, superseded by a newer navigation, or container detached, halt immediately!
      if (cleanedUp || signal.aborted || (isStale && isStale()) || !detailPageRoot.isConnected) {
        return;
      }
      if (!doc || typeof doc !== 'object' || !doc.id) {
        throw new Error('Invalid document response');
      }

      const contentEl = detailPageRoot.querySelector('#detailContent');
      const loadingEl = detailPageRoot.querySelector('#detailLoading');
      const initialHeader = detailPageRoot.querySelector('#detailHeaderWrapper');
      const initialTitleEl = detailPageRoot.querySelector('#detailInitialTitle');
      const hadActiveSharedTitle = Boolean(
        initialTitleEl && initialTitleEl.style.viewTransitionName === 'folio-doc-title'
      );
      if (initialHeader) initialHeader.remove();
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

      // 1. Record View Event (Strictly once per completed navigation)
      if (!viewLogged) {
        viewLogged = true;
        const navigationId = genUuid();
        api(`/documents/${doc.id}/views`, {
          method: 'POST',
          body: { navigation_id: navigationId },
        }).catch((err) => console.warn('View logging error (non-fatal):', err));
      }

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
                <svg class="heart-icon" width="15" height="15" viewBox="0 0 24 24" fill="${doc.liked_by_me ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
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
              <img src="${escapeAttr(safeCoverImageUrl)}" alt="${escapeAttr(doc.cover_image_alt || doc.title)}" class="detail-cover-image" loading="lazy" decoding="async" />
              ${doc.cover_image_alt ? `<div class="detail-cover-caption">${escapeText(doc.cover_image_alt)}</div>` : ''}
            </div>
          ` : ''}

          <div class="detail-tags-wrapper">
            ${tagsHtml}
          </div>
        </header>

        <!-- Sanitized Rendered Content Body -->
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

        <!-- Status Warnings -->
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

    // Setup shared title reference for active transition and back navigation
    const detailTitleEl = contentEl.querySelector('.detail-title');
    if (detailTitleEl && hadActiveSharedTitle && !prefersReducedMotion()) {
      setSharedTitle(detailTitleEl, doc.id);
    }

    // Handle cover image load failure cleanly via event listener (no inline onerror, no retry loop)
    const coverImgEl = contentEl.querySelector('.detail-cover-image');
    if (coverImgEl) {
      coverImgEl.addEventListener('error', () => {
        const coverContainer = coverImgEl.closest('.detail-cover-container');
        if (coverContainer) {
          coverContainer.classList.add('detail-cover-broken');
        }
        coverImgEl.remove();
      }, { once: true });
    }

    // Generate Table of Contents from clean source headings BEFORE rendering KaTeX math (R3-07)
    const readingColumn = contentEl.querySelector('.document-reading-column');
    if (readingColumn) {
      // Enhance inline Markdown images: lazy loading, async decoding, alt fallback, caption pairing, and error listener
      readingColumn.querySelectorAll('img').forEach((imgEl) => {
        if (!imgEl.getAttribute('loading')) {
          imgEl.setAttribute('loading', 'lazy');
        }
        if (!imgEl.getAttribute('decoding')) {
          imgEl.setAttribute('decoding', 'async');
        }
        const altVal = (imgEl.getAttribute('alt') || '').trim();
        if (!altVal) {
          imgEl.setAttribute('alt', doc.title || 'Article illustration');
        }

        const parentP = imgEl.parentElement;
        if (parentP && parentP.tagName === 'P' && parentP.children.length === 1 && (parentP.textContent || '').trim() === '') {
          parentP.classList.add('markdown-figure-paragraph');
          const nextEl = parentP.nextElementSibling;
          if (nextEl && nextEl.tagName === 'P' && nextEl.children.length === 1 && nextEl.firstElementChild && nextEl.firstElementChild.tagName === 'EM') {
            nextEl.classList.add('markdown-figure-caption');
          }
        }

        imgEl.addEventListener('error', () => {
          if (imgEl.dataset.fallbackApplied === '1') return;
          imgEl.dataset.fallbackApplied = '1';
          const fallbackAlt = (imgEl.getAttribute('alt') || '').trim();
          const containerP = imgEl.closest('p');
          imgEl.classList.add('markdown-img-broken');
          if (containerP) {
            containerP.classList.add('markdown-figure-broken');
            const nextCaption = containerP.nextElementSibling;
            const hasAdjacentCaption = Boolean(nextCaption && nextCaption.classList.contains('markdown-figure-caption'));
            if (fallbackAlt && !hasAdjacentCaption) {
              const note = document.createElement('span');
              note.className = 'markdown-img-fallback-note';
              note.textContent = `[Illustration unavailable: ${fallbackAlt}]`;
              containerP.appendChild(note);
            }
          }
          imgEl.remove();
        }, { once: true });
      });
      const headings = readingColumn.querySelectorAll('h1, h2, h3');
      if (headings.length >= 2) {
        const tocItems = [];
        const usedSlugs = new Set();

        headings.forEach((h, idx) => {
          const cleanLabel = extractHeadingLabel(h);
          let slug = cleanLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
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
              <a href="#${finalSlug}">${escapeText(cleanLabel || `Section ${idx + 1}`)}</a>
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

        // Smooth scroll and flash arrival highlight
        tocBox.querySelectorAll('a').forEach((link) => {
          link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('href').slice(1);
            const targetEl = document.getElementById(targetId);
            if (targetEl) {
              safeScrollIntoView(targetEl, { behavior: 'smooth', block: 'start' });
              targetEl.setAttribute('tabindex', '-1');
              targetEl.focus({ preventScroll: true });

              let flashed = false;
              let fallbackTimer = null;
              let onScrollEnd = null;
              const triggerFlash = () => {
                if (flashed) return;
                flashed = true;
                if (fallbackTimer) {
                  clearTimeout(fallbackTimer);
                  fallbackTimer = null;
                }
                if (onScrollEnd) {
                  window.removeEventListener('scrollend', onScrollEnd);
                }
                targetEl.classList.remove('heading-target-flash');
                void targetEl.offsetWidth;
                targetEl.classList.add('heading-target-flash');
                setTimeout(() => {
                  targetEl.classList.remove('heading-target-flash');
                }, 800);
              };

              // Trigger highlight arrival flash when arriving at target heading (with fallback if scroll delta is 0px)
              if ('onscrollend' in window) {
                onScrollEnd = () => triggerFlash();
                window.addEventListener('scrollend', onScrollEnd, { once: true });
                fallbackTimer = setTimeout(triggerFlash, 180);
              } else {
                const observer = new IntersectionObserver((entries) => {
                  if (entries[0] && entries[0].isIntersecting) {
                    observer.disconnect();
                    triggerFlash();
                  }
                }, { threshold: 0.3 });
                observer.observe(targetEl);
                fallbackTimer = setTimeout(() => {
                  observer.disconnect();
                  triggerFlash();
                }, 180);
              }
            }
          });
        });
      }

      // Render self-hosted KaTeX math in article body (after TOC label/slug extraction)
      renderMathInContainer(readingColumn);

      // Reading Progress Bar at top of viewport
      let progressBar = document.getElementById('readingProgressBar');
      if (!progressBar) {
        progressBar = document.createElement('div');
        progressBar.id = 'readingProgressBar';
        progressBar.className = 'reading-progress-bar';
        progressBar.setAttribute('aria-hidden', 'true');
        document.body.appendChild(progressBar);
      }

      let progressRaf = null;
      function updateReadingProgress() {
        if (!readingColumn || !progressBar) return;
        const rect = readingColumn.getBoundingClientRect();
        const columnTop = window.scrollY + rect.top;
        const columnHeight = rect.height;
        const viewportHeight = window.innerHeight;
        const headerOffset = 68;

        if (columnHeight <= viewportHeight) {
          progressBar.style.transform = 'scaleX(0)';
          return;
        }

        const scrollableDist = columnHeight - viewportHeight + headerOffset;
        const currentScroll = window.scrollY + headerOffset - columnTop;
        const progress = Math.min(1, Math.max(0, currentScroll / scrollableDist));
        progressBar.style.transform = `scaleX(${progress})`;
      }

      const onProgressScroll = () => {
        if (progressRaf) cancelAnimationFrame(progressRaf);
        progressRaf = requestAnimationFrame(updateReadingProgress);
      };

      window.addEventListener('scroll', onProgressScroll, { passive: true });
      window.addEventListener('resize', onProgressScroll, { passive: true });
      let readingRo = null;
      if (typeof ResizeObserver !== 'undefined') {
        readingRo = new ResizeObserver(onProgressScroll);
        readingRo.observe(readingColumn);
      }
      updateReadingProgress();

      cleanupReadingProgress = () => {
        if (progressRaf) cancelAnimationFrame(progressRaf);
        window.removeEventListener('scroll', onProgressScroll);
        window.removeEventListener('resize', onProgressScroll);
        if (readingRo) readingRo.disconnect();
        if (progressBar && progressBar.parentNode) {
          progressBar.parentNode.removeChild(progressBar);
        }
      };
    }

    // Hook up Back to Library link
    const backLink = detailPageRoot.querySelector('#detailBackLink');
    if (backLink) {
      backLink.onclick = (e) => {
        if (detailTitleEl) {
          setSharedTitle(detailTitleEl, doc.id);
        }
        try {
          const state = window.history.state || {};
          window.history.replaceState({ ...state, folioDocId: doc.id }, '');
          sessionStorage.setItem('folio_last_doc_id', doc.id);
        } catch (_) {}

        e.preventDefault();
        const lastLibRoute = sessionStorage.getItem('folio_last_library_route') || '#/library';
        const targetPath = lastLibRoute.startsWith('#') ? lastLibRoute.slice(1) : lastLibRoute;
        navigate(targetPath.startsWith('/') ? targetPath : `/${targetPath}`);
      };
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

          const heartSvg = likeBtn.querySelector('.heart-icon');
          if (heartSvg) {
            heartSvg.setAttribute('fill', isLiked ? 'currentColor' : 'none');
          }
          likeCountText.textContent = likesCount;

          if (isLiked && !prefersReducedMotion()) {
            likeBtn.classList.remove('like-pop');
            void likeBtn.offsetWidth;
            likeBtn.classList.add('like-pop');
            setTimeout(() => likeBtn.classList.remove('like-pop'), 250);
          }

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

    // Fetch and render initial comments asynchronously (does not block reading view)
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

        if (signal.aborted || !detailPageRoot.isConnected) return;

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
                ${!isOwner ? `<button class="btn btn-secondary btn-sm report-comment-btn" title="Report this note to administrators">Report</button>` : ''}
              </div>
            </div>
            <div class="comment-body-container">
              <div class="comment-body-text">${escapeText(c.body)}</div>
            </div>
            ${mentionsHtml ? `<div class="comment-mentions-bar">Mentioned: ${mentionsHtml}</div>` : ''}
          `;

          const editBtn = itemEl.querySelector('.edit-comment-btn');
          if (editBtn) {
            editBtn.onclick = () => {
              openInlineCommentEditor(itemEl, c, doc.id, () => fetchAndRenderComments(commentPage));
            };
          }

          const delBtn = itemEl.querySelector('.delete-comment-btn');
          if (delBtn) {
            delBtn.onclick = async () => {
              const ok = await confirmAction({
                title: 'Delete Research Note',
                message: 'Are you sure you want to delete this research note? This action cannot be undone.',
                confirmLabel: 'Delete Note',
                destructive: true,
              });
              if (!ok) return;
              try {
                await api(`/comments/${c.id}`, { method: 'DELETE' });
                notify('Comment removed.', { kind: 'success' });
                fetchAndRenderComments(commentPage);
              } catch (err) {
                notify(err.message || 'Failed to delete comment', { kind: 'error' });
              }
            };
          }

          const repBtn = itemEl.querySelector('.report-comment-btn');
          if (repBtn) {
            repBtn.onclick = () => {
              const modalHost = contentEl.querySelector('#reportModalContainer');
              if (modalHost) {
                openReportDialog(modalHost, c.id);
              }
            };
          }

          feed.appendChild(itemEl);
        });

        // Comments pagination
        if (paginationContainer) {
          const totalPages = Math.ceil(data.total / commentPageSize);
          if (totalPages > 1) {
            paginationContainer.innerHTML = `
              <div class="pagination">
                <button class="btn btn-secondary btn-sm prev-page" ${commentPage <= 1 ? 'disabled' : ''}>← Previous</button>
                <span class="pagination-info">Page ${commentPage} of ${totalPages}</span>
                <button class="btn btn-secondary btn-sm next-page" ${commentPage >= totalPages ? 'disabled' : ''}>Next →</button>
              </div>
            `;
            const prev = paginationContainer.querySelector('.prev-page');
            const next = paginationContainer.querySelector('.next-page');
            if (prev) prev.onclick = () => fetchAndRenderComments(commentPage - 1);
            if (next) next.onclick = () => fetchAndRenderComments(commentPage + 1);
          } else {
            paginationContainer.innerHTML = '';
          }
        }
      } catch (err) {
        if (signal.aborted || !detailPageRoot.isConnected) return;
        feed.innerHTML = `
          <div class="notice notice-error">
            Failed to load peer notes: ${escapeText(err.message)}
          </div>
        `;
      }
    }

    // Submit new comment note
    const submitCommentBtn = contentEl.querySelector('#submitCommentBtn');
    const commentBodyInput = contentEl.querySelector('#commentBodyInput');
    const composeError = contentEl.querySelector('#composeError');

    if (submitCommentBtn && commentBodyInput) {
      submitCommentBtn.onclick = async () => {
        const text = commentBodyInput.value.trim();
        if (!text) {
          if (composeError) {
            composeError.textContent = 'Note content cannot be empty.';
            composeError.style.display = 'inline-block';
          }
          return;
        }

        submitCommentBtn.disabled = true;
        if (composeError) composeError.style.display = 'none';

        try {
          await api(`/documents/${doc.id}/comments`, {
            method: 'POST',
            body: { body: text },
          });
          commentBodyInput.value = '';
          notify('Note published.', { kind: 'success' });
          fetchAndRenderComments(1);
        } catch (err) {
          if (composeError) {
            composeError.textContent = err.message || 'Failed to publish comment.';
            composeError.style.display = 'inline-block';
          }
        } finally {
          submitCommentBtn.disabled = false;
        }
      };
    }

    fetchAndRenderComments(1);

    } catch (err) {
      if (cleanedUp || signal.aborted || (isStale && isStale()) || !detailPageRoot.isConnected) return;
      if (err && err.name === 'AbortError') return;
      console.error('Document detail fetch error:', err);
      detailPageRoot.innerHTML = `
        <a href="#/library" class="back-link">← Back to Library Catalog</a>
        <div class="notice notice-error" style="margin: 2rem auto; max-width: 600px;">
          <h3>Could not load research document</h3>
          <p>${escapeText(err.message || 'The requested document could not be retrieved.')}</p>
          <button type="button" class="btn btn-secondary" id="detailRetryBtn">Retry</button>
        </div>
      `;
      const retryBtn = detailPageRoot.querySelector('#detailRetryBtn');
      if (retryBtn) {
        retryBtn.onclick = () => {
          if (cleanedUp || signal.aborted || (isStale && isStale()) || !detailPageRoot.isConnected) return;
          renderLoadingShell();
          loadDetailContent();
        };
      }
    }
  }

  await loadDetailContent();

  // Cleanup handler called when navigating AWAY from this document detail
  return detailCleanup;
}

function openInlineCommentEditor(itemEl, comment, docId, onSaved) {
  const bodyContainer = itemEl.querySelector('.comment-body-container');
  const actionsBar = itemEl.querySelector('.comment-actions');
  if (!bodyContainer) return;

  const originalHtml = bodyContainer.innerHTML;
  if (actionsBar) actionsBar.style.display = 'none';

  bodyContainer.innerHTML = `
    <div class="inline-comment-edit-box inline-comment-editor">
      <div class="textarea-mentions-wrapper" style="position: relative;">
        <textarea class="textarea edit-textarea edit-body-textarea" rows="3">${escapeText(comment.body)}</textarea>
      </div>
      <div class="inline-edit-actions" style="margin-top: 0.5rem; display: flex; gap: 0.5rem;">
        <button class="btn btn-primary btn-sm save-edit-btn">Save</button>
        <button class="btn btn-secondary btn-sm cancel-edit-btn">Cancel</button>
        <span class="inline-edit-error" style="color: var(--color-danger); font-size: 0.85rem; display: none;"></span>
      </div>
    </div>
  `;

  const editInput = bodyContainer.querySelector('.edit-textarea');
  const mentionsWrapper = bodyContainer.querySelector('.textarea-mentions-wrapper');
  const saveBtn = bodyContainer.querySelector('.save-edit-btn');
  const cancelBtn = bodyContainer.querySelector('.cancel-edit-btn');
  const errorEl = bodyContainer.querySelector('.inline-edit-error');

  const mentionsCleanup = attachMentionsAutocomplete(editInput, mentionsWrapper);

  cancelBtn.onclick = () => {
    if (mentionsCleanup) mentionsCleanup();
    bodyContainer.innerHTML = originalHtml;
    if (actionsBar) actionsBar.style.display = 'flex';
  };

  saveBtn.onclick = async () => {
    const newText = editInput.value.trim();
    if (!newText) {
      errorEl.textContent = 'Note cannot be blank.';
      errorEl.style.display = 'inline-block';
      return;
    }
    saveBtn.disabled = true;
    errorEl.style.display = 'none';

    try {
      await api(`/comments/${comment.id}`, {
        method: 'PATCH',
        body: { body: newText },
      });
      if (mentionsCleanup) mentionsCleanup();
      notify('Note updated.', { kind: 'success' });
      onSaved();
    } catch (err) {
      errorEl.textContent = err.message || 'Failed to update note.';
      errorEl.style.display = 'inline-block';
      saveBtn.disabled = false;
    }
  };
}

function openReportDialog(containerEl, commentId) {
  containerEl.innerHTML = `
    <div class="dialog-backdrop" id="reportDialogBackdrop">
      <div class="dialog-modal report-dialog" role="dialog" aria-labelledby="reportModalTitle" aria-modal="true">
        <h3 id="reportModalTitle" class="dialog-title">Report Research Note</h3>
        <p style="color: var(--color-muted); font-size: 0.875rem; margin-bottom: 1rem;">
          Notify library administrators about notes containing harassment, spam, copyright infringement, or invalid research citations.
        </p>
        <form id="reportCommentForm">
          <div class="field">
            <label class="label" for="reportReasonSelect">Reason</label>
            <select id="reportReasonSelect" class="select" required>
              <option value="spam">Spam / Promotion</option>
              <option value="harassment">Harassment / Abusive Language</option>
              <option value="misinformation">Inaccurate / Misleading Attribution</option>
              <option value="other">Other Violation</option>
            </select>
          </div>

          <div class="field">
            <label class="label" for="reportDetailsInput">Additional Details (optional)</label>
            <textarea id="reportDetailsInput" class="textarea" rows="3" placeholder="Explain the issue for administrators..."></textarea>
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
      notify('Report submitted for administrator review.', { kind: 'success' });
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
