"""
Integration and validation tests for evaluate/run_eval.py harness (P06 & IB-R05).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from evaluate.run_eval import (
    BenchmarkValidator,
    PerformanceBenchmarker,
    RetrievalEvaluator,
    build_latency_boundaries,
    evaluate_engine_queries,
    resolve_git_commit_sha,
)


@pytest.fixture
def sample_valid_data():
    manifest = {
        "manifest_version": "1.0.0",
        "documents": [
            {"id": "doc-pub-1", "title": "Doc 1", "status": "published"},
            {"id": "doc-pub-2", "title": "Doc 2", "status": "published"},
            {"id": "doc-draft-1", "title": "Doc Draft", "status": "draft"},
        ],
    }
    queries = {
        "queries": [
            {"query_id": "Q1", "query": "Test query 1", "category": "exact_title", "split": "test"},
            {"query_id": "Q2", "query": "Test query negative", "category": "negative", "split": "test"},
        ]
    }
    qrels = {
        "qrels": {
            "Q1": {"doc-pub-1": 2, "doc-pub-2": 1},
            "Q2": {},  # Negative query has empty qrels
        }
    }
    return manifest, queries, qrels


def test_validator_success_on_valid_data(sample_valid_data):
    manifest, queries, qrels = sample_valid_data
    validator = BenchmarkValidator(manifest, queries, qrels)
    report = validator.validate()

    assert report["valid"] is True
    assert len(report["errors"]) == 0
    assert report["total_documents_manifest"] == 3
    assert report["published_documents"] == 2
    assert report["draft_documents"] == 1
    assert report["total_queries"] == 2
    assert report["positive_queries"] == 1
    assert report["negative_queries"] == 1
    assert report["oracle_bounds_k10"]["oracle_mean_p10"] == 0.2  # 2 rel / 10


def test_validator_rejects_missing_document_id(sample_valid_data):
    manifest, queries, qrels = sample_valid_data
    # Introduce unknown document ID
    qrels["qrels"]["Q1"]["doc-nonexistent-999"] = 1

    validator = BenchmarkValidator(manifest, queries, qrels)
    report = validator.validate()

    assert report["valid"] is False
    assert any("does not exist in corpus manifest" in err for err in report["errors"])


def test_validator_rejects_draft_document_relevance(sample_valid_data):
    manifest, queries, qrels = sample_valid_data
    # Assign relevance to draft doc
    qrels["qrels"]["Q1"]["doc-draft-1"] = 2

    validator = BenchmarkValidator(manifest, queries, qrels)
    report = validator.validate()

    assert report["valid"] is False
    assert any("is a DRAFT" in err for err in report["errors"])


def test_validator_detects_duplicate_queries(sample_valid_data):
    manifest, queries, qrels = sample_valid_data
    # Duplicate Q1 query_id
    queries["queries"].append({"query_id": "Q1", "query": "Duplicate ID", "category": "exact_title", "split": "tune"})

    validator = BenchmarkValidator(manifest, queries, qrels)
    report = validator.validate()

    assert report["valid"] is False
    assert any("Duplicate query_id: Q1" in err for err in report["errors"])


def test_live_production_dataset_validation():
    # Verify the actual versioned benchmark files in evaluate/
    manifest_path = Path("evaluate/corpus_manifest.json")
    queries_path = Path("evaluate/benchmark_queries.json")
    qrels_path = Path("evaluate/qrels.json")

    assert manifest_path.exists()
    assert queries_path.exists()
    assert qrels_path.exists()

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(queries_path, "r", encoding="utf-8") as f:
        queries = json.load(f)
    with open(qrels_path, "r", encoding="utf-8") as f:
        qrels = json.load(f)

    validator = BenchmarkValidator(manifest, queries, qrels)
    report = validator.validate()

    assert report["valid"] is True
    assert len(report["errors"]) == 0
    assert report["total_documents_manifest"] == 103
    assert report["published_documents"] == 100
    assert report["draft_documents"] == 3
    assert report["total_queries"] == 30
    assert report["positive_queries"] == 24
    assert report["negative_queries"] == 6


def test_ib_r05_failed_and_timeout_queries_included_in_quality_denominator():
    """Failed and timed-out positive queries must contribute 0.0 to denominator, never silently omitted."""
    eval_queries = [
        {"query_id": "Q1", "query": "ok query", "category": "exact_title", "split": "test"},
        {"query_id": "Q2", "query": "degraded query", "category": "conceptual", "split": "test"},
        {"query_id": "Q3", "query": "failed query", "category": "conceptual", "split": "test"},
        {"query_id": "Q4", "query": "timeout query", "category": "conceptual", "split": "test"},
    ]
    qrels = {
        "Q1": {"doc-1": 2},
        "Q2": {"doc-2": 2},
        "Q3": {"doc-3": 2},
        "Q4": {"doc-4": 2},
    }

    def fake_engine(query_str: str, top_k: int = 10):
        if query_str == "ok query":
            return ["doc-1"], {"doc-1": 1.0}, 4.0, "bm25", False, None
        if query_str == "degraded query":
            return ["doc-2"], {"doc-2": 1.0}, 6.0, "fallback_bm25", True, "Chroma offline"
        if query_str == "failed query":
            raise RuntimeError("Index read failure")
        raise TimeoutError("Query execution timed out")

    report = evaluate_engine_queries(
        eng_name="semantic",
        method=fake_engine,
        eval_queries=eval_queries,
        qrels=qrels,
        k=10,
        semantic_available=False,
    )

    health = report["operational_health"]
    assert health["total_queries"] == 4
    assert health["quality_denominator_positive_queries"] == 4
    assert health["successful_count"] == 2
    assert health["degraded_count"] == 1
    assert health["failed_count"] == 1
    assert health["timeout_count"] == 1
    assert health["error_count"] == 2
    assert health["environment_status"] == "BLOCKED_ENV"

    # Two queries scored 1.0 MAP@10 and two failed/timed-out queries scored 0.0 -> mean must be 2/4 = 0.5, NOT 2/2 = 1.0
    agg = report["aggregate_metrics"]
    assert agg["quality_denominator_positive_queries"] == 4
    assert agg["MAP10"] == 0.5
    assert agg["MRR10"] == 0.5
    assert agg["nDCG10"] == 0.5

    statuses = {r["query_id"]: r["status"] for r in report["per_query_results"]}
    assert statuses == {
        "Q1": "successful",
        "Q2": "degraded",
        "Q3": "failed",
        "Q4": "timeout",
    }


def test_ib_r05_verify_fallbacks_calls_real_search_service_not_direct_ilike(db_session):
    """Fallback verification must exercise SearchService(mode='bm25') with missing/failed active generation."""
    from src.backend.search_index.manager import GenerationManager

    GenerationManager.build_new_generation(db_session, force=True)
    evaluator = RetrievalEvaluator(db_session)
    benchmarker = PerformanceBenchmarker(db_session, [{"query_id": "Q1", "query": "neural"}])

    with patch.object(evaluator, "execute_ilike", side_effect=AssertionError("Must not call execute_ilike directly")):
        fb = benchmarker.verify_fallbacks(evaluator)

    missing = fb["missing_index_fallback"]
    assert missing["requested_mode"] == "bm25"
    assert missing["engine_used"] == "ilike_fallback"
    assert missing["is_degraded"] is True
    assert missing["degraded_reason"]
    assert missing["verified"] is True

    # Also verify that if execute_bm25 did NOT degrade, verified is False (never hardcoded True)
    with patch.object(
        evaluator,
        "execute_bm25",
        return_value=(["doc-1"], {"doc-1": 1.0}, 1.0, "bm25", False, None),
    ):
        fb_non_degraded = benchmarker.verify_fallbacks(evaluator)
    assert fb_non_degraded["missing_index_fallback"]["verified"] is False


def test_ib_r05_dynamic_git_sha_and_latency_boundaries():
    sha = resolve_git_commit_sha()
    assert sha != "693d031 (Milestone P05)"
    assert len(sha) == 40

    boundaries_blocked = build_latency_boundaries(False, "ChromaDB not installed")
    assert "retrieval_only" in boundaries_blocked
    assert "service_api_database" in boundaries_blocked
    assert "semantic_model_latency" in boundaries_blocked
    assert boundaries_blocked["semantic_model_latency"]["status"] == "BLOCKED_ENV"
    assert boundaries_blocked["semantic_model_latency"]["included_in_measured_latency"] is False


def test_ext02_corpus_provenance_digest_and_generation_metadata(db_session, tmp_path):
    """
    EXT-02:
    Evaluation reports must record corpus_id, deterministic corpus_digest_sha256,
    active_index_generation provenance, and corpus_db_alignment status.
    """
    from evaluate.run_eval import compute_corpus_digest_sha256, run_evaluation
    from src.backend.search_index.manager import GenerationManager

    gen = GenerationManager.build_new_generation(db_session, force=True)

    manifest_path = Path("evaluate/corpus_manifest.json")
    queries_path = Path("evaluate/benchmark_queries.json")
    qrels_path = Path("evaluate/qrels.json")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    expected_digest = compute_corpus_digest_sha256(manifest)
    assert len(expected_digest) == 64

    payload = run_evaluation(
        manifest_path=manifest_path,
        queries_path=queries_path,
        qrels_path=qrels_path,
        output_dir=tmp_path,
        split="test",
        k=5,
        run_benchmarks=False,
        selected_engines=["bm25"],
        db=db_session,
    )

    meta = payload["evaluation_metadata"]
    assert meta["corpus_id"] == "folio-canonical-corpus-v1"
    assert meta["corpus_digest_sha256"] == expected_digest
    assert meta["active_index_generation"] == gen.id
    assert meta["active_index_generation_num"] == gen.generation_num
    assert meta["corpus_db_alignment"] == "MATCH"
    assert (tmp_path / "eval_results_p06.json").exists()


def test_r3_05_execute_ilike_unpacks_tuple_and_returns_ranked_hits(db_session):
    """R3-05: RetrievalEvaluator.execute_ilike must unpack (hits, total_matches) cleanly."""
    evaluator = RetrievalEvaluator(db_session)
    doc_ids, scores, elapsed_ms, engine_used, is_degraded, degraded_reason = evaluator.execute_ilike(
        "Deep learning", top_k=5
    )
    assert engine_used == "ilike_baseline"
    assert is_degraded is False
    assert degraded_reason is None
    assert elapsed_ms >= 0.0
    assert len(doc_ids) >= 1
    assert all(did in scores for did in doc_ids)


def test_r3_05_corpus_db_alignment_detects_swapped_ids_content_drift_and_tampered_manifest(db_session, tmp_path):
    """
    R3-05:
    corpus_db_alignment must perform order-independent verification of published document IDs,
    non-deleted status, canonical titles, and content/summary SHA-256 digests against PostgreSQL
    rather than comparing counts alone. Official evaluation must refuse mismatched corpora unless
    explicitly overridden as INVALID_MISMATCH.
    """
    import copy
    import uuid
    from datetime import datetime, timezone
    from evaluate.run_eval import CorpusAlignmentError, run_evaluation
    from src.backend.models.document import Document
    from src.backend.models.taxonomy import Category
    from src.backend.search_index.manager import GenerationManager

    GenerationManager.build_new_generation(db_session, force=True)

    manifest_path = Path("evaluate/corpus_manifest.json")
    queries_path = Path("evaluate/benchmark_queries.json")
    qrels_path = Path("evaluate/qrels.json")
    base_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 1. Reordered manifest documents (same IDs/hashes/statuses, shuffled order) -> MUST still MATCH
    reordered_manifest = copy.deepcopy(base_manifest)
    reordered_manifest["documents"] = list(reversed(reordered_manifest["documents"]))
    reordered_path = tmp_path / "manifest_reordered.json"
    reordered_path.write_text(json.dumps(reordered_manifest), encoding="utf-8")

    ok_payload = run_evaluation(
        manifest_path=reordered_path,
        queries_path=queries_path,
        qrels_path=qrels_path,
        output_dir=tmp_path / "out_ok",
        split="test",
        k=5,
        run_benchmarks=False,
        selected_engines=["ilike"],
        db=db_session,
    )
    assert ok_payload["evaluation_metadata"]["corpus_db_alignment"] == "MATCH"
    assert ok_payload["evaluation_metadata"]["verification_status"] == "VERIFIED_MATCH"

    # 2. Tampered manifest content_sha256 (same count=100) -> MUST block by default & flag INVALID_MISMATCH on override
    tampered_manifest = copy.deepcopy(base_manifest)
    pub_entry = next(d for d in tampered_manifest["documents"] if d["status"] == "published")
    pub_entry["content_sha256"] = "0" * 64
    tampered_path = tmp_path / "manifest_tampered.json"
    tampered_path.write_text(json.dumps(tampered_manifest), encoding="utf-8")

    with pytest.raises(CorpusAlignmentError):
        run_evaluation(
            manifest_path=tampered_path,
            queries_path=queries_path,
            qrels_path=qrels_path,
            output_dir=tmp_path / "out_tampered_blocked",
            split="test",
            k=5,
            run_benchmarks=False,
            selected_engines=["bm25"],
            db=db_session,
        )

    tampered_diag = run_evaluation(
        manifest_path=tampered_path,
        queries_path=queries_path,
        qrels_path=qrels_path,
        output_dir=tmp_path / "out_tampered_diag",
        split="test",
        k=5,
        run_benchmarks=False,
        selected_engines=["bm25"],
        db=db_session,
        allow_corpus_mismatch=True,
    )
    assert tampered_diag["evaluation_metadata"]["corpus_db_alignment"] == "MISMATCH"
    assert tampered_diag["evaluation_metadata"]["verification_status"] == "INVALID_MISMATCH"
    assert pub_entry["id"] in tampered_diag["evaluation_metadata"]["alignment_details"]["content_mismatches"]

    # 3. DB published count stays IDENTICAL (100), but one published doc is soft-deleted
    #    and replaced by a newly inserted published doc (same total count, different IDs!)
    victim_id = pub_entry["id"]
    victim = db_session.query(Document).filter(Document.id == victim_id).first()
    cat = db_session.query(Category).first()
    now = datetime.now(timezone.utc)
    victim.deleted_at = now
    replacement_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=replacement_id,
            title="Replacement Doc Same Total Count",
            summary="Injected to keep published count == 100",
            content="Replacement corpus drift test document",
            category_id=cat.id,
            status="published",
            created_at=now,
            published_at=now,
        )
    )
    db_session.flush()

    with pytest.raises(CorpusAlignmentError):
        run_evaluation(
            manifest_path=manifest_path,
            queries_path=queries_path,
            qrels_path=qrels_path,
            output_dir=tmp_path / "out_swap_blocked",
            split="test",
            k=5,
            run_benchmarks=False,
            selected_engines=["bm25"],
            db=db_session,
        )

    swap_diag = run_evaluation(
        manifest_path=manifest_path,
        queries_path=queries_path,
        qrels_path=qrels_path,
        output_dir=tmp_path / "out_swap_diag",
        split="test",
        k=5,
        run_benchmarks=False,
        selected_engines=["bm25"],
        db=db_session,
        allow_corpus_mismatch=True,
    )
    meta_swap = swap_diag["evaluation_metadata"]
    assert meta_swap["db_published_documents"] == 100
    assert meta_swap["corpus_db_alignment"] == "MISMATCH"
    assert meta_swap["verification_status"] == "INVALID_MISMATCH"
    assert victim_id in meta_swap["alignment_details"]["missing_published_ids"]
    assert replacement_id in meta_swap["alignment_details"]["extra_published_ids"]

    # Restore victim & remove replacement, then alter only content on victim (exact same IDs & counts!)
    db_session.query(Document).filter(Document.id == replacement_id).delete(synchronize_session=False)
    victim.deleted_at = None
    orig_content = victim.content
    victim.content = orig_content + "\n\nDrifted DB content not in manifest."
    db_session.flush()

    with pytest.raises(CorpusAlignmentError):
        run_evaluation(
            manifest_path=manifest_path,
            queries_path=queries_path,
            qrels_path=qrels_path,
            output_dir=tmp_path / "out_drift_blocked",
            split="test",
            k=5,
            run_benchmarks=False,
            selected_engines=["bm25"],
            db=db_session,
        )

    drift_diag = run_evaluation(
        manifest_path=manifest_path,
        queries_path=queries_path,
        qrels_path=qrels_path,
        output_dir=tmp_path / "out_drift_diag",
        split="test",
        k=5,
        run_benchmarks=False,
        selected_engines=["bm25"],
        db=db_session,
        allow_corpus_mismatch=True,
    )
    assert drift_diag["evaluation_metadata"]["corpus_db_alignment"] == "MISMATCH"
    assert drift_diag["evaluation_metadata"]["verification_status"] == "INVALID_MISMATCH"
    assert victim_id in drift_diag["evaluation_metadata"]["alignment_details"]["content_mismatches"]
