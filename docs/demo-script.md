# Folio - Demo Script (8-10 Minutes)

The application has two roles: Super Admin and Member. Use a prepared local/demo
database for writes. Demo credentials are not a claim that public deployments have
these accounts.

| Role | Email | Password |
| --- | --- | --- |
| Super Admin | `admin@folio.test` | `FolioDemo2026!` |
| Member | `reader@folio.test` | `FolioDemo2026!` |

## 1. Discover and Read (2 Minutes)

1. Open `#/library`. Explain the curated collection, categories, tags, and pagination.
2. Search for `neural`; show result ranking, snippets, filters, and the actual engine
   badge. If it says `ilike_fallback`, explain fallback instead of claiming BM25 ran.
3. Click a result from that search to open the reading page. Show full content,
   metadata, and source attribution. Result clicks are linked to search events.

## 2. Reader Engagement (1 Minute)

1. Sign in as Member and return to the article.
2. Like the article and post a demo comment mentioning `@admin`.
3. Point out reporting on another user's comment. A comment owner cannot report
   their own comment through the UI. Prepare a report from a second Member account
   before the demo if you want to demonstrate the full report resolution workflow.
4. Show that the Member has no Admin navigation or administrative access.

## 3. Content and Publication (2 Minutes)

1. Sign in as Super Admin once; keep this account for all remaining steps.
2. Open Documents and create `Folio Demo - Neural Networks` with prepared content.
3. Show Markdown preview, save as Draft, reopen, and edit the summary.
4. Publish to Library and open the public detail page. Do not promise immediate
   search-index freshness; publication and indexing are separate operations.
5. Show Taxonomy for category/tag management. Use only disposable demo content
   when demonstrating deletion.

## 4. Moderation (1 Minute)

1. Open Comments and hide the demo comment, or resolve a prepared report in
   Flags & Reports.
2. Return to the public article to verify that the hidden comment is no longer
   shown. Explain optional temporary commenting suspension.
3. These operations belong to Super Admin; there is no separate Moderator role.

## 5. SEO and Analytics (1 Minute)

1. Open SEO Metadata for the demo document, edit its title/description, and show
   the search-result snippet preview.
2. Open Analytics: published documents, search requests, result clicks, document
   views, daily activity, top queries, and top read documents.

## 6. Users, Permissions, and Audit (1-2 Minutes)

1. Open Users & Staff: the only role choices are Super Admin and Member.
2. Open Roles & Permissions Matrix: Super Admin has every administrative capability;
   Member has none. Both columns are fixed and cannot be edited.
3. Open Audit Trail and inspect a document/moderation action's before/after payload.
4. Briefly show Settings. Explain that the last active Super Admin cannot be demoted
   or deactivated, preventing administrative lockout.

Conclude: Folio connects document discovery and reading with content management,
moderation, and administration in one curated library. Wikipedia supplies sample
content; it is not automatically synchronized by a reader's search.

## Existing Installations

Apply `alembic upgrade head` before this demo. Former Content Manager, Moderator,
and Data & SEO accounts become Members. Existing Super Admin accounts retain all
administrative access. Old screenshots or presentation decks showing five roles
illustrate the previous version, not the current role model.
