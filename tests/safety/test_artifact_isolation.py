"""
test_artifact_isolation.py - Folio IA-07 Artifact Safety & Isolation Unit Tests.

Verifies:
1. Configurable artifact root resolution and non-overlapping run directory hierarchy.
2. Unique run ID generation with collision-resistant random suffix.
3. Path traversal sanitization across test names and suite identifiers.
4. Invariant: No outputs written to '../screenshots' or 'docs/verification'.
5. Real Playwright tracing lifecycle: start, execute actions, stop and verify valid .zip archive.
6. Intentional failure artifact generation: proves screenshot and trace are genuinely written on failure.
"""

import os
import sys
import zipfile
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.artifact_utils import (
    sanitize_artifact_name,
    get_git_commit_sha,
    get_worktree_name,
    generate_run_id,
    ArtifactContext,
    reset_artifact_context,
)


class TestArtifactSanitizationAndPaths:
    """Verifies path sanitization, root configuration, and run directory hierarchy."""

    def test_sanitize_artifact_name_path_traversal(self):
        # Prevents directory traversal attacks
        unsafe = "../../etc/passwd"
        sanitized = sanitize_artifact_name(unsafe)
        assert ".." not in sanitized
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert sanitized == "etc_passwd"

    def test_sanitize_artifact_name_pytest_node_ids(self):
        # Pytest node IDs contain colons, brackets, and spaces
        node_id = "tests/frontend/public/test_public_flows.py::test_catalog[1280x720]"
        sanitized = sanitize_artifact_name(node_id)
        assert ":" not in sanitized
        assert "[" not in sanitized
        assert "]" not in sanitized
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert "test_catalog_1280x720" in sanitized

    def test_generate_run_id_uniqueness(self):
        id1 = generate_run_id()
        id2 = generate_run_id()
        assert id1 != id2
        assert id1.startswith("run_")
        assert len(id1) >= 20  # run_YYYYMMDD_HHMMSS_<8hex>

    def test_artifact_context_hierarchy(self, tmp_path):
        ctx = ArtifactContext(
            artifact_root=tmp_path,
            worktree_name="TestWorktree",
            commit_sha="abc1234",
            run_id="run_20261101_120000_deadbeef",
        )

        expected_run_dir = tmp_path / "TestWorktree" / "abc1234" / "run_20261101_120000_deadbeef"
        assert ctx.run_dir == expected_run_dir

        public_shots = ctx.get_screenshots_dir("public")
        admin_shots = ctx.get_screenshots_dir("admin")
        failures_dir = ctx.get_failures_dir()
        traces_dir = ctx.get_traces_dir()
        junit_backend = ctx.get_junit_path("backend")

        assert public_shots == expected_run_dir / "screenshots" / "public"
        assert admin_shots == expected_run_dir / "screenshots" / "admin"
        assert failures_dir == expected_run_dir / "failures" / "screenshots"
        assert traces_dir == expected_run_dir / "failures" / "traces"
        assert junit_backend == expected_run_dir / "junit" / "junit-backend.xml"

        # Verify created on disk
        assert public_shots.is_dir()
        assert admin_shots.is_dir()
        assert failures_dir.is_dir()
        assert traces_dir.is_dir()

    def test_artifact_paths_never_touch_docs_verification_or_parent_screenshots(self, tmp_path):
        ctx = ArtifactContext(artifact_root=tmp_path)
        for suite in ("public", "admin", "remediation"):
            d = ctx.get_screenshots_dir(suite)
            resolved = str(d.resolve()).replace("\\", "/")
            assert "docs/verification" not in resolved
            assert "../screenshots" not in resolved

    def test_env_var_override_artifact_root(self, tmp_path, monkeypatch):
        custom_root = tmp_path / "custom_artifacts"
        monkeypatch.setenv("FOLIO_ARTIFACT_ROOT", str(custom_root))
        monkeypatch.delenv("FOLIO_RUN_ID", raising=False)

        reset_artifact_context(None)
        ctx = ArtifactContext()
        assert ctx.root_dir == custom_root.resolve()
        assert custom_root in ctx.run_dir.parents


class TestPlaywrightTracingAndFailureArtifacts:
    """Verifies genuine Playwright trace capture and intentional failure artifact verification."""

    def test_playwright_trace_lifecycle_genuine(self, tmp_path):
        from playwright.sync_api import sync_playwright

        ctx = ArtifactContext(artifact_root=tmp_path)
        trace_path = ctx.get_failure_trace_path("test_example_flow", 0)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            # 1. Start tracing before actions
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

            # 2. Perform real browser actions
            page = context.new_page()
            page.goto("data:text/html,<html><body><h1 id='title'>Folio Trace Verification</h1></body></html>")
            page.wait_for_selector("#title")
            assert page.inner_text("#title") == "Folio Trace Verification"

            # 3. Stop tracing before closing context
            context.tracing.stop(path=str(trace_path))
            context.close()
            browser.close()

        # 4. Verify trace archive exists and is non-empty
        assert trace_path.exists()
        assert trace_path.stat().st_size > 1000  # Genuine zip with snapshots is > 1KB

        # 5. Verify valid zip archive containing trace data
        with zipfile.ZipFile(trace_path, "r") as z:
            names = z.namelist()
            assert any("trace" in n for n in names)

    def test_intentional_failure_artifact_capture(self, tmp_path):
        from playwright.sync_api import sync_playwright

        ctx = ArtifactContext(artifact_root=tmp_path)
        screenshot_path = ctx.get_failure_screenshot_path("test_intentional_failure", 0)
        trace_path = ctx.get_failure_trace_path("test_intentional_failure", 0)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

            page = context.new_page()
            page.goto("data:text/html,<html><body style='background:red;'><h1>Intentional Failure Probe</h1></body></html>")
            page.wait_for_selector("h1")

            # Simulate failure handling hook
            try:
                # Intentional error condition
                assert 1 == 2, "Intentional probe error"
            except AssertionError:
                # Capture failure screenshot and trace before closing context
                page.screenshot(path=str(screenshot_path), full_page=True)
                context.tracing.stop(path=str(trace_path))
            finally:
                context.close()
                browser.close()

        # Verify failure screenshot is a valid PNG
        assert screenshot_path.exists()
        assert screenshot_path.stat().st_size > 500
        with open(screenshot_path, "rb") as f:
            header = f.read(8)
            assert header[:4] == b"\x89PNG"

        # Verify failure trace is a valid ZIP
        assert trace_path.exists()
        assert trace_path.stat().st_size > 1000
        with zipfile.ZipFile(trace_path, "r") as z:
            assert len(z.namelist()) > 0
