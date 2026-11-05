import json
import pytest
from pathlib import Path
from sqlalchemy.orm import Session
from src.backend.models.document import Document
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.search_index import DocumentRevision, IndexJob
from src.backend.search_index.importer import CorpusImporter, generate_doc_uuid_from_url


def test_dry_run_reports_duplicates_and_conflicts_without_writing_to_db(db_session: Session, tmp_path: Path):
    # Prepare dummy corpus with in-file duplicate and valid items
    corpus_file = tmp_path / "corpus.jsonl"
    lines = [
        json.dumps({
            "title": "Quantum Computing Basics",
            "content": "Quantum computation utilizes quantum bits or qubits...",
            "summary": "Introduction to qubits.",
            "url": "https://en.wikipedia.org/wiki/Quantum_computing_basics",
            "category_slug": "quantum-computing",
            "tags": ["quantum", "physics"],
            "author": "Wikipedia contributors",
            "source_license": "CC BY-SA 4.0",
        }),
        # Duplicate of URL in file
        json.dumps({
            "title": "Quantum Computing Duplicate",
            "content": "Duplicate content...",
            "url": "https://en.wikipedia.org/wiki/Quantum_computing_basics",
        }),
        # Missing content (invalid)
        json.dumps({
            "title": "Invalid Article",
            "url": "https://en.wikipedia.org/wiki/Invalid_article",
            "content": "",
        }),
    ]
    corpus_file.write_text("\n".join(lines), encoding="utf-8")

    initial_doc_count = db_session.query(Document).count()

    importer = CorpusImporter(db_session, dry_run=True)
    report = importer.import_corpus(corpus_file)

    assert report["dry_run"] is True
    assert report["total_scanned"] == 3
    assert report["valid_records"] == 1
    assert len(report["invalid_records"]) == 1
    assert len(report["duplicates_in_file"]) == 1
    assert report["inserted_count"] == 0

    # Ensure zero database changes were committed
    final_doc_count = db_session.query(Document).count()
    assert final_doc_count == initial_doc_count


def test_real_import_maps_source_url_to_id_idempotently(db_session: Session, tmp_path: Path):
    corpus_file = tmp_path / "corpus.json"
    url = "https://en.wikipedia.org/wiki/Neural_Architecture_Search"
    data = [
        {
            "title": "Neural Architecture Search",
            "content": "## Overview\n\n[edit]\n\nNeural architecture search (NAS) is a technique for automating the design of artificial neural networks.",
            "url": url,
            "category_slug": "artificial-intelligence",
            "tags": ["machine-learning", "automl"],
            "author": "Wikipedia contributors",
            "source_license": "CC BY-SA 4.0",
        }
    ]
    corpus_file.write_text(json.dumps(data), encoding="utf-8")

    # Pass 1: Real import
    importer = CorpusImporter(db_session, dry_run=False)
    report1 = importer.import_corpus(corpus_file)
    assert report1["inserted_count"] == 1
    assert report1["preserved_count"] == 0

    imported_doc = db_session.query(Document).filter(Document.source_url == url).first()
    assert imported_doc is not None
    assert imported_doc.title == "Neural Architecture Search"
    assert imported_doc.author == "Wikipedia contributors"
    assert imported_doc.source_license == "CC BY-SA 4.0"
    assert imported_doc.content == "## Overview\n\nNeural architecture search (NAS) is a technique for automating the design of artificial neural networks."

    # Outbox job & revision created
    rev = db_session.query(DocumentRevision).filter(DocumentRevision.document_id == imported_doc.id).first()
    assert rev is not None
    job = db_session.query(IndexJob).filter(IndexJob.document_id == imported_doc.id).first()
    assert job is not None
    assert job.operation == "upsert"

    # Pass 2: Re-import same file idempotently
    report2 = importer.import_corpus(corpus_file)
    assert report2["inserted_count"] == 0
    assert report2["preserved_count"] == 1
    assert report2["existing_preserved"][0]["document_id"] == imported_doc.id


def test_import_preserves_user_edits_without_overwrite(db_session: Session, tmp_path: Path):
    corpus_file = tmp_path / "corpus.jsonl"
    url = "https://en.wikipedia.org/wiki/Preserve_User_Edits_Test"
    record = {
        "title": "Original Corpus Title",
        "content": "Original body text from crawler.",
        "summary": "Original summary.",
        "url": url,
        "category_slug": "computational-biology",
    }
    corpus_file.write_text(json.dumps(record), encoding="utf-8")

    importer = CorpusImporter(db_session, dry_run=False)
    importer.import_corpus(corpus_file)

    doc = db_session.query(Document).filter(Document.source_url == url).first()
    assert doc is not None

    # Simulate user editing the document in Folio
    doc.title = "Custom User Title Edited in Folio"
    doc.summary = "Custom summary written by human editor."
    db_session.commit()

    # Re-run importer with original crawler file
    report = importer.import_corpus(corpus_file)
    assert report["preserved_count"] == 1

    # Verify that human edits were NOT overwritten!
    refreshed_doc = db_session.query(Document).filter(Document.source_url == url).first()
    assert refreshed_doc.title == "Custom User Title Edited in Folio"
    assert refreshed_doc.summary == "Custom summary written by human editor."


def test_conflict_detection_when_id_collides_with_different_url(db_session: Session, tmp_path: Path):
    # Existing doc
    existing_doc = db_session.query(Document).filter(Document.source_url.is_not(None)).first()
    assert existing_doc is not None

    corpus_file = tmp_path / "conflict.jsonl"
    conflict_record = {
        "id": existing_doc.id,  # Same ID
        "url": "https://en.wikipedia.org/wiki/Completely_Different_URL",  # Different URL!
        "title": "Conflict Article",
        "content": "Content text...",
    }
    corpus_file.write_text(json.dumps(conflict_record), encoding="utf-8")

    importer = CorpusImporter(db_session, dry_run=True)
    report = importer.import_corpus(corpus_file)
    assert len(report["conflicts_with_db"]) == 1
    assert report["conflicts_with_db"][0]["id"] == existing_doc.id
