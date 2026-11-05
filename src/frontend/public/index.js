// src/frontend/public/index.js
// Frontend Library Routes Manifest

import { renderLibrary, updateLibrary } from './library_view.js';
import { renderDocumentDetail } from './detail_view.js';
import { renderLogin, renderRegister, renderProfile } from './auth_views.js';

export const routes = [
  {
    path: '/library',
    render: renderLibrary,
    update: updateLibrary,
  },
  {
    path: '/documents/:id',
    render: renderDocumentDetail,
  },
  {
    path: '/login',
    render: renderLogin,
  },
  {
    path: '/register',
    render: renderRegister,
  },
  {
    path: '/profile',
    render: renderProfile,
  },
];
