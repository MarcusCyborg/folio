"""Independent review probes; failures expose gaps in existing acceptance tests."""
from unittest.mock import patch

import pytest

from src.backend.models.document import Document
from src.backend.search.engine import SearchEngine
from src.backend.search.index import InvertedIndex
from src.backend.search.semantic import SemanticAdapter, SemanticCandidateHit
from src.backend.search_index.manager import GenerationManager


def test_review_disk_update_visible_to_existing_reader(tmp_path):
    index = InvertedIndex(generation_id="review-cache")
    index.upsert_document("first", text="neural", title="First")
    index.save(tmp_path)
    engine = SearchEngine()
    assert engine.get_or_load_index(index.generation_id, tmp_path).total_docs == 1
    index.upsert_document("second", text="neural", title="Second")
    index.save(tmp_path)
    assert engine.get_or_load_index(index.generation_id, tmp_path).total_docs == 2


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_review_dense_candidates_obey_category_filter(client, db_session, mode):
    docs = db_session.query(Document).filter(Document.status == "published").all()
    target = docs[0]
    other = next(d for d in docs if d.category_id != target.category_id)
    GenerationManager.build_new_generation(db_session, force=True)
    hit = SemanticCandidateHit(other.id, 0.99, 1, 0.01, 1)
    with patch.object(SemanticAdapter, "query", return_value=([hit], None)):
        response = client.get("/api/v1/search", params={
            "q": "neural", "mode": mode, "category_id": target.category_id,
        })
    assert response.status_code == 200, response.text
    assert other.id not in [item["id"] for item in response.json()["items"]]


def test_review_fallback_declaration_survives_next_page(client, db_session):
    GenerationManager.build_new_generation(db_session, force=True)
    with patch.object(SemanticAdapter, "query", return_value=([], "Vector offline")):
        first = client.get("/api/v1/search", params={
            "q": "neural", "mode": "semantic", "page_size": 1,
        })
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["engine_used"] == "fallback_bm25"
        assert body["has_more"]
        second = client.get("/api/v1/search", params={
            "q": "neural", "mode": "semantic", "page_size": 1, "page": 2,
            "search_context_token": body["search_context_token"],
        })
    assert second.status_code == 200, second.text
    assert second.json()["engine_used"] == "fallback_bm25"
    assert second.json()["is_degraded"] is True


@pytest.mark.parametrize("preloaded_tags", [False, True])
def test_review_tag_edit_job_matches_committed_document(db_session, preloaded_tags):
    from src.backend.models.taxonomy import Tag
    from src.backend.models.auth import User
    from src.backend.models.search_index import IndexJob
    from src.backend.services.admin.content_service import admin_update_document
    from src.backend.search_index.hashing import compute_doc_instance_hash

    doc = db_session.query(Document).filter(Document.status == "published").first()
    old_tags = {dt.tag_id for dt in doc.document_tags}
    new_tag = next(t for t in db_session.query(Tag).all() if t.id not in old_tags)
    user = db_session.query(User).first()
    if not preloaded_tags:
        db_session.expire(doc, ["document_tags"])
    admin_update_document(db_session, doc.id, {"tag_ids": [new_tag.id]}, user)
    job = db_session.query(IndexJob).filter(IndexJob.document_id == doc.id).order_by(
        IndexJob.created_at.desc()
    ).first()
    db_session.expire_all()
    assert job.revision_hash == compute_doc_instance_hash(doc)
