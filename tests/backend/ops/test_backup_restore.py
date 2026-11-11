import os
import json
import tarfile
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.conftest import test_db_url
from scripts.ops import backup, restore
from scripts.ops.backup import (
    DatabaseBackupError,
    perform_backup,
    compute_sha256,
    redact_db_url,
    sanitize_diagnostic_text,
)
from scripts.ops.restore import (
    BackupIntegrityError,
    DatabaseRestoreError,
    IndexRecoveryError,
    perform_restore,
    restore_database,
    verify_backup_artifact,
    verify_checksums,
)
from scripts.run_restore_drill import run_drill, RestoreDrillError


@pytest.fixture
def ensure_pg_bin_path(monkeypatch):
    """Ensures pg_dump and psql can be located on PATH or standard test location."""
    if backup.find_pg_tool("pg_dump") and backup.find_pg_tool("psql"):
        return
    candidate = Path("F:/dpl13.10/folio-live-runtime/pgsql/bin")
    if candidate.is_dir():
        monkeypatch.setenv("POSTGRES_BIN_PATH", str(candidate))
    if not backup.find_pg_tool("pg_dump") or not backup.find_pg_tool("psql"):
        pytest.skip("PostgreSQL client tools (pg_dump/psql) not installed in test environment")


def test_backup_fails_when_pg_dump_missing(tmp_path):
    """R01: Missing pg_dump must fail closed with DatabaseBackupError and leave no partial archive."""
    backup_out = tmp_path / "backups"
    with patch.object(backup, "is_db_reachable", return_value=True), \
         patch.object(backup, "find_pg_tool", return_value=None):
        with pytest.raises(DatabaseBackupError) as exc_info:
            perform_backup(output_dir=backup_out, db_url=test_db_url, label="missing_tool")
        assert "pg_dump" in str(exc_info.value)

    assert list(backup_out.glob("*.tar.gz")) == []


def test_backup_fails_when_pg_dump_nonzero(tmp_path):
    """R01: Non-zero exit from pg_dump must fail closed and leave no archive."""
    backup_out = tmp_path / "backups"
    failed_proc = subprocess.CompletedProcess(
        args=["pg_dump"], returncode=2, stdout="", stderr="pg_dump: error: connection failed"
    )
    with patch.object(backup, "is_db_reachable", return_value=True), \
         patch.object(backup, "find_pg_tool", return_value="/usr/bin/pg_dump"), \
         patch("subprocess.run", return_value=failed_proc):
        with pytest.raises(DatabaseBackupError) as exc_info:
            perform_backup(output_dir=backup_out, db_url=test_db_url, label="nonzero")
        assert "exited with code 2" in str(exc_info.value)

    assert list(backup_out.glob("*.tar.gz")) == []


def test_backup_fails_when_pg_dump_timeout(tmp_path):
    """R01: Timeout from pg_dump must fail closed and leave no archive."""
    backup_out = tmp_path / "backups"
    with patch.object(backup, "is_db_reachable", return_value=True), \
         patch.object(backup, "find_pg_tool", return_value="/usr/bin/pg_dump"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pg_dump", timeout=1)):
        with pytest.raises(DatabaseBackupError) as exc_info:
            perform_backup(output_dir=backup_out, db_url=test_db_url, label="timeout", dump_timeout_seconds=1)
        assert "timed out" in str(exc_info.value).lower()

    assert list(backup_out.glob("*.tar.gz")) == []


def test_backup_fails_when_db_offline_and_redacts_secrets(tmp_path):
    """R18 + R16: Offline DB backup must raise DatabaseBackupError (not UnboundLocalError) and mask secrets."""
    backup_out = tmp_path / "backups"
    secret_url = "postgresql+psycopg://admin_user:S3cr3tP@ssw0rd!@127.0.0.1:1/absent_db?token=SuperSecretQueryTok99"
    with pytest.raises(DatabaseBackupError) as exc_info:
        perform_backup(output_dir=backup_out, db_url=secret_url, label="offline_test")

    msg = str(exc_info.value)
    assert "unreachable" in msg.lower()
    assert "S3cr3tP@ssw0rd!" not in msg
    assert "SuperSecretQueryTok99" not in msg
    assert "***" in msg


def test_restore_fails_when_psql_missing(tmp_path):
    """R01: Missing psql must raise DatabaseRestoreError rather than silently splitting SQL."""
    dump_file = tmp_path / "dump.sql"
    dump_file.write_text("CREATE TABLE should_not_run(id int);\n", encoding="utf-8")
    with patch.object(restore, "find_pg_tool", return_value=None):
        with pytest.raises(DatabaseRestoreError) as exc_info:
            restore_database(dump_file, test_db_url)
        assert "psql" in str(exc_info.value)


def test_restore_fails_on_invalid_sql_and_rolls_back_atomically(tmp_path, ensure_pg_bin_path):
    """R01: SQL error during psql restore must fail closed and roll back preceding DDL in the same dump."""
    bad_sql = tmp_path / "invalid_restore.sql"
    bad_sql.write_text(
        "CREATE TABLE review_restore_marker(id integer PRIMARY KEY);\n"
        "INSERT INTO non_existent_table_xyz VALUES (1);\n",
        encoding="utf-8",
    )
    with pytest.raises(DatabaseRestoreError) as exc_info:
        restore_database(bad_sql, test_db_url)
    assert "psql restore failed" in str(exc_info.value).lower()

    engine = create_engine(test_db_url)
    try:
        with engine.connect() as conn:
            marker = conn.execute(text("SELECT to_regclass('review_restore_marker')")).scalar()
            assert marker is None, "ON_ERROR_STOP + --single-transaction must roll back partial DDL on SQL failure"
    finally:
        engine.dispose()


def test_restore_fails_when_target_db_offline(tmp_path, ensure_pg_bin_path):
    """R01: perform_restore must fail closed when target database is offline."""
    backup_out = tmp_path / "backups"
    idx_dir = tmp_path / "idx"
    media_dir = tmp_path / "media"
    report = perform_backup(
        output_dir=backup_out,
        db_url=test_db_url,
        label="for_offline_restore",
        index_storage_dir=idx_dir,
        media_dir=media_dir,
    )
    archive_path = Path(report["archive_path"])

    offline_report = verify_backup_artifact(archive_path)
    assert offline_report["status"] == "verified_offline"

    offline_url = "postgresql+psycopg://offline_user:TopSecretPass@127.0.0.1:1/absent_db"
    with pytest.raises(DatabaseRestoreError) as exc_info:
        perform_restore(
            archive_path=archive_path,
            target_db_url=offline_url,
            index_storage_dir=tmp_path / "restore_idx",
            media_dir=tmp_path / "restore_media",
        )
    msg = str(exc_info.value)
    assert "unreachable" in msg.lower()
    assert "TopSecretPass" not in msg


def test_restore_fails_when_smoke_test_fails(tmp_path, ensure_pg_bin_path):
    """R01: If post-restore smoke verification fails, overall restore must fail."""
    backup_out = tmp_path / "backups"
    report = perform_backup(
        output_dir=backup_out,
        db_url=test_db_url,
        label="smoke_fail",
        index_storage_dir=tmp_path / "idx",
        media_dir=tmp_path / "media",
    )
    archive_path = Path(report["archive_path"])

    parsed = make_url(test_db_url)
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    smoke_db_name = f"folio_restore_drill_smoke_{os.getpid()}"
    smoke_target_url = parsed.set(database=smoke_db_name).render_as_string(hide_password=False)

    admin_eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_eng.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{smoke_db_name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{smoke_db_name}"'))

        with patch("src.backend.search.engine.SearchEngine.search", side_effect=RuntimeError("Simulated smoke search failure")):
            with pytest.raises(DatabaseRestoreError) as exc_info:
                perform_restore(
                    archive_path=archive_path,
                    target_db_url=smoke_target_url,
                    rebuild_index=True,
                    index_storage_dir=tmp_path / "restore_idx",
                    media_dir=tmp_path / "restore_media",
                )
            assert "smoke test failed" in str(exc_info.value).lower()
    finally:
        with admin_eng.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{smoke_db_name}" WITH (FORCE)'))
        admin_eng.dispose()


def test_restore_verifies_checksum_tampering(tmp_path):
    """verify_checksums must detect corrupted or tampered files and raise BackupIntegrityError."""
    mock_backup = tmp_path / "mock_backup"
    mock_backup.mkdir()
    data_file = mock_backup / "data.txt"
    data_file.write_text("authentic content", encoding="utf-8")

    checksum_file = mock_backup / "checksums.sha256"
    valid_hash = compute_sha256(data_file)
    checksum_file.write_text(f"{valid_hash}  data.txt\n", encoding="utf-8")

    verified = verify_checksums(mock_backup)
    assert verified["data.txt"] is True

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


def test_full_postgresql_backup_restore_and_drill_round_trip(tmp_path, ensure_pg_bin_path):
    """R01: Full round-trip backup + restore + parity drill into an isolated PostgreSQL database."""
    parsed = make_url(test_db_url)
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)

    # Guard against accidental protected target DB names
    with pytest.raises(RestoreDrillError):
        run_drill(admin_url=admin_url, source_db_url=test_db_url, target_db_name="folio")

    drill_report = run_drill(
        admin_url=admin_url,
        source_db_url=test_db_url,
        work_dir=tmp_path / "drill_work",
        source_index_dir=tmp_path / "src_idx",
        source_media_dir=tmp_path / "src_media",
    )

    assert drill_report["status"] == "passed"
    assert drill_report["verified_counts"]["documents_published"] >= 1
    assert drill_report["verified_counts"]["roles"] >= 5
    assert drill_report["verified_counts"]["tags"] >= 1
    assert drill_report["verified_constraints"]["has_open_report_partial_unique_index"] is True
    assert drill_report["smoke_test"]["search_smoke_test"]["status"] == "passed"
