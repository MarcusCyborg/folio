# Folio — UI Component & Style Guide

This guide documents the design tokens, shared CSS classes, and core JavaScript helper modules provided by Foundation for the Public Library and Admin UI lanes.

## 1. Design Tokens (`style.css`)

```css
:root {
  --color-bg: #F6F4EE;         /* Warm paper white */
  --color-surface: #FFFFFF;    /* Clean card & form surface */
  --color-text: #20323D;       /* Deep ink blue for high readability */
  --color-muted: #5E717D;      /* Secondary captions and labels */
  --color-accent: #16675B;     /* Primary teal accent */
  --color-accent-hover: #115349;
  --color-border: #DADFD9;     /* Subtle divider line */
  --color-danger: #C0392B;     /* Destructive action red */
  --color-danger-hover: #9E2B1E;
  --color-success: #27AE60;

  --font-ui: "Source Sans 3", system-ui, sans-serif;
  --font-reading: "Source Serif 4", Georgia, serif;

  --header-height: 68px;
}
```

## 2. Core Frontend Modules

### `src/frontend/core/api.js`
API client wrapper pre-configured for same-origin requests, CSRF token attachment, and unified error mapping.

```javascript
import { api, ApiError } from '../core/api.js';

// GET request with query filtering
const data = await api('/documents', { query: { q: 'neural', page: 1 } });

// POST mutation with automatic X-CSRF-Token injection
await api('/documents/123/like', { method: 'PUT' });
```

### `src/frontend/core/session.js`
In-memory session store providing reactive authentication and permission queries.

```javascript
import { getSession, can, subscribeSession } from '../core/session.js';

// Check effective permission dynamically
if (can('documents:write')) {
  // Show editor or publish controls
}

// React to login/logout events
const unsubscribe = subscribeSession((session) => {
  console.log('Current user:', session.user);
});
```

### `src/frontend/core/router.js`
Hash router with automatic route parameters and `AbortController` cancellation for unmounted routes.

```javascript
import { navigate } from '../core/router.js';

navigate('/documents/123'); // Updates URL hash to #/documents/123
```

### `src/frontend/core/ui.js`
Shared UI feedback, alerts, dialogs, and pagination.

```javascript
import { notify, confirmAction, renderPagination, renderError, renderEmpty } from '../core/ui.js';

// Toast feedback
notify('Document published successfully!', { kind: 'success' });

// Modal confirmation for destructive operations
const ok = await confirmAction({
  title: 'Delete Document',
  message: 'Are you sure you want to delete this document?',
  confirmLabel: 'Delete',
  destructive: true
});
if (ok) {
  // proceed with deletion
}

// Render pagination
renderPagination(paginationEl, {
  page: 1,
  pageSize: 20,
  total: 100,
  onChange: (newPage) => loadPage(newPage)
});
```

## 3. Shared HTML & CSS Components

### Buttons
```html
<button class="btn btn-primary">Primary Action</button>
<button class="btn btn-secondary">Secondary Action</button>
<button class="btn btn-danger">Delete / Destructive</button>
<button class="btn btn-secondary btn-sm">Small Button</button>
```

### Forms & Input Fields
```html
<div class="field">
  <label class="label" for="docTitle">Document Title</label>
  <input class="input" id="docTitle" type="text" placeholder="Enter title" />
</div>

<div class="field">
  <label class="label" for="categorySelect">Category</label>
  <select class="select" id="categorySelect">
    <option value="ai">Artificial Intelligence</option>
  </select>
</div>
```

### Tables
```html
<div class="table-container">
  <table class="table">
    <thead>
      <tr>
        <th>Title</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Deep Learning Fundamentals</td>
        <td><span class="badge badge-teal">Published</span></td>
        <td><button class="btn btn-secondary btn-sm">Edit</button></td>
      </tr>
    </tbody>
  </table>
</div>
```

### Lane Scoping Rules
- **Public Lane:** Scope all lane-specific CSS under `.public-page` or with `.library-*`, `.document-*`, `.auth-*`. Edit only `src/frontend/public/public.css`.
- **Admin Lane:** Scope all lane-specific CSS under `.admin-page` or with `.admin-*`. Edit only `src/frontend/admin/admin.css`.
- Do **NOT** override global `:root`, `body`, or component classes from lane stylesheets.
