import os
import json
import pytest
import shutil
import tempfile
from pathlib import Path

from scripts.ops.backup import perform_backup, compute_sha256
from scripts.ops.restore import perform_restore, verify_checksums, BackupIntegrityError


def test_backup_creates_valid_archive_and_manifest(tmp_path):
    """perform_backup creates archive, checksums, and manifest with correct metadata."""
    backup_out = tmp_path / "backups"
    report = perform_backup(
        output_dir=backup_out,
        label="test_run",
    )

    assert report["status"] == "success"
    archive_path = Path(report["archive_path"])
    assert archive_path.exists()
    assert archive_path.stat().st_size > 0

    manifest = report["manifest"]
    assert manifest["version"] == "1.0.0"
    assert "components" in manifest
    assert "database" in manifest["components"]
    assert "index" in manifest["components"]
    assert "media" in manifest["components"]
    assert "checksums_file" in manifest


def test_restore_verifies_checksum_tampering(tmp_path):
    """verify_checksums must detect corrupted or tampered files and raise BackupIntegrityError."""
    # Create mock backup directory
    mock_backup = tmp_path / "mock_backup"
    mock_backup.mkdir()
    data_file = mock_backup / "data.txt"
    data_file.write_text("authentic content", encoding="utf-8")

    checksum_file = mock_backup / "checksums.sha256"
    valid_hash = compute_sha256(data_file)
    checksum_file.write_text(f"{valid_hash}  data.txt\n", encoding="utf-8")

    # Valid check
    verified = verify_checksums(mock_backup)
    assert verified["data.txt"] is True

    # Tamper with file
    data_file.write_text("tampered malicious payload", encoding="utf-8")
    with pytest.raises(BackupIntegrityError) as exc_info:
        verify_checksums(mock_backup)
    assert "Checksum mismatch" in str(exc_info.value)


def test_restore_detects_missing_file(tmp_path):
    """verify_checksums must fail if a declared file is missing."""
    mock_backup = tmp_path / "missing_file_backup"
    mock_backup.mkdir()
    checksum_file = mock_backup / "checksums.sha256"
    checksum_file.write_text("abcdef1234567890  non_existent_file.sql\n", encoding="utf-8")

    with pytest.raises(BackupIntegrityError) as exc_info:
        verify_checksums(mock_backup)
    assert "missing file declared in checksums" in str(exc_info.value).lower()
