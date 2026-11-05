"""Verify migrations and two-pass seed assertions on a new owned PostgreSQL database."""
import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.backend.core.test_db_guard import TestRunManifest, provision_test_database, safe_teardown_test_database
from src.backend.models.auth import User
from src.backend.models.document import Document
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.system import AppSetting, AuditLog
from scripts.seed_folio import run_seed


def verify_seed(engine):
    fixture = [json.loads(line) for line in (PROJECT_ROOT / "fixtures/folio/documents.jsonl").read_text(encoding="utf-8").splitlines() if line]
    expected_ids = {doc["id"] for doc in fixture}
    expected_mapping = {doc["source_url"]: doc["id"] for doc in fixture}

    def counts(db):
        return (db.query(User).count(), db.query(Document).filter_by(status="published").count(),
                db.query(Document).filter_by(status="draft").count(), db.query(Category).count(), db.query(Tag).count())

    run_seed(target=engine)
    with Session(engine) as db:
        assert counts(db) == (5, 100, 3, 6, 123), counts(db)
        assert {d.id for d in db.query(Document).all()} == expected_ids
        assert {d.source_url: d.id for d in db.query(Document).all()} == expected_mapping
        first_audits = db.query(AuditLog).count()
        sample_id = fixture[0]["id"]
        db.get(Document, sample_id).summary = "LIVE_POSTGRES_PRESERVED_EDIT"
        db.get(AppSetting, "comments_enabled").value = False
        db.commit()
    run_seed(target=engine)
    with Session(engine) as db:
        assert counts(db) == (5, 100, 3, 6, 123), counts(db)
        assert {d.id for d in db.query(Document).all()} == expected_ids
        assert {d.source_url: d.id for d in db.query(Document).all()} == expected_mapping
        assert db.get(Document, sample_id).summary == "LIVE_POSTGRES_PRESERVED_EDIT"
        assert db.get(AppSetting, "comments_enabled").value is False
        assert db.query(AuditLog).count() > first_audits
        print(json.dumps({"dialect": engine.dialect.name, "counts": counts(db), "preserved_ids": len(expected_ids), "preserved_edits": True}))


def main():
    admin_url = os.environ["FOLIO_TEST_ADMIN_URL"]
    manifest = TestRunManifest.create()
    name = manifest.generate_db_name("folio_test_seed")
    url = provision_test_database(admin_url, manifest, requested_dbname=name)
    engine = create_engine(url)
    try:
        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.cmd_opts = argparse.Namespace(x=[f"db_url={url}"])
        command.upgrade(cfg, "head")
        verify_seed(engine)
    finally:
        engine.dispose()
        safe_teardown_test_database(admin_url, manifest, name)


if __name__ == "__main__":
    main()
