import uuid
from datetime import datetime, timezone, timedelta, date
from src.backend.models.document import Document, DocumentTag, DocumentLike
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.comment import Comment, Report
from src.backend.models.auth import User
from src.backend.models.system import AppSetting
from src.backend.models.event import InteractionLog

def get_auth_client(client, email="reader@folio.test", password="FolioDemo2026!"):
    sess_res = client.get("/api/v1/auth/session")
    csrf = sess_res.json()["csrf_token"]
    login_res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf},
        json={"email": email, "password": password}
    )
    assert login_res.status_code == 200
    return login_res.json()["csrf_token"]

def test_public_settings(client):
    res = client.get("/api/v1/settings/public")
    assert res.status_code == 200
    data = res.json()
    assert "site_name" in data
    assert "registration_enabled" in data
    assert "comments_enabled" in data

def test_list_categories_and_tags(client):
    res_cats = client.get("/api/v1/categories")
    assert res_cats.status_code == 200
    cats = res_cats.json()["items"]
    assert len(cats) >= 6
    assert any(c["slug"] == "ai-machine-learning" for c in cats)

    res_tags = client.get("/api/v1/tags?page=1&page_size=10")
    assert res_tags.status_code == 200
    tags = res_tags.json()["items"]
    assert len(tags) == 10

def test_document_listing_and_search_logging(client, db_session):
    # Unfiltered browsing
    res = client.get("/api/v1/documents?page=1&page_size=10")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 100
    assert len(data["items"]) == 10
    assert data["search_event_id"] is None  # No search event when q is empty!

    # Search with keyword q
    res_search = client.get("/api/v1/documents?q=deep&page=1&page_size=5")
    assert res_search.status_code == 200
    s_data = res_search.json()
    assert s_data["query"] == "deep"
    assert s_data["search_event_id"] is not None  # Search event recorded!
    assert len(s_data["items"]) > 0

    # Ensure draft documents are never returned in public list
    draft_docs = db_session.query(Document).filter(Document.status == "draft").all()
    assert len(draft_docs) > 0
    draft_ids = {d.id for d in draft_docs}
    for item in data["items"]:
        assert item["id"] not in draft_ids

def test_document_detail_and_sanitization(client, db_session):
    # Find a published doc
    doc = db_session.query(Document).filter(Document.status == "published").first()
    assert doc is not None

    res = client.get(f"/api/v1/documents/{doc.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == doc.title
    assert "rendered_content" in data
    assert "<" in data["rendered_content"]  # HTML rendered
    assert "<script>" not in data["rendered_content"]  # Safe!

    # Draft doc should 404
    draft = db_session.query(Document).filter(Document.status == "draft").first()
    assert draft is not None
    res_draft = client.get(f"/api/v1/documents/{draft.id}")
    assert res_draft.status_code == 404

def test_legacy_wikipedia_edit_controls_are_cleaned_on_read(client, db_session):
    from src.backend.services.admin.content_service import admin_get_document

    doc = db_session.get(Document, "5968c38e-b185-5854-93dc-47b7843be819")
    raw_content = "## Background\n\n[edit]\n\nKeep the word edit in prose."
    doc.content = raw_content
    db_session.flush()

    response = client.get(f"/api/v1/documents/{doc.id}")
    assert response.status_code == 200
    for data in (response.json(), admin_get_document(db_session, doc.id)):
        assert data["content"] == "## Background\n\nKeep the word edit in prose."
        assert "[edit]" not in data["rendered_content"]
        assert "<h2>Background</h2>" in data["rendered_content"]
        assert "Keep the word edit in prose." in data["rendered_content"]
    db_session.refresh(doc)
    assert doc.content == raw_content  # Reading must not mutate stored revisions.


def test_view_event_idempotency(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    initial_views = doc.views_count
    nav_id = str(uuid.uuid4())

    sess_res = client.get("/api/v1/auth/session")
    csrf = sess_res.json()["csrf_token"]

    # First view call
    res1 = client.post(
        f"/api/v1/documents/{doc.id}/views",
        headers={"X-CSRF-Token": csrf},
        json={"navigation_id": nav_id}
    )
    assert res1.status_code == 200
    assert res1.json()["views_count"] == initial_views + 1

    # Retry same navigation_id -> should NOT increment views_count
    res2 = client.post(
        f"/api/v1/documents/{doc.id}/views",
        headers={"X-CSRF-Token": csrf},
        json={"navigation_id": nav_id}
    )
    assert res2.status_code == 200
    assert res2.json()["views_count"] == initial_views + 1

def test_like_unlike_idempotency(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    csrf = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")

    # Like
    res_like = client.put(f"/api/v1/documents/{doc.id}/like", headers={"X-CSRF-Token": csrf})
    assert res_like.status_code == 200
    assert res_like.json()["liked_by_me"] is True
    likes_after = res_like.json()["likes_count"]

    # Repeat Like -> idempotent
    res_like2 = client.put(f"/api/v1/documents/{doc.id}/like", headers={"X-CSRF-Token": csrf})
    assert res_like2.status_code == 200
    assert res_like2.json()["likes_count"] == likes_after

    # Detail shows liked_by_me = true
    res_detail = client.get(f"/api/v1/documents/{doc.id}")
    assert res_detail.json()["liked_by_me"] is True

    # Unlike
    res_unlike = client.delete(f"/api/v1/documents/{doc.id}/like", headers={"X-CSRF-Token": csrf})
    assert res_unlike.status_code == 200
    assert res_unlike.json()["liked_by_me"] is False
    assert res_unlike.json()["likes_count"] == likes_after - 1

def test_comments_crud_and_mentions(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    csrf_reader = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")

    # 1. Post comment with @mention
    body = "Great research review @admin and @moderator! Really interesting findings."
    post_res = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": body}
    )
    assert post_res.status_code == 201
    c_data = post_res.json()
    comment_id = c_data["id"]
    assert c_data["body"] == body
    assert c_data["can_edit"] is True
    assert c_data["can_delete"] is True
    assert len(c_data["mentions"]) == 2
    mention_usernames = {m["username"] for m in c_data["mentions"]}
    assert "admin" in mention_usernames
    assert "moderator" in mention_usernames

    # 2. Duplicate comment prevention (anti-spam)
    dup_res = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": body}
    )
    assert dup_res.status_code == 429

    # 3. Mention lookup
    lookup_res = client.get("/api/v1/users/mentions?q=adm")
    assert lookup_res.status_code == 200
    lookup_users = lookup_res.json()
    assert any(u["username"] == "admin" for u in lookup_users)
    assert "email" not in lookup_users[0]  # No email leakage

    # 4. Another user cannot edit/delete this comment
    csrf_mod = get_auth_client(client, "moderator@folio.test", "FolioDemo2026!")
    cross_edit = client.patch(
        f"/api/v1/comments/{comment_id}",
        headers={"X-CSRF-Token": csrf_mod},
        json={"body": "Hacked comment body"}
    )
    assert cross_edit.status_code == 403

    cross_del = client.delete(
        f"/api/v1/comments/{comment_id}",
        headers={"X-CSRF-Token": csrf_mod}
    )
    assert cross_del.status_code == 403

    # 5. Owner can edit
    csrf_reader = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")
    own_edit = client.patch(
        f"/api/v1/comments/{comment_id}",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Updated comment text @admin"}
    )
    assert own_edit.status_code == 200
    assert own_edit.json()["body"] == "Updated comment text @admin"

    # 6. Report comment
    csrf_mod = get_auth_client(client, "moderator@folio.test", "FolioDemo2026!")
    report_res = client.post(
        f"/api/v1/comments/{comment_id}/reports",
        headers={"X-CSRF-Token": csrf_mod},
        json={"reason": "spam", "details": "Suspicious promotion"}
    )
    assert report_res.status_code == 201

    # Duplicate open report returns 409
    dup_report = client.post(
        f"/api/v1/comments/{comment_id}/reports",
        headers={"X-CSRF-Token": csrf_mod},
        json={"reason": "spam"}
    )
    assert dup_report.status_code == 409

    # 7. Owner deletes comment
    csrf_reader = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")
    del_res = client.delete(f"/api/v1/comments/{comment_id}", headers={"X-CSRF-Token": csrf_reader})
    assert del_res.status_code == 204

    # Deleted comment no longer in public list
    list_res = client.get(f"/api/v1/documents/{doc.id}/comments")
    assert all(c["id"] != comment_id for c in list_res.json()["items"])

def test_search_and_click_event_linking(client):
    # 1. Perform search to get search_event_id
    res_search = client.get("/api/v1/documents?q=intelligence&page=1&page_size=5")
    assert res_search.status_code == 200
    s_data = res_search.json()
    search_event_id = s_data["search_event_id"]
    assert search_event_id is not None
    assert len(s_data["items"]) > 0
    clicked_doc = s_data["items"][0]

    # Get CSRF
    sess_res = client.get("/api/v1/auth/session")
    csrf = sess_res.json()["csrf_token"]

    req_key = str(uuid.uuid4())

    # 2. Record click
    res_click = client.post(
        "/api/v1/events/clicks",
        headers={"X-CSRF-Token": csrf},
        json={
            "search_event_id": search_event_id,
            "document_id": clicked_doc["id"],
            "request_key": req_key
        }
    )
    assert res_click.status_code == 201
    click_id = res_click.json()["id"]

    # 3. Retry with same request_key -> returns same click_id (idempotent)
    res_click_retry = client.post(
        "/api/v1/events/clicks",
        headers={"X-CSRF-Token": csrf},
        json={
            "search_event_id": search_event_id,
            "document_id": clicked_doc["id"],
            "request_key": req_key
        }
    )
    assert res_click_retry.status_code == 201
    assert res_click_retry.json()["id"] == click_id

    # 4. Attempt to click a doc NOT in search results -> 422
    fake_doc_id = str(uuid.uuid4())
    res_invalid_click = client.post(
        "/api/v1/events/clicks",
        headers={"X-CSRF-Token": csrf},
        json={
            "search_event_id": search_event_id,
            "document_id": fake_doc_id,
            "request_key": str(uuid.uuid4())
        }
    )
    assert res_invalid_click.status_code in (404, 422)

def test_search_combinations_and_edge_cases(client, db_session):
    # 1. Multi-tag AND
    doc = db_session.query(Document).filter(Document.status == "published").first()
    assert doc is not None
    tags = [dt.tag for dt in doc.document_tags]
    if len(tags) >= 2:
        t_ids = f"{tags[0].id},{tags[1].id}"
        res = client.get(f"/api/v1/documents?tag_ids={t_ids}")
        assert res.status_code == 200
        for item in res.json()["items"]:
            item_tag_ids = {t["id"] for t in item["tags"]}
            assert tags[0].id in item_tag_ids
            assert tags[1].id in item_tag_ids

    # 2. Date filters
    today = date.today()
    res_date = client.get(f"/api/v1/documents?date_from=2020-01-01&date_to={today.isoformat()}")
    assert res_date.status_code == 200

    # 2b. Extreme boundary date_to (e.g. 9999-12-31) must not raise OverflowError
    res_max_date = client.get("/api/v1/documents?date_from=2020-01-01&date_to=9999-12-31")
    assert res_max_date.status_code == 200

    # 3. Invalid date range (date_from > date_to) -> 422
    res_invalid_date = client.get("/api/v1/documents?date_from=2026-12-31&date_to=2026-01-01")
    assert res_invalid_date.status_code == 422

    # 4. Page boundaries: past total_pages returns items: []
    res_boundary = client.get("/api/v1/documents?page=9999&page_size=20")
    assert res_boundary.status_code == 200
    assert res_boundary.json()["items"] == []
    assert res_boundary.json()["page"] == 9999

    # 5. Empty and whitespace-only q
    res_empty_q = client.get("/api/v1/documents?q=   ")
    assert res_empty_q.status_code == 200
    assert res_empty_q.json()["query"] is None
    assert res_empty_q.json()["search_event_id"] is None

    # 6. SQL wildcard escaping (% and _)
    res_wildcard_percent = client.get("/api/v1/documents?q=%")
    assert res_wildcard_percent.status_code == 200
    assert res_wildcard_percent.json()["total"] < 100

    res_wildcard_underscore = client.get("/api/v1/documents?q=_")
    assert res_wildcard_underscore.status_code == 200
    assert res_wildcard_underscore.json()["total"] < 100

    # 7. Stable sort
    for s in ["newest", "oldest", "title"]:
        res_sort = client.get(f"/api/v1/documents?sort={s}&page=1&page_size=5")
        assert res_sort.status_code == 200
        assert len(res_sort.json()["items"]) > 0

def test_draft_and_deleted_document_isolation(client, db_session):
    cat = db_session.query(Category).first()
    user = db_session.query(User).filter(User.username == "admin").first()

    deleted_doc = Document(
        title="Deleted Doc For Isolation",
        content="Content of deleted doc",
        summary="Summary of deleted doc",
        author="Wikipedia contributors",
        category_id=cat.id,
        created_by=user.id,
        status="published",
        deleted_at=datetime.now(timezone.utc),
    )
    draft_doc = Document(
        title="Draft Doc For Isolation",
        content="Content of draft doc",
        summary="Summary of draft doc",
        author="Wikipedia contributors",
        category_id=cat.id,
        created_by=user.id,
        status="draft",
        deleted_at=None,
    )
    db_session.add_all([deleted_doc, draft_doc])
    db_session.commit()

    csrf = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")

    for doc in [deleted_doc, draft_doc]:
        # 1. Detail returns 404
        assert client.get(f"/api/v1/documents/{doc.id}").status_code == 404

        # 2. Comments list returns 404
        assert client.get(f"/api/v1/documents/{doc.id}/comments").status_code == 404

        # 3. Post comment returns 404
        res_c = client.post(
            f"/api/v1/documents/{doc.id}/comments",
            headers={"X-CSRF-Token": csrf},
            json={"body": "Hello on unpublished"}
        )
        assert res_c.status_code == 404

        # 4. Like returns 404
        res_l = client.put(f"/api/v1/documents/{doc.id}/like", headers={"X-CSRF-Token": csrf})
        assert res_l.status_code == 404

        # 5. Unlike returns 404
        res_ul = client.delete(f"/api/v1/documents/{doc.id}/like", headers={"X-CSRF-Token": csrf})
        assert res_ul.status_code == 404

        # 6. View returns 404
        res_v = client.post(
            f"/api/v1/documents/{doc.id}/views",
            headers={"X-CSRF-Token": csrf},
            json={"navigation_id": str(uuid.uuid4())}
        )
        assert res_v.status_code == 404

def test_hidden_spam_comments_not_in_public_counts(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    user = db_session.query(User).filter(User.username == "reader").first()

    # Create 1 visible, 1 hidden, 1 spam, 1 deleted comment
    c_visible = Comment(document_id=doc.id, user_id=user.id, body="Visible comment 1", status="visible")
    c_hidden = Comment(document_id=doc.id, user_id=user.id, body="Hidden comment 2", status="hidden")
    c_spam = Comment(document_id=doc.id, user_id=user.id, body="Spam comment 3", status="spam")
    c_deleted = Comment(document_id=doc.id, user_id=user.id, body="Deleted comment 4", status="deleted")
    db_session.add_all([c_visible, c_hidden, c_spam, c_deleted])
    db_session.commit()

    # Detail comments_count only counts visible
    res_detail = client.get(f"/api/v1/documents/{doc.id}")
    assert res_detail.status_code == 200

    # Comments list only returns visible
    res_comments = client.get(f"/api/v1/documents/{doc.id}/comments")
    assert res_comments.status_code == 200
    returned_ids = {c["id"] for c in res_comments.json()["items"]}
    assert c_visible.id in returned_ids
    assert c_hidden.id not in returned_ids
    assert c_spam.id not in returned_ids
    assert c_deleted.id not in returned_ids
    assert res_detail.json()["comments_count"] == len(returned_ids)

def test_comment_moderation_and_suspension_rules(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    reader_user = db_session.query(User).filter(User.username == "reader").first()
    csrf_reader = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")

    # 1. Reader creates comment
    res = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Comment for moderation test"}
    )
    assert res.status_code == 201
    c_id = res.json()["id"]

    # 2. Moderator hides comment
    comment_row = db_session.query(Comment).filter(Comment.id == c_id).first()
    comment_row.status = "hidden"
    db_session.commit()

    # 3. Owner attempts to edit hidden comment -> 403 CANNOT_EDIT_MODERATED_COMMENT
    edit_res = client.patch(
        f"/api/v1/comments/{c_id}",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Owner trying to edit hidden comment"}
    )
    assert edit_res.status_code == 403
    assert edit_res.json()["error"]["code"] == "CANNOT_EDIT_MODERATED_COMMENT"

    # 4. Moderator marks comment as spam
    comment_row.status = "spam"
    db_session.commit()

    # Owner attempts to edit spam comment -> 403 CANNOT_EDIT_MODERATED_COMMENT
    edit_spam_res = client.patch(
        f"/api/v1/comments/{c_id}",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Owner trying to edit spam comment"}
    )
    assert edit_spam_res.status_code == 403
    assert edit_spam_res.json()["error"]["code"] == "CANNOT_EDIT_MODERATED_COMMENT"

    # Restore comment to visible
    comment_row.status = "visible"
    db_session.commit()

    # 5. Suspend reader's commenting privilege
    reader_user.commenting_suspended_until = datetime.now(timezone.utc) + timedelta(days=2)
    db_session.commit()

    # Suspended reader cannot post new comments
    sus_post = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "I am suspended"}
    )
    assert sus_post.status_code == 403
    assert sus_post.json()["error"]["code"] == "COMMENTING_SUSPENDED"

    # Suspended reader cannot edit comment
    sus_edit = client.patch(
        f"/api/v1/comments/{c_id}",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Trying to edit while suspended"}
    )
    assert sus_edit.status_code == 403
    assert sus_edit.json()["error"]["code"] == "COMMENTING_SUSPENDED"

    # Suspended reader CAN delete their own comment
    sus_del = client.delete(f"/api/v1/comments/{c_id}", headers={"X-CSRF-Token": csrf_reader})
    assert sus_del.status_code == 204

    # Clear suspension
    reader_user.commenting_suspended_until = None
    db_session.commit()

    # 6. Disable global comments setting
    setting = db_session.query(AppSetting).filter(AppSetting.key == "comments_enabled").first()
    if not setting:
        setting = AppSetting(key="comments_enabled", value=False)
        db_session.add(setting)
    else:
        setting.value = False
    db_session.commit()

    # Attempt to post comment while disabled -> 403 COMMENTS_DISABLED
    dis_post = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Posting when comments disabled"}
    )
    assert dis_post.status_code == 403
    assert dis_post.json()["error"]["code"] == "COMMENTS_DISABLED"

    # Reset setting
    setting.value = True
    db_session.commit()

def test_anti_spam_rate_limit(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    reader = db_session.query(User).filter(User.username == "reader").first()
    # Reset recent comments for reader to ensure a clean 60s burst window
    db_session.query(Comment).filter(Comment.user_id == reader.id).delete()
    db_session.commit()

    csrf = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")

    # Post 5 distinct comments rapidly
    for i in range(5):
        res = client.post(
            f"/api/v1/documents/{doc.id}/comments",
            headers={"X-CSRF-Token": csrf},
            json={"body": f"Rapid distinct comment {i} {uuid.uuid4()}"}
        )
        assert res.status_code == 201

    # 6th comment exceeds burst rate limit -> 429 RATE_LIMITED
    res_6th = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf},
        json={"body": f"Rapid 6th comment {uuid.uuid4()}"}
    )
    assert res_6th.status_code == 429
    assert res_6th.json()["error"]["code"] == "RATE_LIMITED"

def test_guest_permissions_and_actor_mismatch(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()

    # 1. Guest can read settings, categories, tags, documents, detail, comments
    assert client.get("/api/v1/settings/public").status_code == 200
    assert client.get("/api/v1/categories").status_code == 200
    assert client.get("/api/v1/tags").status_code == 200
    assert client.get("/api/v1/documents").status_code == 200
    assert client.get(f"/api/v1/documents/{doc.id}").status_code == 200
    assert client.get(f"/api/v1/documents/{doc.id}/comments").status_code == 200

    # Get guest session and CSRF
    sess_res = client.get("/api/v1/auth/session")
    guest_csrf = sess_res.json()["csrf_token"]

    # 2. Guest CANNOT like/unlike
    assert client.put(f"/api/v1/documents/{doc.id}/like", headers={"X-CSRF-Token": guest_csrf}).status_code == 401
    assert client.delete(f"/api/v1/documents/{doc.id}/like", headers={"X-CSRF-Token": guest_csrf}).status_code == 401

    # 3. Guest CANNOT post comment
    assert client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": guest_csrf},
        json={"body": "Guest trying to comment"}
    ).status_code == 401

    # 4. Guest CANNOT report
    c = db_session.query(Comment).filter(Comment.status == "visible").first()
    if not c:
        admin_u = db_session.query(User).filter(User.username == "admin").first()
        c = Comment(document_id=doc.id, user_id=admin_u.id, body="Sample comment", status="visible")
        db_session.add(c)
        db_session.commit()
    assert client.post(
        f"/api/v1/comments/{c.id}/reports",
        headers={"X-CSRF-Token": guest_csrf},
        json={"reason": "spam"}
    ).status_code == 401

    # 5. Guest CANNOT lookup mentions
    assert client.get("/api/v1/users/mentions?q=adm").status_code == 401

    # 6. Guest CAN log views
    res_view = client.post(
        f"/api/v1/documents/{doc.id}/views",
        headers={"X-CSRF-Token": guest_csrf},
        json={"navigation_id": str(uuid.uuid4())}
    )
    assert res_view.status_code == 200

    # 7. Search and click actor mismatch check:
    # Actor 1 searches
    res_s = client.get("/api/v1/documents?q=deep&page=1&page_size=5")
    s_id = res_s.json()["search_event_id"]
    doc_id = res_s.json()["items"][0]["id"]

    # In a separate client session (Actor 2):
    from fastapi.testclient import TestClient
    from src.backend.main import app
    from src.backend.core.database import get_db

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="http://testserver") as client2:
        sess2 = client2.get("/api/v1/auth/session")
        csrf2 = sess2.json()["csrf_token"]
        res_mismatch = client2.post(
            "/api/v1/events/clicks",
            headers={"X-CSRF-Token": csrf2},
            json={
                "search_event_id": s_id,
                "document_id": doc_id,
                "request_key": str(uuid.uuid4())
            }
        )
        assert res_mismatch.status_code == 403
        assert res_mismatch.json()["error"]["code"] == "ACTOR_MISMATCH"

def test_markdown_sanitization_and_malformed_inputs(client, db_session):
    cat = db_session.query(Category).first()
    user = db_session.query(User).filter(User.username == "admin").first()

    malicious_md = (
        "# Heading\n"
        "<script>alert('xss')</script>\n"
        "<img src=x onerror=alert('img-xss')>\n"
        "<iframe src=\"https://evil.com\"></iframe>\n"
        "[Click Evil](javascript:alert('link-xss'))\n"
        "<a href=\"https://good.com\" onclick=\"steal()\">Good Link</a>\n"
        "<style>body { display: none; }</style>\n"
    )

    xss_doc = Document(
        title="XSS Test Document",
        content=malicious_md,
        summary="Summary with safe text",
        author="Wikipedia contributors",
        category_id=cat.id,
        created_by=user.id,
        status="published",
        deleted_at=None,
    )
    db_session.add(xss_doc)
    db_session.commit()

    # Detail request
    res = client.get(f"/api/v1/documents/{xss_doc.id}")
    assert res.status_code == 200
    rendered = res.json()["rendered_content"]
    assert "<script>" not in rendered
    assert "onerror=" not in rendered
    assert "<iframe>" not in rendered
    assert "javascript:" not in rendered
    assert "onclick=" not in rendered
    assert "<style>" not in rendered
    assert "https://good.com" in rendered

    # Malformed inputs
    # 1. Query too long (>200) -> 422
    assert client.get(f"/api/v1/documents?q={'a'*201}").status_code == 422

    # 2. Invalid sort -> 422
    assert client.get("/api/v1/documents?sort=invalid_sort").status_code == 422

    # 3. Invalid date -> 422
    assert client.get("/api/v1/documents?date_from=not-a-date").status_code == 422

    # 4. Invalid report reason (>50 chars or empty) -> 422
    csrf = get_auth_client(client, "reader@folio.test", "FolioDemo2026!")
    c = db_session.query(Comment).filter(Comment.status == "visible").first()
    if not c:
        c = Comment(document_id=xss_doc.id, user_id=user.id, body="Sample comment for report", status="visible")
        db_session.add(c)
        db_session.commit()
    assert client.post(
        f"/api/v1/comments/{c.id}/reports",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "a" * 51}
    ).status_code == 422

    # 5. Empty comment body -> 422
    assert client.post(
        f"/api/v1/documents/{xss_doc.id}/comments",
        headers={"X-CSRF-Token": csrf},
        json={"body": "   "}
    ).status_code == 422

    # 6. Extra fields forbidden -> 422
    assert client.post(
        f"/api/v1/comments/{c.id}/reports",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "spam", "unauthorized_extra": "value"}
    ).status_code == 422
