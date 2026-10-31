# Frontend Library Status Report

Status: READY_FOR_INTEGRATION
ReadyToIntegrate: yes

## Scope and owned files:
- `src/frontend/public/**`:
  - `index.js`: Public route manifest (`/library`, `/documents/:id`, `/login`, `/register`, `/profile`).
  - `library_view.js`: Library catalog, search, sidebar categories, active filter chips, pagination, real metrics.
  - `detail_view.js`: Research document reading view (760px column, Source Serif 4), view & search click logging, like/unlike toggle, discussions & peer notes feed.
  - `mentions.js`: Accessible `@username` autocomplete module with keyboard navigation.
  - `auth_views.js`: Login, registration, and scholar profile management views.
  - `public.css`: Scoped stylesheet implementing design tokens, 1280–1920 laptop/desktop responsive layout, ~220px sidebar, 760px reading column, modal dialogs, and visible focus states.
- `tests/frontend/public/**`:
  - `test_public_flows.py`: Comprehensive Playwright browser automation test suite verifying all public flows, accessibility states, error handling, and visual evidence across viewports.
- Evidence directory: `docs/verification/public/` (16 screenshots across 5 screen resolutions, zoom, and interaction states).
- Handoff status and requests: `docs/handoff/status/frontend-library.md`, `docs/handoff/requests/frontend-library.md`.

## Implemented Screens and Flows:

1. **`#/library` (Catalog & Discovery)**:
   - Synchronizes URL query parameters: `q`, `category_id`, `tag_ids`, `date_from`, `date_to`, `sort`, `page`. Browser back/forward navigation and reload work seamlessly.
   - Any filter change immediately resets `page` to 1.
   - Real results rendered immediately in the first viewport (no large hero or fake statistics).
   - Sidebar categories constrained to ~220px with real published document counts.
   - Active filter chips bar surfaces active queries, categories, tags, and dates with individual removal buttons (`✕`) and a "Clear All" action.
   - Date range filtering with client validation preventing invalid `from > to` requests.
   - Document rows display category badge, author, Added date, title linking to detail (with `search_event_id` when searching), summary, clickable tag chips, and real interaction counters (views, likes, comments).
   - AbortController signal discards stale fetch responses to prevent slow requests from overwriting newer user selections.
   - Route cleanup handler resets document title back to `Folio — Knowledge & Research Library`.

2. **`#/documents/:id` (Reading View, Provenance, & Analytics)**:
   - Optimal reading column width (760px centered, Source Serif 4, line-height 1.8) ensuring comfortable reading on 1280px laptops up to 1920px desktops without stretching text.
   - Cover image rendered with alternative caption when present.
   - Executive summary card highlighting key takeaways.
   - Renders only sanitized HTML content allowlisted by backend.
   - Source provenance and license attribution (CC BY-SA 4.0), with protocol validation ensuring only safe `http://` or `https://` URLs are rendered as clickable links.
   - Idempotent view event recording via `POST /documents/:id/views` with unique navigation UUID. Analytics failure does not disrupt reading.
   - Search result click event tracking (`POST /events/clicks`) linked to `search_event_id` with single-key retry logic. Direct catalog links do not submit fake clicks.
   - Dynamic document title (`<Title> — Folio`) and meta description (`doc.seo_description` / `doc.summary`), cleanly restored on route cleanup.

3. **Discussions, Likes, and Scholar Engagement**:
   - Like / Unlike toggle calls `PUT` / `DELETE /documents/:id/like` idempotently with disabled pending state and live count updates. Unauthenticated users are redirected to login with safe `next` parameter.
   - Honors system settings (`comments_enabled`) and user moderation status (`commenting_suspended_until`): surfaces warning notices and hides compose/edit actions when suspended or disabled.
   - Paginated comments stream with oldest-first ordering and page controls.
   - Real-time `@username` autocomplete popup while typing `@` in compose and inline edit textareas: queries `GET /users/mentions?q=...` (min 2 chars), supports keyboard arrow selection and Enter/Tab insertion.
   - Inline comment editor for owners (replacing `prompt()`) with save and cancel buttons.
   - Owner comment deletion with accessible modal confirmation (`confirmAction`).
   - Moderation report modal dialog with reason selector (`spam`, `abuse`, `other`), optional details, and clean 409 conflict handling ("You already submitted an open report for this note.").
   - Strict plain-text escaping for all user comments and usernames.

4. **`#/login` & `#/register`**:
   - Form validation with visible field-level error messages beneath invalid inputs and overall alert box.
   - Submit buttons disabled with loading indicators during in-flight requests.
   - Login validates non-empty email format and password; refreshes session and CSRF token upon success; redirects to validated local hash route (`safeNext` starting with `/` and rejecting `//` or scheme protocols).
   - Register checks `registration_enabled` setting (disabling registration when turned off); validates email, username regex (`^[a-z0-9_]{3,30}$`), display name (1–80 chars), and password length (min 10 chars). Server validation errors mapped to field-level highlights.
   - No role assignment requested from client; forced to `member` role server-side.

5. **`#/profile`**:
   - Route guard redirects guests to login.
   - Scholar identity overview: username, email address, platform role chip, registration date, and effective permissions badges.
   - Commenting privilege notice displayed if user is temporarily suspended by moderator.
   - Public details editor for display name and bio (with live character counter up to 1000).
   - Security credentials update for password modification requiring current password and matching confirmation.

## Commands Run and Actual Results:

1. `python -m pytest tests/frontend/public/test_public_flows.py -v`:
   - Output: `4 passed, 4 warnings in 19.27s` (100% pass rate).
2. `python -m pytest tests/backend/library tests/backend/foundation tests/backend/integration tests/frontend/public -v`:
   - Output: `32 passed, 9 warnings in 37.22s` (100% pass rate across entire project).

## Visual Verification Artifacts (`docs/verification/public/`):
- `library_1280x720.png`: Standard laptop first-viewport with sidebar and real document rows above fold.
- `library_1280x720_zoom125.png`: Laptop 125% OS zoom rendering without layout breakage.
- `library_1366x768.png`: 1366x768 laptop resolution presentation.
- `library_1440x900.png`: High-resolution laptop presentation.
- `library_1920x1080.png`: Desktop 1920x1080 viewport verifying 760px reading column and lack of horizontal overflow.
- `library_filter_active_chips.png`: Active search keyword and category filter chips with removal buttons.
- `library_empty_state.png`: Zero-result state with "Reset All Filters" CTA.
- `document_detail_reading_view.png`: Research article view with metadata, summary, reading column, and likes.
- `document_mentions_autocomplete.png`: `@mentions` autocomplete dropdown active on typing `@ad`.
- `document_comment_posted.png`: Published peer note with author identity and `@admin` mention tag.
- `document_comment_inline_edit.png`: Accessible inline comment editor with save/cancel controls.
- `document_comment_report_modal.png`: Moderation report dialog with reason selector and details.
- `auth_login_validation.png`: Field-level error feedback on empty/invalid login submission.
- `auth_login_success.png`: Authenticated state with scholar name and profile shortcut.
- `auth_register_validation.png`: Comprehensive field validation on registration form.
- `scholar_profile_view.png`: Scholar profile card, bio editor, and password modification panel.

## Contract Deviations / Shared-file Requests:
- No deviations from CONTRACTS.md.
- No files outside lane ownership modified (`index.html`, root `app.js`, root `style.css`, and `core/**` untouched).

## Known Failures and Unverified Paths:
- None. All views connected directly to live `/api/v1` backend and verified with real database records.

## How to Manually Verify:
1. Ensure PostgreSQL is running.
2. Run `alembic upgrade head` and `python scripts/seed_folio.py`.
3. Start the application: `python -m uvicorn src.backend.main:app --port 8000`.
4. Open `http://127.0.0.1:8000/#/library` in Chrome or Edge.
5. Try searching for `"deep learning"`, click a collection in the sidebar, click a tag chip, and inspect the active filters bar.
6. Open an article, verify reading typography and provenance, toggle like, sign in as `reader@folio.test` (`FolioDemo2026!`), type `@ad` in the comment box, post a note, edit the note inline, and report or delete notes.
