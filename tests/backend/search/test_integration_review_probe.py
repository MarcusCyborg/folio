"""Independent review probes and comprehensive Integration B regression tests (IB-R01..IB-R04)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.backend.models.auth import User
from src.backend.models.document import Document
from src.backend.models.search_index import (
    DocumentRevision,
    IndexGeneration,
    IndexJob,
    SearchContext,
)
from src.backend.models.taxonomy import Category, Tag
from src.backend.schemas.admin import DocumentWrite
from src.backend.search.engine import SearchEngine, SearchQuery
from src.backend.search.index import GenerationMismatchError, InvertedIndex
from src.backend.search.semantic import SemanticAdapter, SemanticCandidateHit
from src.backend.search_index.hashing import compute_doc_instance_hash
from src.backend.search_index.manager import GenerationManager
from src.backend.search_index.worker import IndexWorker
from src.backend.services.admin.content_service import (
    admin_create_document,
    admin_delete_document,
    admin_update_document,
    admin_update_document_status,
)
from src.backend.services.search.search_service import search_engine


# ==============================================================================
# IB-R01: STALE SEARCH INDEX CACHE & ATOMIC DISK RELOAD
# ==============================================================================


def test_review_disk_update_visible_to_existing_reader(tmp_path):
    index = InvertedIndex(generation_id="review-cache")
    index.upsert_document("first", text="neural", title="First")
    index.save(tmp_path)
    engine = SearchEngine()
    assert engine.get_or_load_index(index.generation_id, tmp_path).total_docs == 1
    index.upsert_document("second", text="neural", title="Second")
    index.save(tmp_path)
    assert engine.get_or_load_index(index.generation_id, tmp_path).total_docs == 2


def test_ib_r01_search_bm25_sees_publish_edit_unpublish_delete_without_restart(
    client, db_session, tmp_path, monkeypatch
):
    """Verify SearchEngine instance reloads same-generation index updates from IndexWorker."""
    user = db_session.query(User).first()
    cat = db_session.query(Category).first()
    monkeypatch.setenv("INDEX_STORAGE_DIR", str(tmp_path))

    gen = GenerationManager.build_new_generation(db_session, force=True)
    db_session.query(IndexJob).delete()
    db_session.commit()
    gen_id = gen.id
    engine = SearchEngine()
    worker = IndexWorker()

    # Warm the cache in SearchEngine (simulating API process holding loaded generation)
    initial_res = engine.search(SearchQuery(query="quantumfluxtoken", generation_id=gen_id))
    assert initial_res.candidates == []

    # 1. Create & publish a new document -> process via IndexWorker in same generation
    created = admin_create_document(
        db_session,
        DocumentWrite(
            title="Quantum Flux Monograph",
            summary="Initial summary",
            content="Detailed study of quantumfluxtoken mechanics.",
            category_id=cat.id,
            tag_ids=[],
        ),
        user,
    )
    doc_id = created["id"]
    admin_update_document_status(db_session, doc_id, "published", user)
    worker.run_once(db_session)

    # Same engine instance must immediately observe newly indexed document
    res_after_create = engine.search(SearchQuery(query="quantumfluxtoken", generation_id=gen_id))
    assert [h.doc_id for h in res_after_create.candidates] == [doc_id]

    # 2. Update document content -> process via IndexWorker
    admin_update_document(
        db_session,
        doc_id,
        {"content": "Updated study with hyperionpulsetoken mechanics."},
        user,
    )
    worker.run_once(db_session)

    res_old = engine.search(SearchQuery(query="quantumfluxtoken", generation_id=gen_id))
    assert res_old.candidates == []
    res_after_edit = engine.search(SearchQuery(query="hyperionpulsetoken", generation_id=gen_id))
    assert [h.doc_id for h in res_after_edit.candidates] == [doc_id]

    # 3. Unpublish document -> process via IndexWorker
    admin_update_document_status(db_session, doc_id, "draft", user)
    worker.run_once(db_session)

    res_unpub = engine.search(SearchQuery(query="hyperionpulsetoken", generation_id=gen_id))
    assert res_unpub.candidates == []

    # Re-publish then delete -> verify delete removes document from cached reader
    admin_update_document_status(db_session, doc_id, "published", user)
    worker.run_once(db_session)
    res_repub = engine.search(SearchQuery(query="hyperionpulsetoken", generation_id=gen_id))
    assert [h.doc_id for h in res_repub.candidates] == [doc_id]

    admin_delete_document(db_session, doc_id, user)
    worker.run_once(db_session)
    res_del = engine.search(SearchQuery(query="hyperionpulsetoken", generation_id=gen_id))
    assert res_del.candidates == []


def test_ib_r01_reader_rejects_half_written_or_mismatched_checksum_and_keeps_snapshot(
    tmp_path
):
    """Reader must reject torn state when doc_entries.json does not match index_stats.json checksum."""
    index = InvertedIndex(generation_id="atomic-gen")
    index.upsert_document("doc-1", text="alpha beta", title="Doc One")
    index.save(tmp_path)

    # Corrupt doc_entries.json without updating index_stats.json checksum marker
    (tmp_path / "doc_entries.json").write_text(
        '{"doc-1": {"doc_id": "doc-1", "length": 999}}', encoding="utf-8"
    )

    with pytest.raises(GenerationMismatchError, match="checksum mismatch"):
        InvertedIndex.load(tmp_path, "atomic-gen")


# ==============================================================================
# IB-R02: TAG UPDATE REVISION HASH & WORKER CONSISTENCY
# ==============================================================================


@pytest.mark.parametrize("preloaded_tags", [False, True])
def test_review_tag_edit_job_matches_committed_document(db_session, preloaded_tags):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    old_tags = {dt.tag_id for dt in doc.document_tags}
    new_tag = next(t for t in db_session.query(Tag).all() if t.id not in old_tags)
    user = db_session.query(User).first()
    if not preloaded_tags:
        db_session.expire(doc, ["document_tags"])
    admin_update_document(db_session, doc.id, {"tag_ids": [new_tag.id]}, user)
    job = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc.id)
        .order_by(IndexJob.created_at.desc())
        .first()
    )
    db_session.expire_all()
    assert job.revision_hash == compute_doc_instance_hash(doc)


@pytest.mark.parametrize("preloaded_tags", [False, True])
def test_ib_r02_tag_add_and_remove_indexed_by_worker_and_rollback_safe(
    db_session, tmp_path, monkeypatch, preloaded_tags
):
    """Tag add and tag removal must produce matching revision_hash and be applied by IndexWorker."""
    user = db_session.query(User).first()
    doc = db_session.query(Document).filter(Document.status == "published").first()
    all_tags = db_session.query(Tag).all()
    chosen_tag = all_tags[0]
    monkeypatch.setenv("INDEX_STORAGE_DIR", str(tmp_path))

    gen = GenerationManager.build_new_generation(db_session, force=True)
    db_session.query(IndexJob).delete()
    db_session.commit()
    gen_id = gen.id
    engine = SearchEngine()
    worker = IndexWorker()

    # 1. Update with new tag
    if preloaded_tags:
        _ = [dt.tag_id for dt in doc.document_tags]
    else:
        db_session.expire(doc, ["document_tags"])

    admin_update_document(db_session, doc.id, {"tag_ids": [chosen_tag.id]}, user)
    job_add = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc.id)
        .order_by(IndexJob.created_at.desc())
        .first()
    )
    db_session.expire_all()
    assert job_add.revision_hash == compute_doc_instance_hash(doc)

    worker.run_once(db_session)
    db_session.refresh(job_add)
    assert job_add.state == "completed"

    idx = engine.get_or_load_index(gen_id)
    assert chosen_tag.id in idx.documents[doc.id].tag_ids

    # 2. Remove all tags
    if preloaded_tags:
        _ = [dt.tag_id for dt in doc.document_tags]
    else:
        db_session.expire(doc, ["document_tags"])

    admin_update_document(db_session, doc.id, {"tag_ids": []}, user)
    job_remove = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc.id)
        .order_by(IndexJob.created_at.desc())
        .first()
    )
    db_session.expire_all()
    assert job_remove.revision_hash == compute_doc_instance_hash(doc)

    worker.run_once(db_session)
    db_session.refresh(job_remove)
    assert job_remove.state == "completed"

    idx_after_remove = engine.get_or_load_index(gen_id)
    assert idx_after_remove.documents[doc.id].tag_ids == []

    # 3. Transaction rollback must not leave behind orphan revision or job
    rev_count_before = (
        db_session.query(DocumentRevision)
        .filter(DocumentRevision.document_id == doc.id)
        .count()
    )
    job_count_before = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc.id)
        .count()
    )
    with patch.object(
        db_session, "commit", side_effect=RuntimeError("Simulated DB commit failure")
    ):
        with pytest.raises(RuntimeError, match="Simulated DB commit failure"):
            try:
                admin_update_document(
                    db_session, doc.id, {"tag_ids": [chosen_tag.id]}, user
                )
            except RuntimeError:
                db_session.rollback()
                raise

    assert (
        db_session.query(DocumentRevision)
        .filter(DocumentRevision.document_id == doc.id)
        .count()
        == rev_count_before
    )
    assert (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc.id)
        .count()
        == job_count_before
    )


# ==============================================================================
# IB-R03: SEMANTIC & HYBRID FILTER ENFORCEMENT BEFORE RRF / SNAPSHOT
# ==============================================================================


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_review_dense_candidates_obey_category_filter(client, db_session, mode):
    docs = db_session.query(Document).filter(Document.status == "published").all()
    target = docs[0]
    other = next(d for d in docs if d.category_id != target.category_id)
    GenerationManager.build_new_generation(db_session, force=True)
    hit = SemanticCandidateHit(other.id, 0.99, 1, 0.01, 1)
    with patch.object(SemanticAdapter, "query", return_value=([hit], None)):
        response = client.get(
            "/api/v1/search",
            params={
                "q": "neural",
                "mode": mode,
                "category_id": target.category_id,
            },
        )
    assert response.status_code == 200, response.text
    assert other.id not in [item["id"] for item in response.json()["items"]]


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_ib_r03_dense_candidates_obey_tags_dates_draft_and_soft_delete(
    client, db_session, mode
):
    """Verify semantic & hybrid enforce single tag, multi-tag strict AND, date bounds, published, and not deleted."""
    user = db_session.query(User).first()
    cat = db_session.query(Category).first()
    tags = db_session.query(Tag).limit(2).all()
    tag_a, tag_b = tags[0], tags[1]

    now = datetime.now(timezone.utc)

    d_match = admin_create_document(
        db_session,
        DocumentWrite(
            title="Dense Match Doc",
            summary="Matches all filters",
            content="Unique densefiltertoken content",
            category_id=cat.id,
            tag_ids=[tag_a.id, tag_b.id],
        ),
        user,
    )
    admin_update_document_status(db_session, d_match["id"], "published", user)

    d_one_tag = admin_create_document(
        db_session,
        DocumentWrite(
            title="Dense Partial Tag Doc",
            summary="Only has tag_a",
            content="Unique densefiltertoken content",
            category_id=cat.id,
            tag_ids=[tag_a.id],
        ),
        user,
    )
    admin_update_document_status(db_session, d_one_tag["id"], "published", user)

    d_draft = admin_create_document(
        db_session,
        DocumentWrite(
            title="Dense Draft Doc",
            summary="Draft status",
            content="Unique densefiltertoken content",
            category_id=cat.id,
            tag_ids=[tag_a.id, tag_b.id],
        ),
        user,
    )

    d_deleted = admin_create_document(
        db_session,
        DocumentWrite(
            title="Dense Deleted Doc",
            summary="Soft deleted",
            content="Unique densefiltertoken content",
            category_id=cat.id,
            tag_ids=[tag_a.id, tag_b.id],
        ),
        user,
    )
    admin_update_document_status(db_session, d_deleted["id"], "published", user)
    admin_delete_document(db_session, d_deleted["id"], user)

    d_old = admin_create_document(
        db_session,
        DocumentWrite(
            title="Dense Old Doc",
            summary="Created outside date window",
            content="Unique densefiltertoken content",
            category_id=cat.id,
            tag_ids=[tag_a.id, tag_b.id],
        ),
        user,
    )
    admin_update_document_status(db_session, d_old["id"], "published", user)
    old_doc_row = db_session.query(Document).filter(Document.id == d_old["id"]).first()
    old_doc_row.created_at = (now - timedelta(days=30)).replace(tzinfo=None)
    db_session.commit()

    GenerationManager.build_new_generation(db_session, force=True)
    search_engine.clear_cache()

    dense_hits = [
        SemanticCandidateHit(d_draft["id"], 0.99, 1, 0.01, 1),
        SemanticCandidateHit(d_deleted["id"], 0.98, 2, 0.02, 2),
        SemanticCandidateHit(d_old["id"], 0.97, 3, 0.03, 3),
        SemanticCandidateHit(d_one_tag["id"], 0.96, 4, 0.04, 4),
        SemanticCandidateHit(d_match["id"], 0.90, 5, 0.10, 5),
    ]

    date_from = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    with patch.object(SemanticAdapter, "query", return_value=(dense_hits, None)):
        # 1. Single tag + date range -> d_match and d_one_tag allowed; draft, deleted, and old excluded
        res_single = client.get(
            "/api/v1/search",
            params={
                "q": "densefiltertoken",
                "mode": mode,
                "category_id": cat.id,
                "tag_ids": [tag_a.id],
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        assert res_single.status_code == 200, res_single.text
        ids_single = [item["id"] for item in res_single.json()["items"]]
        assert set(ids_single) == {d_match["id"], d_one_tag["id"]}
        assert d_draft["id"] not in ids_single
        assert d_deleted["id"] not in ids_single
        assert d_old["id"] not in ids_single

        # 2. Strict AND multi-tag + date range -> only d_match allowed, and snapshot_candidate_count == 1
        res_multi = client.get(
            "/api/v1/search",
            params={
                "q": "densefiltertoken",
                "mode": mode,
                "category_id": cat.id,
                "tag_ids": [tag_a.id, tag_b.id],
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        assert res_multi.status_code == 200, res_multi.text
        body_multi = res_multi.json()
        ids_multi = [item["id"] for item in body_multi["items"]]
        assert ids_multi == [d_match["id"]]
        assert body_multi["snapshot_candidate_count"] == 1

        ctx = (
            db_session.query(SearchContext)
            .filter(SearchContext.token == body_multi["search_context_token"])
            .first()
        )
        assert ctx is not None
        assert ctx.candidate_ids == [d_match["id"]]


# ==============================================================================
# IB-R04: PAGINATION FALLBACK METADATA PERSISTENCE
# ==============================================================================


def test_review_fallback_declaration_survives_next_page(client, db_session):
    GenerationManager.build_new_generation(db_session, force=True)
    with patch.object(SemanticAdapter, "query", return_value=([], "Vector offline")):
        first = client.get(
            "/api/v1/search",
            params={
                "q": "neural",
                "mode": "semantic",
                "page_size": 1,
            },
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["engine_used"] == "fallback_bm25"
        assert body["has_more"]
        second = client.get(
            "/api/v1/search",
            params={
                "q": "neural",
                "mode": "semantic",
                "page_size": 1,
                "page": 2,
                "search_context_token": body["search_context_token"],
            },
        )
    assert second.status_code == 200, second.text
    assert second.json()["engine_used"] == "fallback_bm25"
    assert second.json()["is_degraded"] is True
    assert second.json()["degraded_reason"] == body["degraded_reason"]


def test_ib_r04_pagination_preserves_hybrid_bm25_and_double_fallbacks_and_bindings(
    client, db_session
):
    """Verify page 2+ preserves fallback metadata across hybrid fallback, BM25->ILIKE, and double fallback."""
    GenerationManager.build_new_generation(db_session, force=True)
    search_engine.clear_cache()

    # 1. Hybrid fallback (vector offline -> fallback_bm25)
    with patch.object(SemanticAdapter, "query", return_value=([], "Chroma timeout")):
        p1_hyb = client.get(
            "/api/v1/search",
            params={"q": "neural", "mode": "hybrid", "page_size": 1},
        )
        assert p1_hyb.status_code == 200
        b1_hyb = p1_hyb.json()
        assert b1_hyb["engine_used"] == "fallback_bm25"
        assert b1_hyb["is_degraded"] is True
        assert b1_hyb["has_more"] is True

        p2_hyb = client.get(
            "/api/v1/search",
            params={
                "q": "neural",
                "mode": "hybrid",
                "page_size": 1,
                "page": 2,
                "search_context_token": b1_hyb["search_context_token"],
            },
        )
        assert p2_hyb.status_code == 200
        b2_hyb = p2_hyb.json()
        assert b2_hyb["engine_used"] == b1_hyb["engine_used"] == "fallback_bm25"
        assert b2_hyb["is_degraded"] is True
        assert b2_hyb["degraded_reason"] == b1_hyb["degraded_reason"]

    # 2. BM25 -> ILIKE fallback AND Double fallback (semantic -> BM25 unavailable -> ilike_fallback)
    for gen in db_session.query(IndexGeneration).all():
        gen.status = "failed"
    db_session.commit()
    search_engine.clear_cache()

    for mode in ("bm25", "semantic", "hybrid"):
        with patch.object(SemanticAdapter, "query", return_value=([], "Vector offline")):
            p1 = client.get(
                "/api/v1/search",
                params={"q": "neural", "mode": mode, "page_size": 1},
            )
            assert p1.status_code == 200
            b1 = p1.json()
            assert b1["engine_used"] == "ilike_fallback"
            assert b1["is_degraded"] is True
            assert b1["degraded_reason"]
            assert b1["has_more"] is True

            p2 = client.get(
                "/api/v1/search",
                params={
                    "q": "neural",
                    "mode": mode,
                    "page_size": 1,
                    "page": 2,
                    "search_context_token": b1["search_context_token"],
                },
            )
            assert p2.status_code == 200
            b2 = p2.json()
            assert b2["engine_used"] == "ilike_fallback"
            assert b2["is_degraded"] is True
            assert b2["degraded_reason"] == b1["degraded_reason"]

            # Parameter mismatch must still fail with 400
            mismatch = client.get(
                "/api/v1/search",
                params={
                    "q": "different-query",
                    "mode": mode,
                    "page_size": 1,
                    "page": 2,
                    "search_context_token": b1["search_context_token"],
                },
            )
            assert mismatch.status_code == 400

            # Expired context must still fail with 410
            ctx = (
                db_session.query(SearchContext)
                .filter(SearchContext.token == b1["search_context_token"])
                .first()
            )
            ctx.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
            db_session.commit()

            expired = client.get(
                "/api/v1/search",
                params={
                    "q": "neural",
                    "mode": mode,
                    "page_size": 1,
                    "page": 2,
                    "search_context_token": b1["search_context_token"],
                },
            )
            assert expired.status_code == 410
