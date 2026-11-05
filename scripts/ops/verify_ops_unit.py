#!/usr/bin/env python3
"""
Direct unit test runner for Folio P08 Operations, Health, Worker, and Disaster Recovery.
Runs pure unit tests independently of ambient database connectivity.
"""
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.main import app
from src.backend.models.search_index import IndexJob
from src.backend.search_index.worker import IndexWorker
from scripts.ops.backup import perform_backup, compute_sha256
from scripts.ops.restore import perform_restore, verify_checksums, BackupIntegrityError
from scripts.ops.init_certs import (
    generate_self_signed_cert,
    verify_certificates,
    CertificateError,
    CertificateNotFoundError,
    CertificateKeyMismatchError,
    CertificateExpiredError,
)


def run_checks():
    client = TestClient(app)
    results = []

    # 1. Liveness Probe
    res = client.get("/health/live")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "alive"
    assert data["app"] == "folio"
    assert "timestamp" in data
    results.append("test_liveness_probe: PASSED")

    # 2. Request ID Generation
    assert "X-Request-ID" in res.headers
    assert len(res.headers["X-Request-ID"]) >= 16
    results.append("test_request_id_generated: PASSED")

    # 3. Request ID Propagation
    custom_id = "test-custom-proxy-id-445566"
    res2 = client.get("/health/live", headers={"X-Request-ID": custom_id})
    assert res2.headers.get("X-Request-ID") == custom_id
    results.append("test_request_id_propagated: PASSED")

    # 4. Security Headers & CSP
    h = res.headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in h
    assert "default-src 'self'" in h["Content-Security-Policy"]
    results.append("test_security_headers_and_csp: PASSED")

    # 5. Readiness Probe DB Unavailable (503)
    mock_db = MagicMock(spec=Session)
    mock_db.execute.side_effect = OperationalError("connection refused", {}, None)
    from src.backend.core.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        res_fail = client.get("/health/ready")
        assert res_fail.status_code == 503
        d_fail = res_fail.json()
        assert d_fail["status"] == "unavailable"
        assert d_fail["database"] == "unavailable"
        results.append("test_readiness_probe_503_on_db_down: PASSED")
    finally:
        app.dependency_overrides.pop(get_db, None)

    # 6. Worker Metrics Calculation Unit Test
    mock_db_metrics = MagicMock(spec=Session)
    q_mock = MagicMock()
    mock_db_metrics.query.return_value = q_mock
    f_mock = MagicMock()
    q_mock.filter.return_value = f_mock
    f_mock.scalar.side_effect = [5, 2, 1, 100]
    ord_mock = MagicMock()
    f_mock.order_by.return_value = ord_mock
    ord_mock.first.return_value = (datetime.now(timezone.utc),)
    m = IndexWorker.get_metrics(mock_db_metrics)
    assert m["pending_jobs"] == 5
    assert m["processing_jobs"] == 2
    assert m["failed_jobs_dlq"] == 1
    assert m["completed_jobs"] == 100
    results.append("test_worker_metrics_calculation: PASSED")

    # 7. Worker Stale Lock Crash Recovery
    stuck_job = IndexJob(
        id="job-stuck-1",
        document_id="doc-1",
        revision_hash="hash1",
        operation="upsert",
        state="processing",
        locked_at=datetime.now(timezone.utc) - timedelta(seconds=120),
        locked_by="crashed-worker",
    )
    mock_db_recover = MagicMock(spec=Session)
    mock_db_recover.query.return_value.filter.return_value.all.return_value = [stuck_job]
    worker = IndexWorker(worker_id="test-recovery-worker", lock_timeout_sec=60.0)
    recovered_count = worker.recover_stale_locks(mock_db_recover)
    assert recovered_count == 1
    assert stuck_job.state == "pending"
    assert stuck_job.locked_at is None
    results.append("test_worker_crash_stale_lock_recovery: PASSED")

    # 8. Worker Daemon Max Iterations
    mock_db_daemon = MagicMock(spec=Session)
    mock_db_daemon.query.return_value.filter.return_value.all.return_value = []
    mock_db_daemon.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    w_daemon = IndexWorker(worker_id="test-daemon")
    total_processed = w_daemon.run_daemon(
        poll_interval=0.01,
        batch_size=5,
        max_iterations=2,
        session_factory=lambda: mock_db_daemon,
    )
    assert total_processed == 0
    results.append("test_worker_daemon_max_iterations: PASSED")

    # 9. Backup & Restore Cycle
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        b_res = perform_backup(output_dir=p / "backups", label="unit")
        assert b_res["status"] == "success"
        archive_path = Path(b_res["archive_path"])
        assert archive_path.exists()

        r_res = perform_restore(archive_path=archive_path, skip_smoke_test=True)
        assert r_res["status"] == "success"
        assert r_res["verified_files_count"] >= 1
        results.append("test_backup_restore_cycle: PASSED")

    # 10. Restore Checksum Tampering Rejection
    with tempfile.TemporaryDirectory() as tmp:
        mock_b = Path(tmp) / "tamper_test"
        mock_b.mkdir()
        df = mock_b / "data.sql"
        df.write_text("SELECT 1;", encoding="utf-8")
        chk = mock_b / "checksums.sha256"
        chk.write_text(f"{compute_sha256(df)}  data.sql\n", encoding="utf-8")
        assert verify_checksums(mock_b)["data.sql"] is True

        # Tamper
        df.write_text("MALICIOUS SQL PAYLOAD;", encoding="utf-8")
        try:
            verify_checksums(mock_b)
            raise AssertionError("Should have failed")
        except BackupIntegrityError:
            pass
        results.append("test_restore_tamper_detection: PASSED")

    # 11. Gitattributes Line Endings Safeguard Unit Test (P08-P2-01)
    ga_path = PROJECT_ROOT / ".gitattributes"
    assert ga_path.exists(), "Missing .gitattributes"
    ga_text = ga_path.read_text(encoding="utf-8")
    assert "*.sh" in ga_text and "eol=lf" in ga_text, ".gitattributes must enforce *.sh text eol=lf"
    for sh_file in PROJECT_ROOT.rglob("*.sh"):
        if ".git" in sh_file.parts:
            continue
        assert b"\r" not in sh_file.read_bytes(), f"CRLF carriage return detected in {sh_file}"
    results.append("test_gitattributes_line_endings_safeguard: PASSED")

    # 12. SSL Certificate Generation & Verification Unit Test (P08-P2-02)
    with tempfile.TemporaryDirectory() as tmp_cert:
        p_cert = Path(tmp_cert)
        cert_res = generate_self_signed_cert(
            cert_dir=p_cert,
            domain="unit-test.folio.local",
            staging_domain="staging.unit-test.local",
            days=90,
        )
        assert cert_res["status"] == "valid"
        assert (p_cert / "folio.crt").exists()
        assert (p_cert / "folio.key").exists()
        assert "CN=unit-test.folio.local" in cert_res["subject"]
        assert "unit-test.folio.local" in cert_res["sans"]
        assert "127.0.0.1" in cert_res["sans"]
        assert cert_res["days_remaining"] >= 89

        v_res = verify_certificates(p_cert)
        assert v_res["status"] == "valid"
        assert v_res["sha256_fingerprint"] == cert_res["sha256_fingerprint"]
        results.append("test_ssl_certificate_generation_and_verification: PASSED")

    # 13. SSL Certificate Tamper, Expiry & Key Mismatch Detection (P08-P2-02)
    with tempfile.TemporaryDirectory() as tmp_cert_tamper:
        p_tamper = Path(tmp_cert_tamper)
        # 13a. Missing files
        try:
            verify_certificates(p_tamper)
            raise AssertionError("Should fail on missing cert files")
        except CertificateNotFoundError:
            pass

        # 13b. Generate valid and tamper key
        generate_self_signed_cert(cert_dir=p_tamper, domain="tamper.folio.local")
        with tempfile.TemporaryDirectory() as tmp_other:
            p_other = Path(tmp_other)
            generate_self_signed_cert(cert_dir=p_other, domain="other.folio.local")
            # Replace key with mismatched key
            (p_tamper / "folio.key").write_bytes((p_other / "folio.key").read_bytes())
            try:
                verify_certificates(p_tamper)
                raise AssertionError("Should fail on key mismatch")
            except CertificateKeyMismatchError:
                pass

        # 13c. Expired certificate
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        expired_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now_utc = datetime.now(timezone.utc)
        expired_cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "expired.local")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "expired.local")]))
            .public_key(expired_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now_utc - timedelta(days=400))
            .not_valid_after(now_utc - timedelta(days=35))
            .sign(expired_key, hashes.SHA256())
        )
        with tempfile.TemporaryDirectory() as tmp_exp:
            p_exp = Path(tmp_exp)
            (p_exp / "folio.crt").write_bytes(expired_cert.public_bytes(serialization.Encoding.PEM))
            (p_exp / "folio.key").write_bytes(
                expired_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            try:
                verify_certificates(p_exp)
                raise AssertionError("Should fail on expired cert")
            except CertificateExpiredError:
                pass

        results.append("test_ssl_certificate_tamper_and_expiry_detection: PASSED")

    for r in results:
        print(f"  [OK] {r}")

    print(f"\nAll {len(results)} ops & disaster recovery unit tests PASSED successfully!")


if __name__ == "__main__":
    run_checks()
