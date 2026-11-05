// src/frontend/core/router.js
// Hash router with parameter matching, query parsing, leave guard protection,
// distinct mounted-page vs per-request lifecycle ownership, and View Transition safety

import {
  withViewTransition,
  clearSharedTitle,
  cancelActiveViewTransition,
} from './motion.js';

let currentRequestAbortController = null;
let currentMountedInstance = null;
let registeredRoutes = [];
let routeContainer = null;
let notFoundHandler = null;

let currentLeaveGuard = null;
let lastActiveHash = (typeof window !== 'undefined' && window.location.hash) ? window.location.hash : '#/library';
let isRevertingHash = false;
let isCheckingLeaveGuard = false;

// Distinct sequence counters:
// - mountSequence tracks mounted route instances (page-level lifecycle)
// - navigationSequence tracks every route/query transition (request-level lifecycle)
let mountSequence = 0;
let navigationSequence = 0;

export function registerLeaveGuard(guardFn) {
  currentLeaveGuard = guardFn;
}

export function clearLeaveGuard() {
  currentLeaveGuard = null;
}

export function getActiveNavigationTarget() {
  const { path, query } = parseHash(
    typeof window !== 'undefined' ? window.location.hash : '#/library'
  );
  for (const r of registeredRoutes) {
    const match = matchRoute(r.path, path);
    if (match !== null) {
      return { path, params: match, query };
    }
  }
  return { path, params: {}, query };
}

export async function navigate(path) {
  const cleanPath = path.startsWith('#') ? path.slice(1) : path;
  const targetHash = cleanPath.startsWith('/') ? `#${cleanPath}` : `#/${cleanPath}`;
  if (window.location.hash === targetHash) return;

  if (currentLeaveGuard) {
    if (isCheckingLeaveGuard) return;
    isCheckingLeaveGuard = true;
    try {
      const canLeave = await currentLeaveGuard();
      if (!canLeave) return;
      currentLeaveGuard = null;
    } finally {
      isCheckingLeaveGuard = false;
    }
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

function isPublicTransitionRoute(route) {
  if (!route || !route.path) return false;
  // Do not wrap admin, settings, or auth routes in public view transitions
  if (route.path.startsWith('/admin') || route.path === '/login' || route.path === '/register') {
    return false;
  }
  return route.path === '/library' || route.path.startsWith('/documents');
}

async function handleRouteChange() {
  if (!routeContainer) return;

  if (isRevertingHash) {
    isRevertingHash = false;
    return;
  }

  const currentRawHash = window.location.hash || '#/library';
  if (currentLeaveGuard && currentRawHash !== lastActiveHash) {
    if (isCheckingLeaveGuard) return;
    isCheckingLeaveGuard = true;
    try {
      const canLeave = await currentLeaveGuard();
      if (!canLeave) {
        isRevertingHash = true;
        window.location.hash = lastActiveHash;
        return;
      }
      currentLeaveGuard = null;
    } finally {
      isCheckingLeaveGuard = false;
    }
  }

  lastActiveHash = currentRawHash;

  const { path, query } = parseHash(window.location.hash);

  // Match route
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

  const navId = ++navigationSequence;

  // In-place route updating if the same route instance is already mounted and supports update()
  if (
    currentMountedInstance &&
    !currentMountedInstance.unmounted &&
    currentMountedInstance.mounted &&
    currentMountedInstance.route === matchedRoute &&
    typeof matchedRoute.update === 'function'
  ) {
    // Abort only the previous query/request controller, NEVER the mounted page instance!
    if (currentRequestAbortController) {
      currentRequestAbortController.abort();
    }
    currentRequestAbortController = new AbortController();
    const signal = currentRequestAbortController.signal;
    const activeMount = currentMountedInstance;

    activeMount.params = params;
    activeMount.query = query;
    activeMount.latestNavId = navId;

    try {
      const updateContext = {
        path,
        params,
        query,
        signal,
        mountSignal: activeMount.mountSignal,
        mountId: activeMount.mountId,
        navId,
        isUpdate: true,
        isStale: () =>
          signal.aborted ||
          navId !== navigationSequence ||
          activeMount.unmounted ||
          currentMountedInstance !== activeMount,
        isMountActive: () =>
          !activeMount.unmounted && currentMountedInstance === activeMount,
        registerCleanup: (fn) => activeMount.registerCleanup(fn),
      };
      await matchedRoute.update(routeContainer, updateContext);
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      console.error('Error during route update:', err);
    }
    return;
  }

  // Full route change: navigating to a different route or mounting for the first time
  // 1. Abort any ongoing request operations from previous navigation
  if (currentRequestAbortController) {
    currentRequestAbortController.abort();
  }
  currentRequestAbortController = new AbortController();
  const signal = currentRequestAbortController.signal;

  // 2. Teardown previous mounted page instance cleanly and idempotently
  if (currentMountedInstance) {
    const prevMount = currentMountedInstance;
    currentMountedInstance = null;
    prevMount.unmounted = true;
    try {
      prevMount.mountAbortController.abort();
    } catch (_) {}
    prevMount.runCleanup();
  }

  // 3. Create new mounted page instance with its own page-level lifecycle
  const mountId = ++mountSequence;
  const mountAbortController = new AbortController();
  const mountInstance = {
    mountId,
    route: matchedRoute,
    path,
    params,
    query,
    initialNavId: navId,
    latestNavId: navId,
    mounted: false,
    unmounted: false,
    cleanedUp: false,
    cleanupFns: [],
    mountAbortController,
    mountSignal: mountAbortController.signal,
    registerCleanup(fn) {
      if (typeof fn !== 'function') return;
      if (this.unmounted || this.cleanedUp) {
        try {
          fn();
        } catch (_) {}
        return;
      }
      if (!this.cleanupFns.includes(fn)) {
        this.cleanupFns.push(fn);
      }
    },
    runCleanup() {
      if (this.cleanedUp) return;
      this.cleanedUp = true;
      this.unmounted = true;
      const fns = this.cleanupFns.splice(0, this.cleanupFns.length);
      for (const fn of fns) {
        try {
          fn();
        } catch (e) {
          console.error('Route cleanup error:', e);
        }
      }
    },
  };

  currentMountedInstance = mountInstance;

  const isMountActive = () =>
    !mountInstance.unmounted && currentMountedInstance === mountInstance;

  const isNavigationStale = () =>
    signal.aborted ||
    navId !== navigationSequence ||
    !isMountActive();

  const context = {
    path,
    params,
    query,
    signal,
    mountSignal: mountInstance.mountSignal,
    mountId,
    navId,
    isUpdate: false,
    isStale: isNavigationStale,
    isMountActive,
    registerCleanup: (fn) => mountInstance.registerCleanup(fn),
  };

  // 4. Render route with View Transitions support decoupled from async network fetching
  const useTransition = isPublicTransitionRoute(matchedRoute);

  let renderPromise = null;
  let mountCommitted = false;

  const executeMount = () => {
    if (mountCommitted || isNavigationStale()) {
      return;
    }
    mountCommitted = true;
    mountInstance.mounted = true;
    routeContainer.innerHTML = '';

    if (matchedRoute) {
      try {
        renderPromise = Promise.resolve(matchedRoute.render(routeContainer, context));
        renderPromise.catch(() => {});
      } catch (syncErr) {
        renderPromise = Promise.reject(syncErr);
        renderPromise.catch(() => {});
        throw syncErr;
      }
    } else if (notFoundHandler) {
      try {
        renderPromise = Promise.resolve(notFoundHandler(routeContainer, context));
        renderPromise.catch(() => {});
      } catch (syncErr) {
        renderPromise = Promise.reject(syncErr);
        renderPromise.catch(() => {});
        throw syncErr;
      }
    } else {
      routeContainer.innerHTML = `
        <div class="empty-state" style="padding: 4rem 1rem; text-align: center;">
          <h2>404 — Page Not Found</h2>
          <p>The requested page <code>${escapeHtml(path)}</code> does not exist.</p>
          <button class="btn btn-primary" onclick="window.location.hash='#/library'">Return to Library</button>
        </div>
      `;
      renderPromise = Promise.resolve(null);
    }
  };

  try {
    if (useTransition) {
      await withViewTransition(executeMount, {
        fallbackContainer: routeContainer,
        signal,
        isStale: isNavigationStale,
      });
    } else {
      // Cancel any in-flight public transition when switching to non-transition routes (e.g. /login, /admin)
      cancelActiveViewTransition();
      executeMount();
    }
  } catch (transitionErr) {
    if (!isMountActive()) return;
    if (transitionErr && transitionErr.name === 'AbortError') return;
    console.error('Error mounting route:', transitionErr);
    routeContainer.innerHTML = `
      <div class="notice notice-error" style="margin: 2rem auto; max-width: 600px;">
        <h3>Failed to load page</h3>
        <p>${escapeHtml(transitionErr.message || 'An unexpected error occurred.')}</p>
        <button class="btn btn-secondary" onclick="window.location.reload()">Reload</button>
      </div>
    `;
    return;
  }

  // Only clear shared element title if this mount is still the active mount
  if (isMountActive()) {
    clearSharedTitle();
  }

  if (!mountCommitted || !renderPromise) {
    return;
  }

  // 5. Await background route data fetching without blocking View Transitions
  // IMPORTANT: Register cleanup on mountInstance if mountInstance is still mounted,
  // even if an in-place same-route update superseded the initial query (Finding A).
  try {
    const cleanup = await renderPromise;
    if (typeof cleanup === 'function') {
      if (isMountActive()) {
        mountInstance.registerCleanup(cleanup);
      } else {
        // Superseded by a DIFFERENT route mount while awaiting: run cleanup immediately
        mountInstance.registerCleanup(cleanup);
        mountInstance.runCleanup();
      }
    }
  } catch (err) {
    if (!isMountActive() || signal.aborted || navId !== navigationSequence) return;
    if (err && err.name === 'AbortError') return;
    console.error('Error rendering route:', err);
    routeContainer.innerHTML = `
      <div class="notice notice-error" style="margin: 2rem auto; max-width: 600px;">
        <h3>Failed to load page</h3>
        <p>${escapeHtml(err.message || 'An unexpected error occurred.')}</p>
        <button class="btn btn-secondary" onclick="window.location.reload()">Reload</button>
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
