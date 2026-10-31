# Folio — Architecture & System Design Specification

This document provides a comprehensive technical reference for the architecture of **Folio — Knowledge & Research Library**, an enterprise research document repository built to satisfy Phase 1 full-stack requirements and establish the foundation for Phase 2 information retrieval algorithms.

---

## 1. System Topology & Architecture Overview

Folio adopts a modular, tiered architecture separating persistent storage, core domain services, RESTful API presentation, and a native ES-module frontend.

```mermaid
graph TD
    Client["Client Browser (Desktop Viewports: 1280x720 - 1920x1080)<br/>Vanilla ES Modules + Hash Router"]
    
    subgraph FastAPI_Backend ["FastAPI Application (Port 8000)"]
        RouterAuth["Auth & Session Controller<br/>(/api/v1/auth)"]
        RouterLib["Public Library & Engagement<br/>(/api/v1/documents, /categories, /tags, /events)"]
        RouterAdmin["Administrative Controller (RBAC)<br/>(/api/v1/admin/*)"]
        
        SecDeps["Security & RBAC Guard<br/>Argon2id, Session Cookies, CSRF Validator"]
        AuditService["Audit Service<br/>Transactional Mutation Logger"]
        Sanitizer["Sanitizer & Markdown<br/>Bleach Allowlist + KaTeX Math"]
    end
    
    subgraph Persistence ["PostgreSQL 16+ RDBMS"]
        TablesAuth["Auth Tables<br/>(users, roles, permissions, sessions)"]
        TablesDocs["Document Store<br/>(documents, categories, tags, document_tags)"]
        TablesEngage["Engagement & Moderation<br/>(comments, comment_mentions, likes, reports)"]
        TablesLogs["Standardized Interaction Logs<br/>(interaction_logs, view_events, audit_logs)"]
    end

    Client -->|HTTP / JSON + Cookie + CSRF| FastAPI_Backend
    RouterAuth --> SecDeps
    RouterLib --> SecDeps
    RouterAdmin --> SecDeps
    RouterAdmin --> AuditService
    RouterLib --> Sanitizer
    
    SecDeps --> TablesAuth
    RouterLib --> TablesDocs
    RouterLib --> TablesEngage
    RouterLib --> TablesLogs
    RouterAdmin --> TablesDocs
    RouterAdmin --> TablesEngage
    AuditService --> TablesLogs
```

---

## 2. Relational Entity-Relationship Diagram (ERD)

The database schema is managed via Alembic migrations on PostgreSQL 16+.

```mermaid
erDiagram
    ROLES ||--o{ ROLE_PERMISSIONS : defines
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : grants
    ROLES ||--o{ USERS : assigns
    USERS ||--o{ SESSIONS : establishes
    
    USERS ||--o{ DOCUMENTS : authors
    CATEGORIES ||--o{ DOCUMENTS : classifies
    DOCUMENTS ||--o{ DOCUMENT_TAGS : labeled_with
    TAGS ||--o{ DOCUMENT_TAGS : labels
    
    DOCUMENTS ||--o{ DOCUMENT_LIKES : receives
    USERS ||--o{ DOCUMENT_LIKES : likes
    
    DOCUMENTS ||--o{ COMMENTS : contains
    USERS ||--o{ COMMENTS : posts
    COMMENTS ||--o{ COMMENT_MENTIONS : mentions
    USERS ||--o{ COMMENT_MENTIONS : tagged_in
    
    COMMENTS ||--o{ REPORTS : flagged_by
    USERS ||--o{ REPORTS : reports
    
    USERS ||--o{ INTERACTION_LOGS : performs
    DOCUMENTS ||--o{ INTERACTION_LOGS : targets
    
    DOCUMENTS ||--o{ VIEW_EVENTS : accumulates
    USERS ||--o{ AUDIT_LOGS : acts

    USERS {
        uuid id PK
        varchar email UK
        varchar username UK
        varchar display_name
        varchar password_hash
        varchar role_key FK
        boolean is_active
        timestamp commenting_suspended_until
        timestamp created_at
    }

    ROLES {
        varchar key PK
        varchar label
        boolean is_protected
    }

    PERMISSIONS {
        varchar key PK
        varchar description
    }

    DOCUMENTS {
        uuid id PK
        varchar title
        text content
        text summary
        varchar author
        uuid category_id FK
        varchar status
        integer views_count
        integer likes_count
        integer comments_count
        varchar cover_image_url
        varchar cover_image_alt
        varchar source_url
        varchar source_attribution
        varchar seo_title
        text seo_description
        jsonb seo_keywords
        timestamp published_at
        timestamp created_at
        timestamp updated_at
        timestamp deleted_at
    }

    CATEGORIES {
        uuid id PK
        varchar name UK
        varchar slug UK
        text description
    }

    TAGS {
        uuid id PK
        varchar name UK
        varchar slug UK
    }

    INTERACTION_LOGS {
        uuid id PK
        varchar event_type
        uuid actor_key
        uuid user_id FK
        varchar query_string
        uuid clicked_doc_id FK
        uuid search_event_id
        jsonb result_doc_ids
        timestamp timestamp
    }

    AUDIT_LOGS {
        uuid id PK
        uuid actor_id FK
        varchar action
        varchar entity_type
        varchar entity_id
        jsonb before_state
        jsonb after_state
        timestamp created_at
    }
```

---

## 3. Roles and Permissions Matrix (RBAC)

Folio uses a fine-grained, database-driven capability permission system. Application endpoints enforce capabilities (e.g., `documents:write`, `moderation:manage`) rather than role string checks.

| Capability Permission | member | content_manager | moderator | data_seo | super_admin |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `documents:write` | - | **Yes** | - | - | **Yes** |
| `taxonomy:write` | - | **Yes** | - | - | **Yes** |
| `moderation:manage` | - | - | **Yes** | - | **Yes** |
| `seo:write` | - | - | - | **Yes** | **Yes** |
| `analytics:read` | - | - | - | **Yes** | **Yes** |
| `users:manage` | - | - | - | - | **Yes** |
| `roles:manage` | - | - | - | - | **Yes** |
| `audit:read` | - | - | - | - | **Yes** |
| `settings:write` | - | - | - | - | **Yes** |

### Last Super Administrator Protection Invariant
To prevent administrative lockout:
- Any modification to user status (`is_active = false`) or role (`role_key != 'super_admin'`) executes an explicit row-locked SQL query (`SELECT ... FOR UPDATE`) checking the count of active super administrators.
- If the target user is the final remaining active `super_admin`, the request is rejected with HTTP `409 Conflict` and transaction rolled back.
- The `super_admin` role's capabilities cannot be modified or revoked in the Permissions Matrix.

---

## 4. Phase 2 Document Store & Standardized Interaction Logging

### Document Schema Mapping
The `documents` table fulfills all Phase 2 storage requirements:
- `id` (UUID): Primary key.
- `title` (VARCHAR 500): Article title.
- `content` (TEXT): Raw Markdown/HTML research text.
- `summary` (TEXT): Abstract / teaser.
- `category_id` (UUID FK): Many-to-one relationship to `categories`.
- `tags`: Many-to-many relationship joined via `document_tags`. Public API serializes tags as `[{id, name, slug}, ...]`.
- `author` (VARCHAR 255): Attribution / scholar name.
- `created_at` (TIMESTAMP UTC): System creation timestamp.
- `views_count` (INTEGER): Cached counter updated via idempotent `POST /documents/{id}/views`.

### Search & Click Interaction Logging Semantics
Folio implements a two-event click-through tracking pipeline designed for evaluation and ranking training:

1. **Search Request Event:**
   - Triggered when a client queries `GET /api/v1/documents?q=<term>`.
   - Generates a record in `interaction_logs` with `event_type = 'search'`, `query_string = <term>`, `result_doc_ids = [<uuid>, ...]`, and assigns a unique `search_event_id`.
   - If user is anonymous, `user_id` is recorded as `NULL`, but `actor_key` (opaque browser session UUID) is persisted.
   - Searching without a keyword (e.g. browsing a category) returns `search_event_id = null` and logs no search query event.

2. **Result Click Event:**
   - Triggered when a user clicks a search result card (`POST /api/v1/events/clicks`).
   - The payload provides `{search_event_id, document_id, request_key}`.
   - The backend validates:
     - The referenced `search_event_id` exists and belongs to the same `actor_key`.
     - The target `document_id` was actually present in `result_doc_ids` of that search.
     - The target document is currently published and not deleted.
   - A separate record is inserted into `interaction_logs` with `event_type = 'click'`, copying `query_string` server-side from the parent search event, recording `clicked_doc_id`, `search_event_id`, and `user_id`.
   - **Idempotency Guarantee:** Retrying with the same `request_key` UUID returns the existing click ID without double-counting clicks.

---

## 5. Security & Authentication Architecture

1. **Password Hashing:**
   - Implemented using Argon2id with salt generation via `argon2-cffi`. Plaintext passwords are never stored or logged.

2. **Session Lifecycle:**
   - Cookie-based session token (`folio_session`) generated using `secrets.token_urlsafe(32)` (256-bit entropy).
   - Marked `HttpOnly`, `SameSite=Lax`, `Path=/`.
   - Only the SHA-256 hash of the session token is stored in the database.
   - On authentication (login/register/logout/password change), session tokens are rotated to prevent session fixation.

3. **CSRF Protection:**
   - Every state-changing HTTP method (`POST`, `PUT`, `PATCH`, `DELETE`) enforces a valid `X-CSRF-Token` header.
   - The CSRF token is issued in session context (`GET /api/v1/auth/session`), bound to the active session ID, and verified cryptographically on every mutation.

4. **Sanitization:**
   - Public user content (comments, bios) and research content are sanitized using `bleach` with a strict allowlist (`p`, `h1`-`h6`, `pre`, `code`, `blockquote`, `ul`, `ol`, `li`, `a`, `img`, `strong`, `em`).
   - All external hyperlinks enforce `rel="noopener noreferrer"`.
   - Raw JavaScript tags (`<script>`), event handlers (`onload`, `onerror`), and `javascript:` URIs are stripped.
