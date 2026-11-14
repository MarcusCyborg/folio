from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from src.backend.core.config import settings
from src.backend.models.document import Document, DocumentTag
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.search_index import IndexGeneration, IndexJob
from src.backend.search.builder import IndexBuilder
from src.backend.search.snippets import generate_snippet
from src.backend.search_index import database_storage as storage
from src.backend.search_index.manager import GenerationManager
from src.backend.search_index.worker import IndexWorker
from src.backend.search_index.hashing import compute_doc_instance_hash


@pytest.fixture
def database_backend(monkeypatch):
    monkeypatch.setattr(settings, "INDEX_STORAGE_BACKEND", "database")
    storage._unpack_index.cache_clear()


@pytest.fixture
def search_docs(db_session):
    category = Category(name="Search regression", slug=f"search-{uuid4().hex}")
    db_session.add(category)
    db_session.flush()
    rows = [
        Document(title="Deep learning", summary="Neural networks", content="Deep learning models include GPT architectures.", category_id=category.id, status="published"),
        Document(title="Optimization software", summary="Algorithms", content="Mathematical optimization with learning methods. " + "Other tools. " * 70 + "Deep learning is supported.", category_id=category.id, status="published"),
        Document(title="GPT", summary="Language models", content="GPT uses deep neural networks for learning.", category_id=category.id, status="published"),
        Document(title="Deep learning private", summary="Draft", content="GPT deep learning", category_id=category.id, status="draft"),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


def test_portable_index_roundtrip_and_integrity():
    index = IndexBuilder().build_from_documents([
        {"id": "one", "title": "Deep learning", "content": "GPT", "tag_ids": ["tag"]},
    ], "portable")
    manifest = storage.pack_index(index)
    from types import SimpleNamespace
    generation = SimpleNamespace(id="portable", manifest=manifest)
    restored = storage.load_index(generation)
    assert restored.get_candidate_doc_ids(["deep", "gpt"]) == {"one"}
    assert restored.total_tokens == index.total_tokens
    assert restored.documents["one"].tag_ids == ["tag"]
    manifest["checksum"] = "corrupt"
    with pytest.raises(ValueError, match="checksum"):
        storage.load_index(generation)


def test_database_search_cold_start_without_files(client, db_session, database_backend, search_docs):
    with patch("src.backend.search.engine.SearchEngine.get_or_load_index", side_effect=AssertionError("No disk on Vercel")):
        first = client.get("/api/v1/search", params={"q": "deep learning", "page_size": 1}).json()
        assert first["engine_used"] == "bm25"
        assert first["is_degraded"] is False
        assert first["items"][0]["title"] == "Deep learning"
        assert first["items"][0]["score"] > 0
        storage._unpack_index.cache_clear()
        second = client.get("/api/v1/search", params={"q": "gpt deep learning"}).json()
        assert second["engine_used"] == "bm25"
        assert search_docs[0].id in {item["id"] for item in second["items"]}
        assert search_docs[3].id not in {item["id"] for item in second["items"]}
        assert first["index_generation"] == second["index_generation"]
        ready = client.get("/health/ready").json()
        assert ready["search"]["engine"] == "bm25"

        search_docs[2].content += " New content changes this generation."
        db_session.commit()
        third = client.get("/api/v1/search", params={"q": "deep learning"}).json()
        assert third["index_generation"] != first["index_generation"]
        old_page = client.get("/api/v1/search", params={
            "search_context_token": first["search_context_token"], "page": 2, "page_size": 1,
        }).json()
        assert old_page["index_generation"] == first["index_generation"]
        assert old_page["items"][0]["rank"] == 2


def test_source_changes_refresh_but_views_do_not(db_session, database_backend, search_docs):
    generation, index = storage.ensure_database_generation(db_session)
    search_docs[0].views_count += 1
    db_session.commit()
    same, _ = storage.ensure_database_generation(db_session)
    assert same.id == generation.id
    tag = db_session.query(Tag).first()
    db_session.add(DocumentTag(document_id=search_docs[0].id, tag_id=tag.id))
    db_session.commit()
    changed, index = storage.ensure_database_generation(db_session)
    assert changed.id != generation.id
    assert tag.id in index.documents[search_docs[0].id].tag_ids
    search_docs[0].status = "draft"
    search_docs[1].deleted_at = datetime.now(timezone.utc)
    search_docs[3].status = "published"
    db_session.commit()
    changed, index = storage.ensure_database_generation(db_session)
    assert search_docs[0].id not in index.documents
    assert search_docs[1].id not in index.documents
    assert search_docs[3].id in index.documents
    assert GenerationManager.verify_generation(db_session)["valid"] is True


def test_parallel_cold_starts_share_generation(db_session, database_backend):
    # Independent connections are required: the ordinary fixture uses one savepoint.
    bind = db_session.get_bind().engine
    with Session(bind) as session:
        previous = {g.id: g.status for g in session.query(IndexGeneration).all()}
    def build(_):
        with Session(bind) as session:
            generation, index = storage.ensure_database_generation(session)
            return generation.id, index.total_docs
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(build, range(3)))
        assert len(set(results)) == 1
    finally:
        with Session(bind) as session:
            for generation in session.query(IndexGeneration).all():
                if generation.id not in previous:
                    session.delete(generation)
                else:
                    generation.status = previous[generation.id]
            session.commit()


def test_corrupt_payload_rebuilds(db_session, database_backend, search_docs):
    generation, _ = storage.ensure_database_generation(db_session)
    original_id = generation.id
    generation.manifest = {**generation.manifest, "payload": "invalid"}
    db_session.commit()
    restored, index = storage.ensure_database_generation(db_session)
    assert restored.id != original_id
    assert search_docs[0].id in index.documents


def test_database_worker_and_generation_gc(db_session, database_backend, search_docs):
    original = GenerationManager.build_new_generation(db_session)
    doc = search_docs[0]
    doc.content += " Updated text for the index worker."
    db_session.commit()
    job = IndexJob(document_id=doc.id, revision_hash=compute_doc_instance_hash(doc), operation="upsert")
    db_session.add(job)
    db_session.commit()
    adapter = Mock()
    with patch("src.backend.search_index.worker.GenerationStorage", side_effect=AssertionError("No disk")):
        assert IndexWorker(semantic_adapter=adapter).process_job(db_session, job)
    assert job.state == "completed"
    adapter.upsert_document.assert_called_once()
    active = GenerationManager.get_active_generation(db_session)
    assert active.id != original.id
    assert doc.id in storage.load_index(active).get_candidate_doc_ids(["updated"])
    assert original.id in GenerationManager.garbage_collect_generations(db_session)
    db_session.refresh(original)
    assert "payload" not in original.manifest


def test_database_index_failure_uses_keyword_fallback(client, database_backend, search_docs):
    with patch.object(storage, "ensure_database_generation", side_effect=RuntimeError("Unavailable")):
        response = client.get("/api/v1/search", params={
            "q": "deep learning gpt", "category_id": search_docs[0].category_id,
        })
    assert response.status_code == 200
    data = response.json()
    assert data["engine_used"] == "ilike_fallback"
    assert data["items"][0]["title"] == "Deep learning"
    assert all(item["score"] is None for item in data["items"])


def test_fallback_multiword_ranking_and_no_fake_score(client, search_docs, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_STORAGE_BACKEND", "filesystem")
    with patch.object(GenerationManager, "get_active_generation", return_value=None):
        for query in ["deep learning gpt", "gpt deep learning"]:
            response = client.get("/api/v1/search", params={
                "q": query, "page_size": 1, "category_id": search_docs[0].category_id,
            })
            assert response.status_code == 200
            data = response.json()
            assert data["engine_used"] == "ilike_fallback"
            assert data["items"][0]["title"] == "Deep learning"
            assert data["items"][0]["score"] is None
            page = client.get("/api/v1/search", params={
                "search_context_token": data["search_context_token"], "page": 2, "page_size": 1,
            }).json()
            assert page["items"][0]["score"] is None


def test_snippet_prefers_multiple_terms_and_escapes_markup():
    body = "Learning alone. " + "Unrelated text. " * 25 + "Deep learning uses GPT <script>alert(1)</script>."
    snippet = generate_snippet(body, ["deep", "learning", "gpt"])
    assert "<em>Deep</em> <em>learning</em>" in snippet
    assert "<em>GPT</em>" in snippet
    assert "<script>" not in snippet
    assert "&lt;script&gt;" in snippet
