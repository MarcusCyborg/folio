// src/frontend/admin/index.js
// Frontend Admin route manifest and controller wiring

import { can } from '../core/session.js';
import { navigate } from '../core/router.js';
import { renderAdminDocuments, renderDocumentEditor, renderTaxonomyManager } from './content_views.js';
import { renderCommentsQueue, renderReportsQueue } from './moderation_views.js';
import { renderUsersManager, renderRolesMatrix, renderAuditLogs, renderSettingsManager } from './governance_views.js';
import { renderSeoManager, renderAnalyticsDashboard } from './analytics_views.js';
import { renderDatabaseExplorer } from './database_views.js';

// Ensure admin stylesheet is loaded in head if not already loaded by shell
function ensureAdminStyles() {
  if (typeof document !== 'undefined' && !document.getElementById('folioAdminStyles')) {
    const link = document.createElement('link');
    link.id = 'folioAdminStyles';
    link.rel = 'stylesheet';
    link.href = './admin/admin.css';
    document.head.appendChild(link);
  }
}
ensureAdminStyles();

export const routes = [
  {
    path: '/admin',
    render: async (container, routeContext) => {
      // Find first authorized administrative lane based on effective permissions
      if (can('documents:write')) {
        navigate('/admin/documents');
      } else if (can('taxonomy:write')) {
        navigate('/admin/taxonomy');
      } else if (can('moderation:manage')) {
        navigate('/admin/comments');
      } else if (can('seo:write')) {
        navigate('/admin/seo');
      } else if (can('analytics:read')) {
        navigate('/admin/analytics');
      } else if (can('users:manage')) {
        navigate('/admin/users');
      } else if (can('roles:manage')) {
        navigate('/admin/roles');
      } else if (can('audit:read')) {
        navigate('/admin/audit');
      } else if (can('settings:write')) {
        navigate('/admin/settings');
      } else {
        container.innerHTML = `
          <div class="admin-page" style="padding: 3rem 1.5rem; max-width: 600px; margin: 0 auto; text-align: center;">
            <div class="notice notice-error" style="text-align: left;">
              <h3 style="margin-top: 0;">403 Forbidden</h3>
              <p>Your current account does not hold administrative access to Folio.</p>
              <p style="margin-bottom: 0;">If you require staff privileges, please contact a super administrator.</p>
            </div>
            <div style="margin-top: 1.5rem;">
              <a href="#/library" class="btn btn-secondary">&larr; Return to Library</a>
            </div>
          </div>
        `;
      }
    }
  },
  {
    path: '/admin/documents',
    render: renderAdminDocuments
  },
  {
    path: '/admin/documents/new',
    render: renderDocumentEditor
  },
  {
    path: '/admin/documents/:id/edit',
    render: renderDocumentEditor
  },
  {
    path: '/admin/taxonomy',
    render: renderTaxonomyManager
  },
  {
    path: '/admin/comments',
    render: renderCommentsQueue
  },
  {
    path: '/admin/reports',
    render: renderReportsQueue
  },
  {
    path: '/admin/seo',
    render: renderSeoManager
  },
  {
    path: '/admin/seo/:id',
    render: renderSeoManager
  },
  {
    path: '/admin/analytics',
    render: renderAnalyticsDashboard
  },
  {
    path: '/admin/users',
    render: renderUsersManager
  },
  {
    path: '/admin/roles',
    render: renderRolesMatrix
  },
  {
    path: '/admin/audit',
    render: renderAuditLogs
  },
  {
    path: '/admin/database',
    render: renderDatabaseExplorer
  },
  {
    path: '/admin/settings',
    render: renderSettingsManager
  }
];
