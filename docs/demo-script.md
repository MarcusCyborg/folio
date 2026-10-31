# Folio — Evaluator Demo Script (8–10 Minutes)

This script provides an 8–10 minute step-by-step demonstration walkthrough for instructors and graders evaluating **Folio — Knowledge & Research Library**.

All demo accounts use password: `FolioDemo2026!`

| Persona | Email | Username | Primary Role |
| :--- | :--- | :--- | :--- |
| **Reader / Member** | `reader@folio.test` | `reader` | `member` |
| **Content Manager** | `content@folio.test` | `content_mgr` | `content_manager` |
| **Moderator** | `moderator@folio.test` | `moderator` | `moderator` |
| **Data & SEO Specialist** | `seo@folio.test` | `seo_specialist` | `data_seo` |
| **Super Administrator** | `admin@folio.test` | `admin` | `super_admin` |

---

## Act 1: Public Library & Engagement (Reader — 2.5 mins)

1. **Launch & Navigation (`#/library`):**
   - Open browser at `http://127.0.0.1:8002` (or development server at `http://127.0.0.1:8000`).
   - Observe the paper-and-ink visual aesthetic (`#F6F4EE` background, `#20323D` ink headings, `#16675B` teal accents, self-hosted Source Serif 4 headings and Source Sans 3 UI typography).
   - Point out the active collection: **100 authentic published articles** categorized across:
     - *Artificial Intelligence & Machine Learning* (18 articles)
     - *Computer Science & Systems* (18 articles)
     - *Mathematics & Optimization* (16 articles)
     - *Neuroscience & Cognitive Science* (16 articles)
     - *Scientific Research & Publishing* (16 articles)
     - *Technology & Society* (16 articles)

2. **Search & Multi-Facet Filtering:**
   - In the search bar, type `quantum` and press Enter.
   - Observe the live results and notice how the URL synchronizes to `#/library?q=quantum`.
   - Explain to the grader: *This search automatically recorded a standardized search event in PostgreSQL `interaction_logs` with a unique `search_event_id` and captured all result doc IDs.*
   - Click a Category pill on the sidebar (e.g. *Physics*) and select a Tag (e.g. *Quantum Computing*). Note the multi-faceted filtering.

3. **Reading Detail & Engagement (`#/documents/:id`):**
   - Click one of the research article cards.
   - Point out that clicking from search sent a result click log event (`/api/v1/events/clicks`) linked to the original search event, followed by an idempotent view event (`/api/v1/documents/:id/views`).
   - Scroll through the article: observe the clean single-column reading typography, cover image with attribution, and sanitized Markdown rendering.

4. **Liking & Commenting with `@mentions`:**
   - Log in as Reader: click **Login** in the header (`reader@folio.test` / `FolioDemo2026!`).
   - Click the **Like** heart button: note the count increases and persists.
   - Scroll to the Discussion section:
     - Type a comment: `"Outstanding research overview! Paging @content_mgr for feedback on section 3."`
     - Click **Post Comment**: note that `@content_mgr` is automatically recognized and stored in `comment_mentions`.
   - Click the **Flag** icon next to the comment and submit a test report: *"Suspected off-topic speculation"*.

---

## Act 2: Content Authoring & Taxonomy (Content Manager — 2 mins)

1. **Switch Account & Access Admin Area:**
   - Log out, then log in as `content@folio.test` (`FolioDemo2026!`).
   - Click the **Admin** button in the header.
   - Point out that the admin sidebar only displays links authorized for `content_manager`: **Documents** and **Taxonomy**.

2. **Author New Research Document (`#/admin/documents/new`):**
   - Click **+ Create Document**.
   - Fill in Title: `"Graph Neural Networks for Molecular Discovery"`.
   - Select Category: *Computer Science*.
   - Fill in Summary and Body with Markdown text:
     ```markdown
     ## Abstract
     Graph neural networks (GNNs) provide expressive representations for molecular graphs.
     ```
   - Click the **Live Preview** toggle: observe the real-time sanitized preview alongside the textarea editor.
   - Click **Save as Draft**.

3. **Draft Privacy & Publishing Workflow:**
   - Open a secondary incognito window as a guest visitor at `#/library`. Search for `"Molecular Discovery"`.
   - Prove to the grader: *The draft does not appear in public search or catalog listings.*
   - Return to the Content Manager editor and click **Publish Document**.
   - Refresh the incognito window: the document is now instantly discoverable and readable.

4. **Taxonomy & Conflict Protection (`#/admin/taxonomy`):**
   - Navigate to **Taxonomy**.
   - Create a new Category: `"Nanotechnology"`.
   - Attempt to delete a category that currently contains published documents (e.g. *Computer Science*).
   - Observe the system behavior: The backend returns HTTP `409 Conflict`, and the UI displays a clear explanation that active documents prevent deletion.

---

## Act 3: Moderation & Spam Suspension (Moderator — 1.5 mins)

1. **Review Flagged Reports (`#/admin/reports`):**
   - Log in as `moderator@folio.test`.
   - Notice the sidebar opens directly to **Moderation** and **Flags & Reports**.
   - Click **Flags & Reports**: observe the report submitted earlier by the Reader.
   - Inspect the card: it shows the reporter username, reason, and full comment body context.
   - Click **Hide Comment**: this atomically resolves the report and sets the comment status to `hidden`.

2. **Spam Control & Commenting Suspension (`#/admin/comments`):**
   - Switch to the **Comments Moderation Queue**.
   - Filter by `Hidden` to view the newly hidden comment.
   - Click the **Suspend** button next to `reader`.
   - In the modal dialog, select **3 Days** and input the audit reason: *"Violated scientific discourse standards"*.
   - Click **Apply Suspension**.

3. **Enforcement Verification:**
   - Log back in as `reader@folio.test` and attempt to post a comment on any document.
   - Observe the instant HTTP `403 Forbidden` response displaying: *"Your commenting privileges have been temporarily suspended until [Date]."*.

---

## Act 4: Data & SEO Analytics (SEO Specialist — 1.5 mins)

1. **SEO Management & Google SERP Simulator (`#/admin/seo`):**
   - Log in as `seo@folio.test`.
   - Navigate to **SEO Metadata**.
   - Click **Edit SEO** on any document.
   - Demonstrate the **Google SERP Snippet Simulator**:
     - Edit Meta Title: notice character counter (`X / 60`) and live title preview update.
     - Edit Meta Description: notice character counter (`X / 160`) and live snippet update.
     - Add keywords: `"deep learning, graph theory, chemistry"`.
     - Click **Save SEO Metadata**.

2. **Library Analytics Dashboard (`#/admin/analytics`):**
   - Navigate to **Analytics**.
   - Point out the 4 primary metric cards: *Published Documents*, *Search Requests*, *Result Clicks*, and *Document Views*.
   - Filter by period: **Last 7 Days**, **Last 30 Days**, **Last 90 Days**.
   - Highlight the **Daily Activity Breakdown Table**: observe the zero-filled daily series generated by PostgreSQL.
   - Point to the **Top Search Queries** table (reflecting the queries executed during this demo) and **Top Read Documents** table.

---

## Act 5: Governance & Audit Trail (Super Administrator — 1.5 mins)

1. **User Management & Last Super Admin Invariant (`#/admin/users`):**
   - Log in as `admin@folio.test`.
   - Navigate to **Users & Staff**.
   - Locate the row for `admin` (`super_admin`).
   - Attempt to change `admin`'s role to `Member` or uncheck the `Active` toggle.
   - Observe the result: The backend triggers row-locked protection and returns HTTP `409 Conflict: Cannot demote or deactivate the last active super administrator`. The UI alerts the admin without breaking system state.

2. **Role & Permissions Matrix (`#/admin/roles`):**
   - Navigate to **Roles & Matrix**.
   - Demonstrate the dynamic capability matrix: permissions on the vertical axis, roles on the horizontal axis.
   - Explain: *Super Admin can dynamically grant or revoke specific capabilities (e.g. granting SEO specialists taxonomy write permissions) and persist them directly to the database.*
   - Point out that `super_admin` permissions are permanently locked to prevent accidental revocation.

3. **Immutable Audit Trail (`#/admin/audit`):**
   - Navigate to **Audit Trail**.
   - Show the grader the audit log table: all actions performed during this demo (`document.create`, `document.status_update`, `moderation.report_hide_comment`, `moderation.suspend_commenting`, `seo.update`) are recorded in chronological order.
   - Click **Inspect Payload** on a record: open the before/after JSON diff viewer to demonstrate transparency and security compliance.

4. **Global System Settings (`#/admin/settings`):**
   - Navigate to **Settings**.
   - Update repository title from `"Folio"` to `"Folio — Institute Archives"`.
   - Click **Save Settings**: observe the public header and browser title update instantly across the entire application.
