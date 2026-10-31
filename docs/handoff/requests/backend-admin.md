# Backend Admin Shared File Requests

- **Partial Updates Schemas (`src/backend/schemas/admin.py`)**:
  - Provided `DocumentUpdate`, `CategoryUpdate`, and `TagUpdate` to support partial PATCH operations without requiring clients to re-send entire resource bodies.
- **Strict Allowlist Configuration (`extra="forbid"`)**:
  - Applied `model_config = ConfigDict(extra="forbid")` to all admin input schemas (`DocumentWrite`, `DocumentUpdate`, `CategoryWrite`, `CategoryUpdate`, `TagWrite`, `TagUpdate`, `DocumentStatusUpdate`, `SEOMetadataUpdate`, `UserAdminUpdate`, `RolePermissionsUpdate`, `CommentStatusUpdate`, `ReportResolveRequest`, `SuspendCommentingRequest`, `AppSettingsUpdate`). This strictly prevents mass-assignment vulnerabilities (e.g., forging `status`, `author_id`, `created_by`, `role_key`, or passwords).
- **No Shared Infrastructure Changes**:
  - No changes required to SQLAlchemy models, Alembic migrations, `main.py`, `core`, `auth`, or frontend files. All admin operations integrate cleanly with the existing frozen contracts.
