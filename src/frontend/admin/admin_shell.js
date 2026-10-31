// src/frontend/admin/admin_shell.js
// Common Admin Layout & Navigation Sidebar

import { can, getSession } from '../core/session.js';

export function wrapAdminLayout(currentPath, pageTitle, contentHtml) {
  // Navigation items grouped by domain, guarded by granular permissions
  const navGroups = [
    {
      group: 'Content',
      items: [
        { label: 'Documents', path: '/admin/documents', perm: ['documents:write', 'seo:write'] },
        { label: 'Taxonomy', path: '/admin/taxonomy', perm: ['taxonomy:write', 'documents:write'] },
      ]
    },
    {
      group: 'Community',
      items: [
        { label: 'Comments Queue', path: '/admin/comments', perm: ['moderation:manage'] },
        { label: 'Flags & Reports', path: '/admin/reports', perm: ['moderation:manage'] },
      ]
    },
    {
      group: 'Administration',
      items: [
        { label: 'SEO Metadata', path: '/admin/seo', perm: ['seo:write'] },
        { label: 'Library Analytics', path: '/admin/analytics', perm: ['analytics:read'] },
        { label: 'Users & Staff', path: '/admin/users', perm: ['users:manage'] },
        { label: 'Roles Matrix', path: '/admin/roles', perm: ['roles:manage'] },
        { label: 'Audit Trail', path: '/admin/audit', perm: ['audit:read'] },
        { label: 'Settings', path: '/admin/settings', perm: ['settings:write'] },
      ]
    }
  ];

  const sidebarGroupsHtml = navGroups.map((g) => {
    const visibleItems = g.items.filter((item) => item.perm.some((p) => can(p)));
    if (visibleItems.length === 0) return '';

    const itemsHtml = visibleItems.map((item) => {
      const isActive = currentPath === item.path || (item.path !== '/admin/documents' && currentPath.startsWith(item.path));
      return `
        <li>
          <a href="#${item.path}" class="admin-sidebar-link ${isActive ? 'active' : ''}">
            ${escapeText(item.label)}
          </a>
        </li>
      `;
    }).join('');

    return `
      <div class="admin-nav-group">
        <div class="admin-nav-group-title">${escapeText(g.group)}</div>
        <ul class="admin-sidebar-nav">
          ${itemsHtml}
        </ul>
      </div>
    `;
  }).join('');

  const session = getSession();
  const userName = session.user ? (session.user.display_name || session.user.username) : 'Staff';
  const roleLabel = session.user ? session.user.role_key.replace('_', ' ') : 'Guest';

  return `
    <div class="admin-page">
      <div class="admin-layout">
        <aside class="admin-sidebar">
          <div class="admin-sidebar-header">
            <div class="admin-sidebar-kicker">Folio Workspace</div>
            <div class="admin-sidebar-user">
              <strong>${escapeText(userName)}</strong>
              <span class="role-chip">${escapeText(roleLabel)}</span>
            </div>
          </div>
          <div class="admin-sidebar-nav-container">
            ${sidebarGroupsHtml || '<p style="padding: 0.75rem 1.25rem; font-size: 0.85rem; color: var(--color-muted);">No accessible sections</p>'}
          </div>
          <div class="admin-sidebar-footer">
            <a href="#/library" class="btn btn-secondary btn-sm" style="width: 100%; display: block; text-align: center;">
              &larr; Public Library
            </a>
          </div>
        </aside>

        <section class="admin-main">
          <div class="admin-header-row">
            <h1 class="admin-title">${escapeText(pageTitle)}</h1>
          </div>
          <div class="admin-body-area">
            ${contentHtml}
          </div>
        </section>
      </div>
    </div>
  `;
}

function escapeText(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
