// src/frontend/core/api.js
// Standardized client-side API fetch wrapper for Folio API v1

export class ApiError extends Error {
  constructor(status, code, message, fields = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

let currentCsrfToken = '';
let authMutationHook = null;

export function setCsrfToken(token) {
  currentCsrfToken = token || '';
}

export function getCsrfToken() {
  return currentCsrfToken;
}

export function registerAuthMutationHook(fn) {
  authMutationHook = typeof fn === 'function' ? fn : null;
}

export async function api(path, { method = 'GET', query, body, signal } = {}) {
  // Normalize path relative to /api/v1
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  const basePath = cleanPath.startsWith('/api/v1') ? cleanPath : `/api/v1${cleanPath}`;

  // Serialize query string, skipping null/undefined/empty
  const url = new URL(basePath, window.location.origin);
  if (query && typeof query === 'object') {
    Object.entries(query).forEach(([key, val]) => {
      if (val !== null && val !== undefined && val !== '') {
        url.searchParams.set(key, String(val));
      }
    });
  }

  const headers = {
    'Accept': 'application/json',
  };

  const isUnsafeMethod = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase());
  if (isUnsafeMethod && currentCsrfToken) {
    headers['X-CSRF-Token'] = currentCsrfToken;
  }

  let requestBody = undefined;
  if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json';
    requestBody = JSON.stringify(body);
  }

  try {
    const res = await fetch(url.toString(), {
      method: method.toUpperCase(),
      headers,
      body: requestBody,
      credentials: 'same-origin',
      signal,
    });

    // Check for CSRF rotation in response header or cookies
    const respCsrf = res.headers.get('X-CSRF-Token');
    if (respCsrf) {
      setCsrfToken(respCsrf);
    }

    if (res.status === 204) {
      if (isUnsafeMethod && /^\/api\/v1\/auth\/(login|register|logout|password)$/.test(basePath) && authMutationHook) {
        try { authMutationHook(basePath); } catch (_) {}
      }
      return null;
    }

    const contentType = res.headers.get('content-type') || '';
    const isJson = contentType.includes('application/json');
    const data = isJson ? await res.json() : await res.text();

    if (!res.ok) {
      if (isJson && data && data.error) {
        // AUTH-03: Multi-tab CSRF rotation auto-recovery
        if (res.status === 403 && data.error.code === 'CSRF_FORBIDDEN' && !arguments[1]?._isCsrfRetry) {
          try {
            const sessRes = await fetch(new URL('/api/v1/auth/session', window.location.origin), {
              credentials: 'same-origin',
              headers: { 'Accept': 'application/json' },
            });
            if (sessRes.ok) {
              const sessData = await sessRes.json();
              if (sessData?.csrf_token) {
                setCsrfToken(sessData.csrf_token);
                return await api(path, { ...arguments[1], _isCsrfRetry: true });
              }
            }
          } catch (_) {}
        }
        throw new ApiError(res.status, data.error.code, data.error.message, data.error.fields || {});
      }
      throw new ApiError(res.status, 'HTTP_ERROR', `Request failed with status ${res.status}`);
    }

    // If response body contains csrf_token, keep updated
    if (isJson && data && typeof data === 'object' && data.csrf_token) {
      setCsrfToken(data.csrf_token);
    }

    if (isUnsafeMethod && /^\/api\/v1\/auth\/(login|register|logout|password)$/.test(basePath) && authMutationHook) {
      try { authMutationHook(basePath); } catch (_) {}
    }

    return data;
  } catch (err) {
    if (err.name === 'AbortError') {
      // Re-throw raw abort error without treating it as API failure
      throw err;
    }
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(0, 'NETWORK_ERROR', err.message || 'Network request failed');
  }
}
