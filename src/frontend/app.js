// src/frontend/app.js
// Folio Application Shell & Entrypoint

import { refreshSession, subscribeSession, can } from './core/session.js';
import { initRouter, navigate } from './core/router.js';
import { routes as publicRoutes } from './public/index.js';
import { routes as adminRoutes } from './admin/index.js';
import { api } from './core/api.js';

// Preserve same-origin API_BASE resolution
export const API_BASE = (typeof window !== 'undefined' && window.location.origin && window.location.origin.startsWith('http'))
  ? window.location.origin
  : 'http://127.0.0.1:8000';

const allRoutes = [...publicRoutes, ...adminRoutes];

function renderUserMenu(session) {
  const spinner = document.getElementById('userMenuSpinner');
  const content = document.getElementById('userMenuContent');
  const adminNav = document.getElementById('navAdmin');

  if (spinner) spinner.style.display = 'none';
  if (!content) return;
  content.style.display = 'flex';
  content.style.alignItems = 'center';
  content.style.gap = '1rem';

  // Toggle Admin link in header if user has any administrative permissions
  const hasStaffAccess = can('documents:write') ||
    can('taxonomy:write') ||
    can('moderation:manage') ||
    can('seo:write') ||
    can('analytics:read') ||
    can('users:manage') ||
    can('roles:manage') ||
    can('audit:read') ||
    can('settings:write');

  if (adminNav) {
    adminNav.style.display = hasStaffAccess ? 'inline-block' : 'none';
  }

  if (session && session.user) {
    const user = session.user;
    content.innerHTML = `
      <div class="user-badge">
        <span>${escapeText(user.display_name)}</span>
        <span class="role-chip">${escapeText(user.role_key.replace('_', ' '))}</span>
      </div>
      <a href="#/profile" class="btn btn-secondary btn-sm">Profile</a>
      <button class="btn btn-secondary btn-sm" id="logoutBtn">Sign Out</button>
    `;

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
      logoutBtn.onclick = async () => {
        try {
          await api('/auth/logout', { method: 'POST' });
          await refreshSession();
          navigate('/library');
        } catch (err) {
          console.error('Logout failed:', err);
        }
      };
    }
  } else {
    content.innerHTML = `
      <a href="#/login" class="btn btn-secondary btn-sm">Sign In</a>
      <a href="#/register" class="btn btn-primary btn-sm">Join</a>
    `;
  }
}

function updateActiveNav() {
  const currentHash = window.location.hash || '#/library';
  const navLinks = document.querySelectorAll('.nav-link');
  navLinks.forEach((link) => {
    const href = link.getAttribute('href');
    if (href && currentHash.startsWith(href)) {
      link.classList.add('active');
    } else {
      link.classList.remove('active');
    }
  });
}

function escapeText(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Bootstrap Folio
let publicSettings = {
  site_name: 'Folio',
  site_description: 'Knowledge & Research Library',
  registration_enabled: true,
  comments_enabled: true,
};

export function getPublicSettings() {
  return publicSettings;
}

async function loadPublicSettings() {
  try {
    const data = await api('/settings/public');
    if (data) {
      if (data.site_name) data.site_name = data.site_name.replace('—', ':');
      publicSettings = { ...publicSettings, ...data };
      const brandEl = document.getElementById('shellBrandName');
      const taglineEl = document.getElementById('shellBrandTagline');
      if (brandEl && data.site_name) brandEl.textContent = data.site_name;
      if (taglineEl && data.site_description) taglineEl.textContent = data.site_description;
    }
  } catch (err) {
    console.warn('Could not load public settings:', err);
  }
}

async function bootstrap() {
  const appContainer = document.getElementById('app');

  // 1. Subscribe user menu to session changes
  subscribeSession((session) => {
    renderUserMenu(session);
  });

  // 2. Initial session & public settings retrieval
  await Promise.all([
    refreshSession(),
    loadPublicSettings(),
  ]);

  // 3. Initialize Hash Router
  initRouter(appContainer, allRoutes);

  // 4. Listen to route changes to update active nav indicator
  window.addEventListener('hashchange', updateActiveNav);
  updateActiveNav();
}

bootstrap().catch((err) => {
  console.error('Failed to bootstrap Folio:', err);
});
