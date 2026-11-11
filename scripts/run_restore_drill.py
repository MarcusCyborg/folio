#!/usr/bin/env python3
"""
Folio Disaster Recovery Restore Drill Runner (R01 / OPS-04).

Executes an isolated, non-destructive end-to-end backup & restore drill:
1. Requires explicit --admin-url and --source-db-url (never falls back to ambient production .env or hardcoded credentials).
2. Provisions a brand-new uniquely named target database (validated against protected DB names).
3. Uses isolated backup, index, and media directories so production files are never touched.
4. Captures a comprehensive pre-backup state snapshot (counts, relation digests, content digests, constraints).
5. Executes perform_backup() and perform_restore() (with Alembic upgrade + index rebuild + smoke test).
6. Verifies 100% parity between source and restored target across all entities, digests, and DB constraints.
7. Drops the drill-created target database on cleanup unless --keep-target-db is specified.
"""

import os
import re
import sys
import uuid
import json
import hashlib
import argparse
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from scripts.ops.backup import perform_backup, redact_db_url, sanitize_diagnostic_text
from scripts.ops.restore import perform_restore
from src.backend.core.test_db_guard import PROTECTED_DB_NAMES, VALID_IDENTIFIER_REGEX


class RestoreDrillError(RuntimeError):
    """Raised when restore drill safety guard or verification assertion fails."""


def _validate_drill_db_name(db_name: str) -> str:
    if not db_name or not VALID_IDENTIFIER_REGEX.match(db_name):
        raise RestoreDrillError(f"Invalid target database identifier: '{db_name}'")
    lowered = db_name.lower()
    if lowered in PROTECTED_DB_NAMES or not lowered.startswith("folio_restore_drill_"):
        raise RestoreDrillError(
            f"Refusing to use target database '{db_name}'. "
            "Drill target database name must start with 'folio_restore_drill_' and never match a protected database."
        )
    return db_name


def _digest_rows(rows) -> str:
    h = hashlib.sha256()
    for row in rows:
        serialized = json.dumps([str(v) if v is not None else None for v in row], ensure_ascii=False)
        h.update(serialized.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def capture_database_snapshot(db_url: str) -> Dict[str, Any]:
    """Captures table counts, deterministic content/relation digests, and schema constraints."""
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            counts = {
                "documents_total": int(conn.execute(text("SELECT count(*) FROM documents")).scalar() or 0),
                "documents_active": int(conn.execute(text("SELECT count(*) FROM documents WHERE deleted_at IS NULL")).scalar() or 0),
                "documents_published": int(conn.execute(text("SELECT count(*) FROM documents WHERE status = 'published' AND deleted_at IS NULL")).scalar() or 0),
                "categories": int(conn.execute(text("SELECT count(*) FROM categories")).scalar() or 0),
                "tags": int(conn.execute(text("SELECT count(*) FROM tags")).scalar() or 0),
                "document_tags": int(conn.execute(text("SELECT count(*) FROM document_tags")).scalar() or 0),
                "users": int(conn.execute(text("SELECT count(*) FROM users")).scalar() or 0),
                "roles": int(conn.execute(text("SELECT count(*) FROM roles")).scalar() or 0),
                "role_permissions": int(conn.execute(text("SELECT count(*) FROM role_permissions")).scalar() or 0),
                "documents_with_seo": int(
                    conn.execute(
                        text("SELECT count(*) FROM documents WHERE seo_title IS NOT NULL OR seo_description IS NOT NULL")
                    ).scalar()
                    or 0
                ),
                "comments": int(conn.execute(text("SELECT count(*) FROM comments")).scalar() or 0),
                "reports": int(conn.execute(text("SELECT count(*) FROM reports")).scalar() or 0),
                "document_likes": int(conn.execute(text("SELECT count(*) FROM document_likes")).scalar() or 0),
                "interaction_logs": int(conn.execute(text("SELECT count(*) FROM interaction_logs")).scalar() or 0),
                "audit_logs": int(conn.execute(text("SELECT count(*) FROM audit_logs")).scalar() or 0),
            }

            digests = {
                "documents": _digest_rows(
                    conn.execute(
                        text(
                            "SELECT id, title, status, content, source_url, source_license, deleted_at "
                            "FROM documents ORDER BY id ASC"
                        )
                    ).fetchall()
                ),
                "document_tags": _digest_rows(
                    conn.execute(
                        text("SELECT document_id, tag_id FROM document_tags ORDER BY document_id ASC, tag_id ASC")
                    ).fetchall()
                ),
                "users": _digest_rows(
                    conn.execute(
                        text("SELECT id, email, username, role_key, is_active FROM users ORDER BY id ASC")
                    ).fetchall()
                ),
                "document_seo": _digest_rows(
                    conn.execute(
                        text("SELECT id, seo_title, seo_description, cover_image_alt FROM documents ORDER BY id ASC")
                    ).fetchall()
                ),
                "comments": _digest_rows(
                    conn.execute(
                        text("SELECT id, document_id, user_id, body, status FROM comments ORDER BY id ASC")
                    ).fetchall()
                ),
                "reports": _digest_rows(
                    conn.execute(
                        text("SELECT id, comment_id, reporter_id, status FROM reports ORDER BY id ASC")
                    ).fetchall()
                ),
            }

            indexes = {
                row[0]
                for row in conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                ).fetchall()
            }
            fk_count = int(
                conn.execute(
                    text("SELECT count(*) FROM pg_constraint WHERE contype = 'f'")
                ).scalar()
                or 0
            )
            unique_count = int(
                conn.execute(
                    text("SELECT count(*) FROM pg_constraint WHERE contype = 'u'")
                ).scalar()
                or 0
            )

            return {
                "counts": counts,
                "digests": digests,
                "constraints": {
                    "foreign_keys": fk_count,
                    "unique_constraints": unique_count,
                    "has_open_report_partial_unique_index": "uq_reports_open_comment_reporter" in indexes,
                },
            }
    finally:
        engine.dispose()


def run_drill(
    admin_url: str,
    source_db_url: str,
    target_db_name: Optional[str] = None,
    work_dir: Optional[Path] = None,
    keep_target_db: bool = False,
    drop_owned_target_db: bool = False,
    source_index_dir: Optional[Path] = None,
    source_media_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Runs a full disaster recovery backup + restore + parity verification drill.
    Raises RestoreDrillError on any safety violation or integrity mismatch.
    """
    if not admin_url or not source_db_url:
        raise RestoreDrillError("Both admin_url and source_db_url are required.")

    parsed_admin = make_url(admin_url)
    parsed_source = make_url(source_db_url)
    if (parsed_source.database or "").lower() in {"postgres", "template0", "template1"}:
        raise RestoreDrillError(f"Invalid source database name: {parsed_source.database}")

    if target_db_name:
        drill_db_name = _validate_drill_db_name(target_db_name)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        drill_db_name = _validate_drill_db_name(f"folio_restore_drill_{ts}_{uuid.uuid4().hex[:6]}")

    if drill_db_name == parsed_source.database:
        raise RestoreDrillError("Target drill database must never equal source database.")

    target_drill_url = parsed_admin.set(database=drill_db_name).render_as_string(hide_password=False)
    created_target_db = False

    temp_work_ctx = None
    if work_dir is None:
        temp_work_ctx = tempfile.TemporaryDirectory(prefix="folio_dr_drill_")
        base_work_dir = Path(temp_work_ctx.name)
    else:
        base_work_dir = Path(work_dir)
        base_work_dir.mkdir(parents=True, exist_ok=True)

    backup_out_dir = base_work_dir / "backups"
    restored_index_dir = base_work_dir / "restored_index"
    restored_media_dir = base_work_dir / "restored_media"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        # Step 1: Capture pre-backup snapshot from source database
        before_snapshot = capture_database_snapshot(source_db_url)

        # Step 2: Provision brand-new isolated drill target database
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": drill_db_name},
            ).scalar()
            if exists:
                if not drop_owned_target_db:
                    raise RestoreDrillError(
                        f"Target drill database '{drill_db_name}' already exists; pass --drop-owned-target-db to recreate."
                    )
                conn.execute(text(f'DROP DATABASE "{drill_db_name}" WITH (FORCE)'))

            owner_clause = f' OWNER "{parsed_admin.username}"' if parsed_admin.username else ""
            conn.execute(text(f'CREATE DATABASE "{drill_db_name}"{owner_clause}'))
            created_target_db = True

        # Step 3: Execute backup
        backup_report = perform_backup(
            output_dir=backup_out_dir,
            db_url=source_db_url,
            label="dr_drill",
            include_vector=False,
            index_storage_dir=source_index_dir,
            media_dir=source_media_dir,
        )

        # Step 4: Execute restore into newly created drill DB
        restore_report = perform_restore(
            archive_path=Path(backup_report["archive_path"]),
            target_db_url=target_drill_url,
            rebuild_index=True,
            skip_migrations=False,
            skip_smoke_test=False,
            index_storage_dir=restored_index_dir,
            media_dir=restored_media_dir,
        )

        # Step 5: Capture post-restore snapshot & verify full parity
        after_snapshot = capture_database_snapshot(target_drill_url)

        mismatches = []
        for k, v in before_snapshot["counts"].items():
            if after_snapshot["counts"].get(k) != v:
                mismatches.append(f"Count mismatch for {k}: before={v}, after={after_snapshot['counts'].get(k)}")
        for k, v in before_snapshot["digests"].items():
            if after_snapshot["digests"].get(k) != v:
                mismatches.append(f"Digest mismatch for {k}: before={v}, after={after_snapshot['digests'].get(k)}")
        if after_snapshot["constraints"] != before_snapshot["constraints"]:
            mismatches.append(
                f"Constraint mismatch: before={before_snapshot['constraints']}, after={after_snapshot['constraints']}"
            )
        if not after_snapshot["constraints"]["has_open_report_partial_unique_index"]:
            mismatches.append("Missing partial unique index uq_reports_open_comment_reporter after restore.")

        if mismatches:
            raise RestoreDrillError("Post-restore integrity verification failed:\n  - " + "\n  - ".join(mismatches))

        return {
            "status": "passed",
            "source_db": redact_db_url(source_db_url),
            "target_db": redact_db_url(target_drill_url),
            "backup_id": backup_report["backup_id"],
            "archive_sha256": backup_report["archive_sha256"],
            "verified_counts": after_snapshot["counts"],
            "verified_digests": after_snapshot["digests"],
            "verified_constraints": after_snapshot["constraints"],
            "index_recovery": restore_report["index_recovery"],
            "smoke_test": restore_report["smoke_test"],
        }

    finally:
        if created_target_db and not keep_target_db:
            try:
                with admin_engine.connect() as conn:
                    conn.execute(text(f'DROP DATABASE IF EXISTS "{drill_db_name}" WITH (FORCE)'))
            except Exception:
                pass
        admin_engine.dispose()
        if temp_work_ctx is not None:
            temp_work_ctx.cleanup()


def main():
    parser = argparse.ArgumentParser(description="Folio Disaster Recovery Restore Drill Runner")
    parser.add_argument(
        "--admin-url",
        type=str,
        required=True,
        help="PostgreSQL administrative connection URL (connected to 'postgres' database) for creating isolated drill DB",
    )
    parser.add_argument(
        "--source-db-url",
        type=str,
        required=True,
        help="PostgreSQL source database URL to back up",
    )
    parser.add_argument(
        "--target-db-name",
        type=str,
        default=None,
        help="Optional explicit target drill database name (must start with 'folio_restore_drill_')",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Optional isolated working directory for drill artifacts (defaults to temporary directory)",
    )
    parser.add_argument(
        "--keep-target-db",
        action="store_true",
        help="Keep the created drill target database after completion instead of dropping it",
    )
    parser.add_argument(
        "--drop-owned-target-db",
        action="store_true",
        help="Drop target drill database first if it already exists (only allowed for folio_restore_drill_* names)",
    )
    args = parser.parse_args()

    try:
        report = run_drill(
            admin_url=args.admin_url,
            source_db_url=args.source_db_url,
            target_db_name=args.target_db_name,
            work_dir=args.work_dir,
            keep_target_db=args.keep_target_db,
            drop_owned_target_db=args.drop_owned_target_db,
        )
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        safe_err = sanitize_diagnostic_text(str(exc), args.source_db_url)
        safe_err = sanitize_diagnostic_text(safe_err, args.admin_url)
        print(json.dumps({"status": "failed", "error": safe_err}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
