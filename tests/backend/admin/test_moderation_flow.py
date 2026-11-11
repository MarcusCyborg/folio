import pytest
from datetime import datetime, timezone, timedelta
from src.backend.models.comment import Comment, Report
from src.backend.models.document import Document
from src.backend.models.auth import User

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]

def test_moderation_atomic_resolution_and_no_resurrect(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    reader = db_session.query(User).filter(User.username == "reader").first()

    # 1. Create comment and report
    comment1 = Comment(
        document_id=doc.id,
        user_id=reader.id,
        body="Check out this shady cryptocurrency scheme http://spam.xyz",
        status="visible"
    )
    db_session.add(comment1)
    db_session.flush()

    report1 = Report(
        comment_id=comment1.id,
        reporter_id=reader.id,
        reason="spam",
        details="Spam link to crypto site",
        status="open"
    )
    db_session.add(report1)
    db_session.commit()

    csrf_mod = auth_login(client, "moderator@folio.test")

    # Verify report in admin reports list
    reports_res = client.get("/api/v1/admin/reports?status=open").json()
    assert any(r["id"] == report1.id for r in reports_res["items"])

    # 2. Atomic resolution: mark_spam -> report becomes resolved, comment becomes spam in same commit
    res_spam = client.patch(
        f"/api/v1/admin/reports/{report1.id}",
        headers={"X-CSRF-Token": csrf_mod},
        json={"action": "mark_spam", "resolution": "Confirmed spam URL"}
    )
    assert res_spam.status_code == 200
    assert res_spam.json()["status"] == "resolved"

    db_session.refresh(comment1)
    db_session.refresh(report1)
    assert report1.status == "resolved"
    assert comment1.status == "spam"

    # Public comments list for this document must NOT show spam comment
    pub_comments = client.get(f"/api/v1/documents/{doc.id}/comments").json()
    assert all(c["id"] != comment1.id for c in pub_comments["items"])

    # 3. Dismiss action on a report
    comment2 = Comment(document_id=doc.id, user_id=reader.id, body="Legitimate disagreement on methodology", status="visible")
    db_session.add(comment2)
    db_session.flush()
    report2 = Report(comment_id=comment2.id, reporter_id=reader.id, reason="abuse", details="I disagree with this", status="open")
    db_session.add(report2)
    db_session.commit()

    res_dismiss = client.patch(
        f"/api/v1/admin/reports/{report2.id}",
        headers={"X-CSRF-Token": csrf_mod},
        json={"action": "dismiss", "resolution": "No policy violation found"}
    )
    assert res_dismiss.status_code == 200
    assert res_dismiss.json()["status"] == "dismissed"

    db_session.refresh(comment2)
    assert comment2.status == "visible"

    # 4. Invariant: Cannot resurrect owner-deleted comment
    comment_del = Comment(document_id=doc.id, user_id=reader.id, body="Personal comment deleted by owner", status="deleted")
    db_session.add(comment_del)
    db_session.flush()

    # Moderator attempts to resurrect deleted comment -> 400 CANNOT_RESURRECT_DELETED_COMMENT
    res_resurrect = client.patch(
        f"/api/v1/admin/comments/{comment_del.id}/status",
        headers={"X-CSRF-Token": csrf_mod},
        json={"status": "visible"}
    )
    assert res_resurrect.status_code == 400
    assert res_resurrect.json()["error"]["code"] == "CANNOT_RESURRECT_DELETED_COMMENT"

    # 5. Commenting suspension
    suspension_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    suspend_res = client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf_mod},
        json={"suspended_until": suspension_time, "reason": "Repeated spam links posted"}
    )
    assert suspend_res.status_code == 200
    assert suspend_res.json()["commenting_suspended_until"] is not None

    # Blank reason is rejected
    bad_suspend = client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf_mod},
        json={"suspended_until": suspension_time, "reason": "   "}
    )
    assert bad_suspend.status_code == 422

    # Verify suspended user cannot comment on public documents
    csrf_reader = auth_login(client, "reader@folio.test")
    post_comment_res = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Trying to comment while suspended"}
    )
    assert post_comment_res.status_code == 403

    # Remove suspension
    auth_login(client, "moderator@folio.test")
    client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf_mod},
        json={"suspended_until": None, "reason": "Suspension lifted"}
    )


def test_r05_report_open_unique_migration_handles_equal_timestamps_and_concurrent_reports():
    """
    R05 / B08 REGRESSION (PostgreSQL):
    - Preflight dry-run & Alembic upgrade cleanly deduplicate open reports even when created_at timestamps are equal
      and >2 duplicates exist, preserving historical rows and recording an audit trail.
    - Partial unique index uq_reports_open_comment_reporter prevents concurrent duplicate open reports,
      returning HTTP 409 DUPLICATE_REPORT to the losing request while allowing new reports after resolution.
    """
    import importlib.util
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from tests.conftest import test_db_url
    from src.backend.core.exceptions import AppException
    from src.backend.services.library.engagement_service import report_comment
    from src.backend.models.auth import User
    from src.backend.models.comment import Comment, Report
    from src.backend.models.document import Document

    spec = importlib.util.spec_from_file_location(
        "migration_20261106_report_open_unique",
        "alembic/versions/20261106_report_open_unique.py",
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = create_engine(test_db_url, pool_size=10, max_overflow=5)
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    try:
        with SessionFactory() as db:
            doc = db.query(Document).filter(Document.status == "published").first()
            reader = db.query(User).filter(User.username == "reader").first()
            comment = Comment(
                document_id=doc.id,
                user_id=reader.id,
                body="R05 migration and concurrency test comment",
                status="visible",
            )
            db.add(comment)
            db.commit()
            comment_id = comment.id
            reporter_id = reader.id

        # 1. Drop partial index temporarily, insert historical closed report + 3 equal-timestamp open duplicates + 1 newer open duplicate
        with engine.begin() as conn:
            conn.execute(text("DROP INDEX IF EXISTS uq_reports_open_comment_reporter"))
            equal_ts = "2026-11-06 00:00:00+00"
            later_ts = "2026-11-06 00:05:00+00"
            conn.execute(
                text(
                    """
                    INSERT INTO reports (id, comment_id, reporter_id, reason, status, resolution, created_at)
                    VALUES
                      ('r05_hist_closed', :cid, :rid, 'spam', 'resolved', 'earlier_closed', '2026-11-05 12:00:00+00'),
                      ('r05_open_a', :cid, :rid, 'spam', 'open', NULL, :eq_ts),
                      ('r05_open_b', :cid, :rid, 'abuse', 'open', NULL, :eq_ts),
                      ('r05_open_c', :cid, :rid, 'other', 'open', NULL, :eq_ts),
                      ('r05_open_d', :cid, :rid, 'spam', 'open', NULL, :lt_ts)
                    """
                ),
                {"cid": comment_id, "rid": reporter_id, "eq_ts": equal_ts, "lt_ts": later_ts},
            )

            # Preflight dry-run check
            dry_plan = mig.inspect_duplicate_open_reports(conn)
            assert dry_plan["duplicate_rows_to_resolve"] == 3
            assert set(dry_plan["duplicate_ids"]) == {"r05_open_b", "r05_open_c", "r05_open_d"}

            # Execute actual Alembic migration upgrade()
            mig.op = Operations(MigrationContext.configure(conn))
            mig.upgrade()

            # Verify canonical earliest open report ('r05_open_a') kept, 3 duplicates resolved without deleting rows
            rows = conn.execute(
                text("SELECT id, status, resolution FROM reports WHERE comment_id = :cid ORDER BY id ASC"),
                {"cid": comment_id},
            ).fetchall()
            status_map = {r[0]: (r[1], r[2]) for r in rows}
            assert len(rows) == 5, "No historical report rows may be deleted"
            assert status_map["r05_hist_closed"] == ("resolved", "earlier_closed")
            assert status_map["r05_open_a"] == ("open", None)
            assert status_map["r05_open_b"] == ("resolved", "auto_merged_duplicate_open_report")
            assert status_map["r05_open_c"] == ("resolved", "auto_merged_duplicate_open_report")
            assert status_map["r05_open_d"] == ("resolved", "auto_merged_duplicate_open_report")

            # Close r05_open_a so user can test concurrent reporting on a clean open slot
            conn.execute(
                text("UPDATE reports SET status = 'dismissed', resolution = 'cleared' WHERE id = 'r05_open_a'")
            )

        # 2. Two concurrent PostgreSQL sessions submit open reports simultaneously
        barrier = threading.Barrier(2)

        def submit_concurrent_report(idx: int):
            with SessionFactory() as db:
                user_obj = db.query(User).filter(User.id == reporter_id).first()
                barrier.wait(timeout=10)
                try:
                    res = report_comment(db, comment_id, user_obj, reason="spam", details=f"concurrent-{idx}")
                    return ("created", res["id"])
                except AppException as exc:
                    return ("conflict", exc.status_code, exc.code)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit_concurrent_report, [1, 2]))

        created = [o for o in outcomes if o[0] == "created"]
        conflicts = [o for o in outcomes if o[0] == "conflict"]
        assert len(created) == 1, f"Expected exactly 1 created report, got {outcomes}"
        assert len(conflicts) == 1 and conflicts[0] == ("conflict", 409, "DUPLICATE_REPORT")

        with engine.connect() as conn:
            open_count = conn.execute(
                text("SELECT count(*) FROM reports WHERE comment_id = :cid AND reporter_id = :rid AND status = 'open'"),
                {"cid": comment_id, "rid": reporter_id},
            ).scalar()
            assert open_count == 1
    finally:
        # Clean up test comment & reports so shared session DB stays pristine
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_logs WHERE entity_id = '20261106_report_open_unique'"))
            conn.execute(text("DELETE FROM comments WHERE body = 'R05 migration and concurrency test comment'"))
        engine.dispose()
