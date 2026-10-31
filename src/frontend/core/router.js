// src/frontend/core/router.js
// Hash router with parameter matching, query parsing, leave guard protection, and AbortController lifecycle

let currentAbortController = null;
let currentCleanup = null;
let registeredRoutes = [];
let routeContainer = null;
let notFoundHandler = null;

let currentLeaveGuard = null;
let lastActiveHash = (typeof window !== 'undefined' && window.location.hash) ? window.location.hash : '#/library';
let isRevertingHash = false;

export function registerLeaveGuard(guardFn) {
  currentLeaveGuard = guardFn;
}

export function clearLeaveGuard() {
  currentLeaveGuard = null;
}

export async function navigate(path) {
  const cleanPath = path.startsWith('#') ? path.slice(1) : path;
  const targetHash = cleanPath.startsWith('/') ? `#${cleanPath}` : `#/${cleanPath}`;
  if (window.location.hash === targetHash) return;

  if (currentLeaveGuard) {
    const canLeave = await currentLeaveGuard();
    if (!canLeave) return;
    currentLeaveGuard = null;
  }
  window.location.hash = targetHash;
}

export function registerRoutes(routes) {
  registeredRoutes = routes;
}

export function setNotFoundHandler(handler) {
  notFoundHandler = handler;
}

function parseHash(hashString) {
  const raw = hashString.startsWith('#') ? hashString.slice(1) : hashString;
  const clean = raw.trim() || '/library';
  const qIndex = clean.indexOf('?');
  const path = qIndex >= 0 ? clean.slice(0, qIndex) : clean;
  const queryString = qIndex >= 0 ? clean.slice(qIndex + 1) : '';
  return {
    path: path.startsWith('/') ? path : `/${path}`,
    query: new URLSearchParams(queryString),
  };
}

function matchRoute(routePath, currentPath) {
  const routeSegments = routePath.split('/').filter(Boolean);
  const currentSegments = currentPath.split('/').filter(Boolean);

  if (routeSegments.length !== currentSegments.length) {
    return null;
  }

  const params = {};
  for (let i = 0; i < routeSegments.length; i++) {
    const rSeg = routeSegments[i];
    const cSeg = currentSegments[i];
    if (rSeg.startsWith(':')) {
      const paramName = rSeg.slice(1);
      params[paramName] = decodeURIComponent(cSeg);
    } else if (rSeg !== cSeg) {
      return null;
    }
  }

  return params;
}

async function handleRouteChange() {
  if (!routeContainer) return;

  if (isRevertingHash) {
    isRevertingHash = false;
    return;
  }

  const currentRawHash = window.location.hash || '#/library';
  if (currentLeaveGuard && currentRawHash !== lastActiveHash) {
    const canLeave = await currentLeaveGuard();
    if (!canLeave) {
      isRevertingHash = true;
      window.location.hash = lastActiveHash;
      return;
    }
    currentLeaveGuard = null;
  }

  lastActiveHash = currentRawHash;

  // 1. Abort any ongoing operations from previous route
  if (currentAbortController) {
    currentAbortController.abort();
  }
  currentAbortController = new AbortController();
  const signal = currentAbortController.signal;

  // 2. Call previous page's cleanup function if provided
  if (typeof currentCleanup === 'function') {
    try {
      currentCleanup();
    } catch (e) {
      console.error('Route cleanup error:', e);
    }
    currentCleanup = null;
  }

  const { path, query } = parseHash(window.location.hash);

  // 3. Match route
  let matchedRoute = null;
  let params = {};

  for (const r of registeredRoutes) {
    const match = matchRoute(r.path, path);
    if (match !== null) {
      matchedRoute = r;
      params = match;
      break;
    }
  }

  routeContainer.innerHTML = '';

  if (matchedRoute) {
    try {
      const context = { path, params, query, signal };
      const cleanup = await matchedRoute.render(routeContainer, context);
      if (typeof cleanup === 'function') {
        currentCleanup = cleanup;
      }
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.error('Error rendering route:', err);
      routeContainer.innerHTML = `
        <div class="notice notice-error" style="margin: 2rem auto; max-width: 600px;">
          <h3>Failed to load page</h3>
          <p>${escapeHtml(err.message || 'An unexpected error occurred.')}</p>
          <button class="btn btn-secondary" onclick="window.location.reload()">Reload</button>
        </div>
      `;
    }
  } else if (notFoundHandler) {
    notFoundHandler(routeContainer, { path, query, signal });
  } else {
    routeContainer.innerHTML = `
      <div class="empty-state" style="padding: 4rem 1rem; text-align: center;">
        <h2>404 — Page Not Found</h2>
        <p>The requested page <code>${escapeHtml(path)}</code> does not exist.</p>
        <button class="btn btn-primary" onclick="window.location.hash='#/library'">Return to Library</button>
      </div>
    `;
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

export function initRouter(container, routes) {
  routeContainer = container;
  registeredRoutes = routes;

  window.addEventListener('hashchange', handleRouteChange);
  // Default to #/library if empty hash
  if (!window.location.hash || window.location.hash === '#') {
    window.location.hash = '#/library';
  } else {
    handleRouteChange();
  }
}
