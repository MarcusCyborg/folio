"""
Integration and validation tests for evaluate/run_eval.py harness (P06).
"""

import json
from pathlib import Path
import pytest
from evaluate.run_eval import BenchmarkValidator


@pytest.fixture
def sample_valid_data():
    manifest = {
        "manifest_version": "1.0.0",
        "documents": [
            {"id": "doc-pub-1", "title": "Doc 1", "status": "published"},
            {"id": "doc-pub-2", "title": "Doc 2", "status": "published"},
            {"id": "doc-draft-1", "title": "Doc Draft", "status": "draft"},
        ]
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
            "Q2": {}, # Negative query has empty qrels
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
