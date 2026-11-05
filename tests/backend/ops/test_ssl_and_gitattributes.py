import os
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from scripts.ops.init_certs import (
    generate_self_signed_cert,
    verify_certificates,
    CertificateNotFoundError,
    CertificateKeyMismatchError,
    CertificateExpiredError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_gitattributes_present_and_enforces_lf_for_shell():
    """Verify that .gitattributes exists at project root and enforces LF line endings for shell scripts."""
    ga_path = PROJECT_ROOT / ".gitattributes"
    assert ga_path.exists(), "Missing .gitattributes in project root"
    content = ga_path.read_text(encoding="utf-8")
    assert "*.sh" in content
    assert "eol=lf" in content

    # All tracked shell scripts must not have CRLF
    for sh_file in PROJECT_ROOT.rglob("*.sh"):
        if ".git" in sh_file.parts:
            continue
        raw_bytes = sh_file.read_bytes()
        assert b"\r" not in raw_bytes, f"CRLF byte found in shell script: {sh_file}"


def test_init_certs_generates_valid_certificate_and_key(tmp_path):
    """generate_self_signed_cert produces valid PEM files with correct Subject and SANs."""
    cert_dir = tmp_path / "certs"
    result = generate_self_signed_cert(
        cert_dir=cert_dir,
        domain="folio.example.com",
        staging_domain="staging.folio.example.com",
        days=180,
    )

    assert result["status"] == "valid"
    assert (cert_dir / "folio.crt").exists()
    assert (cert_dir / "folio.key").exists()
    assert "CN=folio.example.com" in result["subject"]
    assert "folio.example.com" in result["sans"]
    assert "staging.folio.example.com" in result["sans"]
    assert "localhost" in result["sans"]
    assert "127.0.0.1" in result["sans"]
    assert result["days_remaining"] >= 179


def test_init_certs_check_only_validates_healthy_certificates(tmp_path):
    """verify_certificates returns valid summary for generated certificates."""
    cert_dir = tmp_path / "certs"
    generate_self_signed_cert(cert_dir=cert_dir, domain="proxy.test")

    verified = verify_certificates(cert_dir)
    assert verified["status"] == "valid"
    assert len(verified["sha256_fingerprint"]) == 64
    assert (cert_dir / "folio.crt").stat().st_size > 0
    assert (cert_dir / "folio.key").stat().st_size > 0


def test_init_certs_detects_tampered_or_mismatched_key(tmp_path):
    """verify_certificates raises CertificateKeyMismatchError if key does not match cert."""
    dir_a = tmp_path / "certs_a"
    dir_b = tmp_path / "certs_b"
    generate_self_signed_cert(cert_dir=dir_a, domain="a.test")
    generate_self_signed_cert(cert_dir=dir_b, domain="b.test")

    # Mismatched key swap
    (dir_a / "folio.key").write_bytes((dir_b / "folio.key").read_bytes())
    with pytest.raises(CertificateKeyMismatchError):
        verify_certificates(dir_a)


def test_init_certs_detects_missing_certificates(tmp_path):
    """verify_certificates raises CertificateNotFoundError if cert or key file is absent."""
    empty_dir = tmp_path / "empty_certs"
    empty_dir.mkdir()
    with pytest.raises(CertificateNotFoundError):
        verify_certificates(empty_dir)
