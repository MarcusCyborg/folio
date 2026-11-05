// src/frontend/core/motion.js
// Folio Shared Motion Tokens, Reduced-Motion Preference, View Transitions, and Animation Helpers

export const MOTION_TOKENS = {
  fast: 140,
  state: 200,
  panel: 240,
  nav: 320,
  entrance: 380,
  easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
};

/**
 * Checks if the user prefers reduced motion (OS/browser accessibility setting).
 */
export function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Subscribes to live changes in reduced motion preference.
 * Returns an unsubscribe cleanup function.
 */
export function onReducedMotionChange(callback) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {};
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  const handler = (e) => callback(e.matches);
  if (mq.addEventListener) {
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  } else if (mq.addListener) {
    mq.addListener(handler);
    return () => mq.removeListener(handler);
  }
  return () => {};
}

/**
 * Shared element title transition tracker.
 * Ensures strictly ONE element has view-transition-name: folio-doc-title in the DOM at any given moment.
 * Binds the element to an optional document ID so mismatched navigations do not morph incorrectly.
 */
let currentSharedTitleEl = null;
let currentSharedDocId = null;

export function setSharedTitle(el, docId = null) {
  if (prefersReducedMotion() || !el) return;
  clearSharedTitle();
  el.style.viewTransitionName = 'folio-doc-title';
  currentSharedTitleEl = el;
  currentSharedDocId = docId;
}

export function getSharedDocId() {
  return currentSharedDocId;
}

export function clearSharedTitle() {
  if (currentSharedTitleEl) {
    try {
      currentSharedTitleEl.style.viewTransitionName = '';
    } catch (_) {}
    currentSharedTitleEl = null;
  }
  currentSharedDocId = null;
  if (typeof document !== 'undefined') {
    const strayElements = document.querySelectorAll('[style*="folio-doc-title"]');
    strayElements.forEach((node) => {
      node.style.viewTransitionName = '';
    });
  }
}

/**
 * Active ViewTransition / fallback animation tracking so superseded navigations
 * can immediately skip or cancel in-flight transitions without interfering with newer ones.
 */
let activeViewTransition = null;
let activeFallbackAnim = null;
let activeFallbackContainer = null;

export function cancelActiveViewTransition() {
  if (activeViewTransition) {
    const prevTransition = activeViewTransition;
    activeViewTransition = null;
    try {
      if (typeof prevTransition.skipTransition === 'function') {
        prevTransition.skipTransition();
      }
    } catch (_) {}
  }
  if (activeFallbackAnim) {
    const prevAnim = activeFallbackAnim;
    activeFallbackAnim = null;
    try {
      prevAnim.cancel();
    } catch (_) {}
  }
  if (activeFallbackContainer) {
    try {
      activeFallbackContainer.style.opacity = '';
    } catch (_) {}
    activeFallbackContainer = null;
  }
}

/**
 * Executes a DOM update callback with View Transitions API if supported and motion is enabled.
 * If unsupported, provides a smooth fallback opacity transition with strict ownership checks.
 * Guarantees updateFn is never executed if stale, never executed twice on errors,
 * and never swallows render errors or leaks unhandled transition promise rejections.
 */
export async function withViewTransition(
  updateFn,
  { fallbackContainer = null, signal = null, isStale = null } = {}
) {
  const checkStale = () =>
    Boolean((signal && signal.aborted) || (typeof isStale === 'function' && isStale()));

  // Immediately cancel any previous transition or fallback animation before starting a new one
  cancelActiveViewTransition();

  if (checkStale()) {
    return;
  }

  let updateFnExecuted = false;
  let updateFnError = null;

  const runUpdateOnce = async () => {
    if (updateFnExecuted || checkStale()) return;
    updateFnExecuted = true;
    try {
      await updateFn();
    } catch (err) {
      updateFnError = err;
      throw err;
    }
  };

  const supportsVT =
    typeof document !== 'undefined' &&
    typeof document.startViewTransition === 'function' &&
    !prefersReducedMotion();

  if (supportsVT) {
    let transition = null;
    const onAbort = () => {
      if (transition && activeViewTransition === transition) {
        activeViewTransition = null;
      }
      if (transition && typeof transition.skipTransition === 'function') {
        try {
          transition.skipTransition();
        } catch (_) {}
      }
    };

    if (signal) {
      signal.addEventListener('abort', onAbort, { once: true });
    }

    try {
      transition = document.startViewTransition(async () => {
        await runUpdateOnce();
      });
      activeViewTransition = transition;

      // Immediately attach rejection handlers to all ViewTransition promises
      // so skipped/superseded transitions never trigger unhandledrejection pageerrors
      if (transition.ready && typeof transition.ready.catch === 'function') {
        transition.ready.catch(() => {});
      }
      if (transition.updateCallbackDone && typeof transition.updateCallbackDone.catch === 'function') {
        transition.updateCallbackDone.catch(() => {});
      }
      if (transition.finished && typeof transition.finished.catch === 'function') {
        transition.finished.catch(() => {});
      }

      if (checkStale()) {
        onAbort();
        return;
      }

      await transition.finished.catch(() => {});
    } catch (err) {
      if (!updateFnExecuted && !checkStale()) {
        await runUpdateOnce();
      }
    } finally {
      if (signal) {
        signal.removeEventListener('abort', onAbort);
      }
      if (activeViewTransition === transition) {
        activeViewTransition = null;
      }
    }

    if (updateFnError) {
      throw updateFnError;
    }
    return;
  }

  // Fallback when View Transitions API is unsupported and motion is enabled
  if (!prefersReducedMotion() && fallbackContainer && typeof fallbackContainer.animate === 'function') {
    let currentAnim = null;
    const onAbort = () => {
      if (currentAnim) {
        try {
          currentAnim.cancel();
        } catch (_) {}
      }
      if (activeFallbackAnim === currentAnim) {
        activeFallbackAnim = null;
      }
      if (activeFallbackContainer === fallbackContainer) {
        try {
          fallbackContainer.style.opacity = '';
        } catch (_) {}
        activeFallbackContainer = null;
      }
    };

    if (signal) {
      signal.addEventListener('abort', onAbort, { once: true });
    }

    try {
      const fadeOut = fallbackContainer.animate(
        [{ opacity: 1 }, { opacity: 0.85 }],
        { duration: 100, easing: 'ease-out' }
      );
      currentAnim = fadeOut;
      activeFallbackAnim = fadeOut;
      activeFallbackContainer = fallbackContainer;

      if (fadeOut.finished && typeof fadeOut.finished.catch === 'function') {
        fadeOut.finished.catch(() => {});
        await fadeOut.finished.catch(() => {});
      }

      // Verify ownership immediately before committing DOM update
      if (checkStale()) {
        return;
      }

      await runUpdateOnce();

      if (checkStale()) {
        return;
      }

      const fadeIn = fallbackContainer.animate(
        [{ opacity: 0.85 }, { opacity: 1 }],
        { duration: 120, easing: 'ease-in' }
      );
      currentAnim = fadeIn;
      activeFallbackAnim = fadeIn;

      if (fadeIn.finished && typeof fadeIn.finished.catch === 'function') {
        fadeIn.finished.catch(() => {});
        await fadeIn.finished.catch(() => {});
      }
      return;
    } catch (err) {
      if (updateFnError) {
        throw updateFnError;
      }
      if (!updateFnExecuted && !checkStale()) {
        await runUpdateOnce();
      }
      return;
    } finally {
      if (signal) {
        signal.removeEventListener('abort', onAbort);
      }
      if (activeFallbackAnim === currentAnim) {
        activeFallbackAnim = null;
      }
      if (activeFallbackContainer === fallbackContainer) {
        try {
          fallbackContainer.style.opacity = '';
        } catch (_) {}
        activeFallbackContainer = null;
      }
    }
  }

  await runUpdateOnce();
}

/**
 * Smoothly scrolls an element into view, respecting reduced-motion preference.
 */
export function safeScrollIntoView(element, options = {}) {
  if (!element || typeof element.scrollIntoView !== 'function') return;
  const isReduced = prefersReducedMotion();
  element.scrollIntoView({
    behavior: isReduced ? 'auto' : (options.behavior || 'smooth'),
    block: options.block || 'start',
    inline: options.inline || 'nearest',
  });
}
