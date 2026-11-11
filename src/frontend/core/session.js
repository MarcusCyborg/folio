// src/frontend/core/session.js
// Client session state management and permissions checker

import { api, setCsrfToken, registerAuthMutationHook } from './api.js';

const TAB_ID = `${Math.random().toString(36).slice(2)}-${Date.now()}`;

let sessionState = {
  user: null,
  csrf_token: '',
  loaded: false,
};

const listeners = new Set();

let authChannel = null;
try {
  if (typeof window !== 'undefined' && 'BroadcastChannel' in window) {
    authChannel = new BroadcastChannel('folio_auth_channel');
    authChannel.onmessage = (event) => {
      if (event.data?.type === 'AUTH_STATE_CHANGED' && event.data?.source !== TAB_ID) {
        refreshSession({ broadcast: false });
      }
    };
  }
} catch (_) {}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === 'folio_auth_sync' && e.newValue) {
      try {
        const parsed = JSON.parse(e.newValue);
        if (parsed && parsed.source === TAB_ID) return;
      } catch (_) {}
      refreshSession({ broadcast: false });
    }
  });
  window.addEventListener('focus', () => {
    refreshSession({ broadcast: false });
  });
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        refreshSession({ broadcast: false });
      }
    });
  }
}

export function broadcastAuthChange() {
  const payload = { type: 'AUTH_STATE_CHANGED', source: TAB_ID, ts: Date.now() };
  try {
    if (authChannel) {
      authChannel.postMessage(payload);
    }
  } catch (_) {}
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('folio_auth_sync', JSON.stringify(payload));
    }
  } catch (_) {}
}

registerAuthMutationHook(() => {
  broadcastAuthChange();
});

function emit() {
  const snapshot = getSession();
  listeners.forEach((fn) => {
    try {
      fn(snapshot);
    } catch (e) {
      console.error('Session listener error:', e);
    }
  });
}

export function getSession() {
  return {
    user: sessionState.user ? { ...sessionState.user } : null,
    csrf_token: sessionState.csrf_token,
    loaded: sessionState.loaded,
  };
}

export function setSessionData(user, csrf_token, { broadcast = true } = {}) {
  sessionState = {
    user: user || null,
    csrf_token: csrf_token || '',
    loaded: true,
  };
  setCsrfToken(csrf_token);
  emit();
  if (broadcast) {
    broadcastAuthChange();
  }
}

export async function refreshSession({ broadcast = false } = {}) {
  try {
    const data = await api('/auth/session');
    setSessionData(data.user, data.csrf_token, { broadcast });
    return getSession();
  } catch (err) {
    console.warn('Failed to refresh session:', err);
    sessionState.loaded = true;
    emit();
    return getSession();
  }
}

export function can(permission) {
  if (!sessionState.user) return false;
  const user = sessionState.user;
  if (user.role_key === 'super_admin') return true;
  if (!user.permissions || !Array.isArray(user.permissions)) return false;
  return user.permissions.includes(permission);
}

export function subscribeSession(listener) {
  listeners.add(listener);
  // Trigger once immediately with current state
  try {
    listener(getSession());
  } catch (e) {
    console.error('Initial session listener error:', e);
  }
  return () => {
    listeners.delete(listener);
  };
}
