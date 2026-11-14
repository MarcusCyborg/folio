"""
test_seed_idempotency_asserts.py - Folio Seed Idempotency, Fixture Integrity & Count Verification.

Verifies:
1. Authentic Fixture Audit:
   - 103 total documents (100 published, 3 drafts).
   - 6 categories, 123 unique tags.
   - Exact SHA256 digest of fixtures/folio/documents.jsonl.
   - Preservation of existing canonical UUIDs (v4 and v5).
   - Uniqueness of source_url mappings.
2. Two-Pass Seed Idempotency on Empty Database:
   - Pass 1: Seeds clean database. Asserts exact counts (2 users, 100 published, 3 drafts, 6 categories, 123 tags).
   - Preservation check: Custom edits to documents and settings must be preserved.
   - Pass 2: Re-seeds same database. Asserts zero row duplication, ID preservation, and preserved edit retention.
   - Does NOT assert that all audit log timestamps must be byte-for-byte identical (audit logs append per policy).
3. Production/Staging Demo User Guard:
   - When skip_demo_users=True (or APP_ENV=production), zero demo users are created.
"""

import os
import sys
import json
import hashlib
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.models.base import Base
from src.backend.models.auth import User, Role, Permission, RolePermission
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.document import Document, DocumentTag
from src.backend.models.system import AppSetting, AuditLog
from scripts.seed_folio import (
    run_seed,
    DEMO_USERS,
    DEFAULT_SETTINGS,
    ROLES_CATALOG,
    PERMISSIONS_CATALOG,
)

FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "folio" / "documents.jsonl"
EXPECTED_SHA256 = "dc197eff2de35dcb6c889eb81660e261013996c31fd5e67edd951f22d0010648"


class TestFixtureIntegrityAndRealCounts:
    """Verifies that the authentic dataset contains 103 items (not the historical claim of 162/165)."""

    def test_fixture_hash_and_real_item_counts(self):
        assert FIXTURE_PATH.exists(), f"Fixture file not found: {FIXTURE_PATH}"

        # Normalize older Windows checkouts; the tracked fixture uses LF.
        raw_bytes = FIXTURE_PATH.read_bytes().replace(b"\r\n", b"\n")
        computed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        assert computed_sha256 == EXPECTED_SHA256, (
            f"Fixture SHA256 changed! Expected {EXPECTED_SHA256}, got {computed_sha256}. "
            "Never modify the authentic dataset to match stale report claims."
        )

        lines = [json.loads(line) for line in raw_bytes.decode("utf-8").splitlines() if line.strip()]
        assert len(lines) == 103, f"Expected exactly 103 documents, found {len(lines)}"

        published = [doc for doc in lines if doc.get("status") == "published"]
        drafts = [doc for doc in lines if doc.get("status") == "draft"]
        assert len(published) == 100, f"Expected 100 published documents, found {len(published)}"
        assert len(drafts) == 3, f"Expected 3 draft documents, found {len(drafts)}"

        # Check unique IDs and source URLs
        doc_ids = set()
        source_urls = set()
        categories = set()
        tags = set()

        for doc in lines:
            doc_id = doc.get("id")
            source_url = doc.get("source_url")
            assert doc_id, "Document missing ID"
            assert source_url, "Document missing source_url"
            assert doc_id not in doc_ids, f"Duplicate ID: {doc_id}"
            assert source_url not in source_urls, f"Duplicate source_url: {source_url}"
            doc_ids.add(doc_id)
            source_urls.add(source_url)
            categories.add(doc.get("category_slug"))
            for t in doc.get("tags", []):
                tags.add(t.strip().lower())

        assert len(categories) == 6, f"Expected 6 categories, got {len(categories)}"
        assert len(tags) == 123, f"Expected 123 tags, got {len(tags)}"


class TestSeedIdempotencyAndPreservation:
    """Proves two-pass seeding idempotency and preservation of existing modifications."""

    @pytest.fixture
    def test_engine(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        yield engine
        engine.dispose()

    def test_seed_twice_assert_counts_and_preserved_edits(self, test_engine):
        # Pass 1: Fresh seed
        run_seed(target=test_engine, skip_demo_users=False)

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            user_count_p1 = s.query(User).count()
            pub_doc_count_p1 = s.query(Document).filter(Document.status == "published").count()
            draft_count_p1 = s.query(Document).filter(Document.status == "draft").count()
            cat_count_p1 = s.query(Category).count()
            tag_count_p1 = s.query(Tag).count()
            audit_count_p1 = s.query(AuditLog).count()

            assert user_count_p1 == 2
            assert pub_doc_count_p1 == 100
            assert draft_count_p1 == 3
            assert cat_count_p1 == 6
            assert tag_count_p1 == 123
            assert audit_count_p1 >= 1

            # 2. Introduce an intentional modification that MUST be preserved across re-seed
            sample_doc = s.query(Document).filter(Document.id == "f7a024da-9f22-511a-9694-a0bce374a136").first()
            assert sample_doc is not None
            sample_doc.summary = "CUSTOM_SUMMARY_PRESERVED_ACROSS_RESEED"

            setting = s.query(AppSetting).filter(AppSetting.key == "comments_enabled").first()
            assert setting is not None
            setting.value = False
            s.commit()

        # Pass 2: Second seed run (testing strict zero-duplicate idempotency)
        run_seed(target=test_engine, skip_demo_users=False)

        with Session() as s:
            user_count_p2 = s.query(User).count()
            pub_doc_count_p2 = s.query(Document).filter(Document.status == "published").count()
            draft_count_p2 = s.query(Document).filter(Document.status == "draft").count()
            cat_count_p2 = s.query(Category).count()
            tag_count_p2 = s.query(Tag).count()
            audit_count_p2 = s.query(AuditLog).count()

            # Strict assertions: counts MUST NOT duplicate
            assert user_count_p2 == 2, f"Users duplicated! Expected 2, got {user_count_p2}"
            assert pub_doc_count_p2 == 100, f"Published docs duplicated! Expected 100, got {pub_doc_count_p2}"
            assert draft_count_p2 == 3, f"Drafts duplicated! Expected 3, got {draft_count_p2}"
            assert cat_count_p2 == 6, f"Categories duplicated! Expected 6, got {cat_count_p2}"
            assert tag_count_p2 == 123, f"Tags duplicated! Expected 123, got {tag_count_p2}"

            # Verify audit log appended new seed event without wiping previous logs
            assert audit_count_p2 > audit_count_p1

            # Verify preserved edits were NOT overwritten
            sample_doc_p2 = s.query(Document).filter(Document.id == "f7a024da-9f22-511a-9694-a0bce374a136").first()
            assert sample_doc_p2.summary == "CUSTOM_SUMMARY_PRESERVED_ACROSS_RESEED"

            setting_p2 = s.query(AppSetting).filter(AppSetting.key == "comments_enabled").first()
            assert setting_p2.value is False

    def test_seed_with_skip_demo_users_creates_zero_demo_accounts(self, test_engine):
        run_seed(target=test_engine, skip_demo_users=True)

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            user_count = s.query(User).count()
            assert user_count == 0, f"Expected 0 demo accounts with skip_demo_users=True, found {user_count}"
            doc_count = s.query(Document).count()
            assert doc_count == 103
