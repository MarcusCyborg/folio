"""
artifact_utils.py - Folio Unified Artifact Root & Path Manager (Remediation of IA-07).

Provides configurable, collision-free artifact paths for:
- Browser visual verification screenshots (public, admin, remediation).
- Playwright context failure traces (.zip).
- Pytest failure screenshots.
- JUnit XML test execution reports.

Enforces directory convention:
  <artifact_root>/<worktree_or_checkout>/<commit_sha>/<run_id>/<suite_or_kind>/...

Security & Reproducibility Invariants:
1. Output root is fully configurable via FOLIO_ARTIFACT_ROOT (defaults to git-ignored test-results/artifacts).
2. Never writes to '../screenshots' or 'docs/verification'.
3. Never overwrites historical or baseline tracked PNG evidence.
4. Run ID incorporates timestamp + random suffix, preventing collisions across concurrent runs or runs in the same second.
5. All file names are sanitized against path traversal vulnerabilities.
"""

import os
import re
import sys
import uuid
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Project root resolution
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def sanitize_artifact_name(name: str) -> str:
    """
    Sanitizes arbitrary strings (e.g. pytest node IDs, test names) for safe filesystem usage.
    Replaces path separators and reserved characters with underscores to prevent path traversal.
    """
    if not name:
        return "unnamed"
    # Replace invalid/unsafe characters across Windows and POSIX
    sanitized = re.sub(r'[\\/*?:"<>|\s\[\]#:]+', "_", name)
    sanitized = sanitized.strip("._")
    return sanitized or "unnamed"


def get_git_commit_sha(repo_root: Optional[Path] = None) -> str:
    """Retrieves short Git commit SHA, falling back to environment or 'local'."""
    env_sha = os.environ.get("FOLIO_COMMIT_SHA") or os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha[:7]

    root = repo_root or PROJECT_ROOT
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        ).strip()
        if out:
            return out
    except Exception:
        pass

    # Direct fallback if .git exists
    git_head = root / ".git" / "HEAD"
    if git_head.exists():
        try:
            head_content = git_head.read_text().strip()
            if head_content.startswith("ref:"):
                ref_path = root / ".git" / head_content.split(" ", 1)[1].strip()
                if ref_path.exists():
                    return ref_path.read_text().strip()[:7]
            else:
                return head_content[:7]
        except Exception:
            pass

    return "local"


def get_worktree_name(repo_root: Optional[Path] = None) -> str:
    """Returns directory name of worktree/checkout."""
    root = repo_root or PROJECT_ROOT
    return sanitize_artifact_name(root.name)


def generate_run_id() -> str:
    """Generates unique run ID formatted as run_YYYYMMDD_HHMMSS_<8 hex chars>."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:8]
    return f"run_{ts}_{rand_suffix}"


class ArtifactContext:
    """
    Encapsulates hierarchical artifact output locations for a specific execution run.
    """

    def __init__(
        self,
        artifact_root: Optional[Path] = None,
        worktree_name: Optional[str] = None,
        commit_sha: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        raw_root = artifact_root or os.environ.get("FOLIO_ARTIFACT_ROOT") or (PROJECT_ROOT / "test-results" / "artifacts")
        self.root_dir = Path(raw_root).resolve()
        self.worktree_name = worktree_name or get_worktree_name()
        self.commit_sha = commit_sha or get_git_commit_sha()
        self.run_id = run_id or os.environ.get("FOLIO_RUN_ID") or generate_run_id()

        # Dedicated run directory: <root>/<worktree>/<commit>/<run_id>
        self.run_dir = self.root_dir / self.worktree_name / self.commit_sha / self.run_id

    def ensure_dir(self, directory: Path) -> Path:
        """Ensures directory exists on disk and returns the Path."""
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def get_screenshots_dir(self, suite: str = "public") -> Path:
        """Returns dedicated screenshot directory for given suite (e.g. public, admin)."""
        safe_suite = sanitize_artifact_name(suite)
        path = self.run_dir / "screenshots" / safe_suite
        return self.ensure_dir(path)

    def get_failures_dir(self) -> Path:
        """Returns dedicated directory for test failure screenshots."""
        path = self.run_dir / "failures" / "screenshots"
        return self.ensure_dir(path)

    def get_traces_dir(self) -> Path:
        """Returns dedicated directory for Playwright context traces."""
        path = self.run_dir / "failures" / "traces"
        return self.ensure_dir(path)

    def get_junit_path(self, suite: str = "suite") -> Path:
        """Returns dedicated JUnit XML report path for given suite."""
        safe_suite = sanitize_artifact_name(suite)
        junit_dir = self.ensure_dir(self.run_dir / "junit")
        return junit_dir / f"junit-{safe_suite}.xml"

    def get_failure_screenshot_path(self, test_name: str, index: int = 0) -> Path:
        """Generates collision-free path for a test failure screenshot."""
        safe_name = sanitize_artifact_name(test_name)
        return self.get_failures_dir() / f"{safe_name}_{index}_{self.run_id}.png"

    def get_failure_trace_path(self, test_name: str, index: int = 0) -> Path:
        """Generates collision-free path for a Playwright failure trace archive."""
        safe_name = sanitize_artifact_name(test_name)
        return self.get_traces_dir() / f"{safe_name}_{index}_{self.run_id}.zip"


# Session-level cached context instance
_CURRENT_CONTEXT: Optional[ArtifactContext] = None


def get_artifact_context() -> ArtifactContext:
    """Returns active session ArtifactContext, initializing lazily if needed."""
    global _CURRENT_CONTEXT
    if _CURRENT_CONTEXT is None:
        _CURRENT_CONTEXT = ArtifactContext()
    return _CURRENT_CONTEXT


def reset_artifact_context(context: Optional[ArtifactContext] = None) -> ArtifactContext:
    """Resets or overrides the active ArtifactContext (useful for testing or sub-runs)."""
    global _CURRENT_CONTEXT
    _CURRENT_CONTEXT = context
    return get_artifact_context()
