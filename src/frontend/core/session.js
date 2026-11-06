// src/frontend/core/session.js
// Client session state management and permissions checker

import { api, setCsrfToken } from './api.js';

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
      if (event.data?.type === 'AUTH_STATE_CHANGED') {
        refreshSession();
      }
    };
  }
} catch (_) {}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === 'folio_auth_sync') {
      refreshSession();
    }
  });
  window.addEventListener('focus', () => {
    refreshSession();
  });
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        refreshSession();
      }
    });
  }
}

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
    try {
      if (authChannel) authChannel.postMessage({ type: 'AUTH_STATE_CHANGED' });
      localStorage.setItem('folio_auth_sync', String(Date.now()));
    } catch (_) {}
  }
}

export async function refreshSession() {
  try {
    const data = await api('/auth/session');
    setSessionData(data.user, data.csrf_token, { broadcast: false });
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
