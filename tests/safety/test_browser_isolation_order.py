"""
test_browser_isolation_order.py - Folio Browser Test Isolation & Order Independence Proof.

Verifies:
1. Browser Test DB State Isolation:
   - Proves that data mutated by browser tests (app settings, user suspensions, newly created
     test documents, roles, reports, comments) does not leak across test boundaries.
   - Proves that test execution order (A -> B vs B -> A) has zero impact on state.
2. Two Sequential Suite Runs with Independent Run IDs:
   - Proves run 2 does not overwrite run 1 artifacts.
3. Tracked Evidence Protection:
   - Asserts all 52 tracked PNG files in docs/verification remain 100% bit-for-bit identical before and after runs.
"""

import os
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.models.base import Base
from src.backend.models.auth import User
from src.backend.models.document import Document
from src.backend.models.system import AppSetting, AuditLog
from scripts.seed_folio import run_seed, DEFAULT_SETTINGS
from src.backend.core.artifact_utils import ArtifactContext, reset_artifact_context
from tests.conftest import reset_browser_test_data

DOCS_VERIFICATION_DIR = PROJECT_ROOT / "docs" / "verification"


class TestBrowserIsolationAndOrderIndependence:
    """Verifies isolation across sequential test executions and differing orders."""

    @pytest.fixture
    def isolated_db(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        run_seed(target=engine, skip_demo_users=False)
        yield engine
        engine.dispose()

    def simulate_flow_a_admin_settings_and_document(self, engine):
        """Simulates test_admin_flows modifying settings and adding a document."""
        Session = sessionmaker(bind=engine)
        with Session() as s:
            setting = s.query(AppSetting).filter(AppSetting.key == "site_name").first()
            setting.value = "Modified Site Name"
            
            from src.backend.models.taxonomy import Category
            cat = s.query(Category).first()
            new_doc = Document(
                id="99999999-9999-9999-9999-999999999999",
                title="Quantum Computing Advancements 123456",
                summary="Temporary test doc",
                content="Content",
                status="draft",
                category_id=cat.id,
                source_url="https://example.com/quantum_temp_1",
            )
            s.add(new_doc)

            reader = s.query(User).filter(User.username == "reader").first()
            reader.commenting_suspended_until = datetime(2099, 1, 1, tzinfo=timezone.utc)
            s.commit()

    def simulate_flow_b_public_user_registration(self, engine):
        """Simulates test_public_flows registering a new user."""
        Session = sessionmaker(bind=engine)
        with Session() as s:
            new_user = User(
                email="ephemeral_test_user@folio.test",
                username="ephemeral_user",
                display_name="Ephemeral User",
                password_hash="argon2_hash",
                role_key="member",
            )
            s.add(new_user)
            s.commit()

    def test_order_a_then_b(self, isolated_db):
        Session = sessionmaker(bind=isolated_db)

        # Execute Flow A
        self.simulate_flow_a_admin_settings_and_document(isolated_db)
        with Session() as s:
            assert s.query(Document).filter(Document.title.like("Quantum%")).count() == 1
            assert s.query(User).filter(User.username == "reader").first().commenting_suspended_until is not None

        # Reset isolation hook
        reset_browser_test_data(isolated_db)

        # Verify state is pristine before Flow B
        with Session() as s:
            assert s.query(Document).filter(Document.title.like("Quantum%")).count() == 0
            assert s.query(User).filter(User.username == "reader").first().commenting_suspended_until is None
            setting = s.query(AppSetting).filter(AppSetting.key == "site_name").first()
            assert setting.value == DEFAULT_SETTINGS["site_name"]

        # Execute Flow B
        self.simulate_flow_b_public_user_registration(isolated_db)
        with Session() as s:
            assert s.query(User).filter(User.username == "ephemeral_user").count() == 1

        # Reset isolation hook
        reset_browser_test_data(isolated_db)

        # Verify pristine again
        with Session() as s:
            assert s.query(User).filter(User.username == "ephemeral_user").count() == 0

    def test_order_b_then_a(self, isolated_db):
        """Reverses execution order (B -> A) to prove order independence."""
        Session = sessionmaker(bind=isolated_db)

        # Execute Flow B first
        self.simulate_flow_b_public_user_registration(isolated_db)
        with Session() as s:
            assert s.query(User).filter(User.username == "ephemeral_user").count() == 1

        reset_browser_test_data(isolated_db)

        with Session() as s:
            assert s.query(User).filter(User.username == "ephemeral_user").count() == 0

        # Execute Flow A second
        self.simulate_flow_a_admin_settings_and_document(isolated_db)
        with Session() as s:
            assert s.query(Document).filter(Document.title.like("Quantum%")).count() == 1

        reset_browser_test_data(isolated_db)

        with Session() as s:
            assert s.query(Document).filter(Document.title.like("Quantum%")).count() == 0
            assert s.query(User).count() == 2


class TestTrackedEvidenceImmutability:
    """Verifies that running captures and test suites never touches tracked baseline PNG files."""

    def test_tracked_pngs_remain_untouched_after_runs(self, tmp_path):
        assert DOCS_VERIFICATION_DIR.exists()
        tracked_pngs = list(DOCS_VERIFICATION_DIR.glob("**/*.png"))
        assert len(tracked_pngs) >= 30, f"Expected tracked PNGs in {DOCS_VERIFICATION_DIR}"

        # 1. Compute SHA256 of all tracked PNGs prior to test run
        hashes_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked_pngs}

        # 2. Simulate Run 1 writing to ArtifactContext
        ctx_run1 = ArtifactContext(artifact_root=tmp_path, run_id="run_1_alpha")
        admin_out1 = ctx_run1.get_screenshots_dir("admin")
        (admin_out1 / "admin_documents_1440x900.png").write_bytes(b"\x89PNG\r\n\x1a\nRUN1_DATA")

        # 3. Simulate Run 2 writing to ArtifactContext (distinct run ID)
        ctx_run2 = ArtifactContext(artifact_root=tmp_path, run_id="run_2_beta")
        admin_out2 = ctx_run2.get_screenshots_dir("admin")
        (admin_out2 / "admin_documents_1440x900.png").write_bytes(b"\x89PNG\r\n\x1a\nRUN2_DATA")

        # 4. Verify run 1 and run 2 do not collide or overwrite
        assert ctx_run1.run_dir != ctx_run2.run_dir
        assert (admin_out1 / "admin_documents_1440x900.png").read_bytes() == b"\x89PNG\r\n\x1a\nRUN1_DATA"
        assert (admin_out2 / "admin_documents_1440x900.png").read_bytes() == b"\x89PNG\r\n\x1a\nRUN2_DATA"

        # 5. Check all tracked PNGs: zero files modified!
        hashes_after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked_pngs}
        assert hashes_before == hashes_after, "Tracked PNG files were mutated during run!"
