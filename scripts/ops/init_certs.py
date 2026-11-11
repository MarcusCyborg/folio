#!/usr/bin/env python3
"""
Folio Reverse Proxy SSL Certificate Initialization, Import & Preflight Validation Tool.
Ensures folio.crt and folio.key exist and are valid for Nginx/Caddy proxy service.
Supports:
1. Generating self-signed local/staging SSL certificates with Subject Alternative Names (SANs).
2. Importing & validating production CA-signed certificates (--import-cert / --import-key).
3. Non-mutating --check-only verification (existence, PEM, expiry, key match, optional domain SAN check).
4. Non-clobbering defaults: never silently overwrites existing/partial certs unless --force is passed.
"""

import os
import re
import ssl
import sys
import argparse
import ipaddress
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    HAVE_CRYPTOGRAPHY = True
except ImportError:
    HAVE_CRYPTOGRAPHY = False


class CertificateError(Exception):
    """Base exception for certificate operations."""
    pass


class CertificateNotFoundError(CertificateError):
    """Raised when required certificate or private key is missing."""
    pass


class CertificateKeyMismatchError(CertificateError):
    """Raised when certificate public key does not match private key."""
    pass


class CertificateExpiredError(CertificateError):
    """Raised when certificate is expired or not yet valid."""
    pass


class CertificateDomainMismatchError(CertificateError):
    """Raised when certificate SAN/CN does not match expected domain."""
    pass


def _set_cert_permissions(cert_dir: Path, cert_path: Path, key_path: Path) -> None:
    """Enforces POSIX file permissions (0644 cert, 0600 private key) and folio UID ownership when root."""
    try:
        os.chmod(cert_path, 0o644)
    except OSError:
        pass
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            import pwd
            folio_uid = int(os.environ.get("CERT_OWNER_UID", pwd.getpwnam("folio").pw_uid))
            folio_gid = int(os.environ.get("CERT_OWNER_GID", pwd.getpwnam("folio").pw_gid))
            for p in (cert_dir, cert_path, key_path):
                os.chown(p, folio_uid, folio_gid)
        except Exception:
            pass


def _domain_matches(expected_domain: str, sans: List[str], common_name: Optional[str]) -> bool:
    """Checks whether expected_domain matches certificate SANs (or CN if SAN extension absent)."""
    expected = (expected_domain or "").strip().lower().rstrip(".")
    if not expected:
        return True

    candidates = [s.strip().lower().rstrip(".") for s in sans if s]
    if not candidates and common_name:
        candidates = [common_name.strip().lower().rstrip(".")]

    try:
        expected_ip = str(ipaddress.ip_address(expected))
    except ValueError:
        expected_ip = None

    for cand in candidates:
        if expected_ip is not None:
            try:
                if str(ipaddress.ip_address(cand)) == expected_ip:
                    return True
            except ValueError:
                continue
        if cand == expected:
            return True
        if cand.startswith("*.") and "." in expected:
            # RFC 6125 single-label wildcard match
            suffix = cand[1:]
            if expected.endswith(suffix) and expected.count(".") == cand.count("."):
                return True
    return False


_PEM_BEGIN_RE = re.compile(rb"^-----BEGIN ([A-Z0-9 ]+)-----$")
_PEM_END_RE = re.compile(rb"^-----END ([A-Z0-9 ]+)-----$")
_ALLOWED_CERT_PEM_LABELS = {b"CERTIFICATE", b"X509 CERTIFICATE"}
_ALLOWED_KEY_PEM_LABELS = {
    b"PRIVATE KEY",
    b"RSA PRIVATE KEY",
    b"EC PRIVATE KEY",
    b"DSA PRIVATE KEY",
    b"ENCRYPTED PRIVATE KEY",
    b"EC PARAMETERS",
}


def _scan_pem_blocks(pem_bytes: bytes, allowed_labels: set[bytes], file_label: str, kind: str) -> int:
    """
    Validates strict PEM block framing across the entire file payload.
    Rejects truncated blocks (missing END), nested BEGINs, stray ENDs,
    malformed header/footer lines, and unexpected PEM block types.
    """
    current_label: Optional[bytes] = None
    block_count = 0

    for line_no, raw_line in enumerate(pem_bytes.splitlines(), start=1):
        stripped = raw_line.strip()
        if b"-----BEGIN " in stripped or b"-----END " in stripped:
            begin_match = _PEM_BEGIN_RE.fullmatch(stripped)
            end_match = _PEM_END_RE.fullmatch(stripped)
            if begin_match:
                label = begin_match.group(1)
                if current_label is not None:
                    raise CertificateError(
                        f"Malformed PEM {kind} file {file_label} (line {line_no}): "
                        f"unexpected BEGIN '{label.decode('ascii', errors='replace')}' "
                        f"before END '{current_label.decode('ascii', errors='replace')}'"
                    )
                if label not in allowed_labels:
                    raise CertificateError(
                        f"Unexpected PEM block '{label.decode('ascii', errors='replace')}' "
                        f"in {kind} file {file_label} (line {line_no})"
                    )
                current_label = label
                block_count += 1
            elif end_match:
                label = end_match.group(1)
                if current_label is None or current_label != label:
                    raise CertificateError(
                        f"Malformed PEM {kind} file {file_label} (line {line_no}): "
                        f"unmatched END '{label.decode('ascii', errors='replace')}'"
                    )
                current_label = None
            else:
                raise CertificateError(
                    f"Malformed PEM boundary marker in {kind} file {file_label} (line {line_no})"
                )

    if current_label is not None:
        raise CertificateError(
            f"Truncated PEM {kind} block in {file_label}: "
            f"missing END '{current_label.decode('ascii', errors='replace')}'"
        )
    if block_count == 0:
        raise CertificateError(f"No PEM {kind} blocks found in {file_label}")

    return block_count


def _validate_pem_certificate_bundle(cert_bytes: bytes, cert_label: str) -> List[Any]:
    """Parses and validates every X.509 certificate block in a PEM fullchain bundle."""
    block_count = _scan_pem_blocks(cert_bytes, _ALLOWED_CERT_PEM_LABELS, cert_label, "certificate")

    try:
        if hasattr(x509, "load_pem_x509_certificates"):
            certs = x509.load_pem_x509_certificates(cert_bytes)
        else:
            certs = [x509.load_pem_x509_certificate(cert_bytes)]
    except Exception as e:
        raise CertificateError(f"Failed to parse PEM certificate bundle {cert_label}: {e}")

    if len(certs) != block_count or not certs:
        raise CertificateError(
            f"Malformed certificate block(s) in {cert_label}: "
            f"parsed {len(certs)} of {block_count} PEM certificate block(s)"
        )
    return certs


def _validate_pem_private_key(key_bytes: bytes, key_label: str) -> Any:
    """Validates PEM private key framing and decodes an unencrypted private key."""
    _scan_pem_blocks(key_bytes, _ALLOWED_KEY_PEM_LABELS, key_label, "private key")
    try:
        return serialization.load_pem_private_key(key_bytes, password=None)
    except Exception as e:
        raise CertificateError(f"Failed to parse PEM private key {key_label}: {e}")


def _validate_cert_and_key_paths(
    cert_path: Path,
    key_path: Path,
    expected_domain: Optional[str] = None,
    cert_label: Optional[str] = None,
    key_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validates certificate bundle and private key files at arbitrary paths.
    Checks existence, complete PEM/DER decoding of all blocks in the bundle,
    leaf validity period, public/private key match, optional domain match,
    and OpenSSL SSLContext.load_cert_chain loadability.
    """
    if not HAVE_CRYPTOGRAPHY:
        raise CertificateError("The 'cryptography' library is required to verify certificates.")

    disp_cert = cert_label or str(cert_path)
    disp_key = key_label or str(key_path)

    if not cert_path.exists():
        raise CertificateNotFoundError(
            f"Missing certificate file: {disp_cert}. "
            "Provision local/staging self-signed TLS via 'cert-init' or import production CA certificates "
            "via '--import-cert <fullchain.pem> --import-key <privkey.pem>'."
        )
    if not key_path.exists():
        raise CertificateNotFoundError(
            f"Missing private key file: {disp_key}. "
            "Provision local/staging self-signed TLS via 'cert-init' or import production CA certificates "
            "via '--import-cert <fullchain.pem> --import-key <privkey.pem>'."
        )
    if not cert_path.is_file():
        raise CertificateError(f"Certificate path is not a regular file: {disp_cert}")
    if not key_path.is_file():
        raise CertificateError(f"Private key path is not a regular file: {disp_key}")

    try:
        cert_bytes = cert_path.read_bytes()
    except OSError as e:
        raise CertificateError(f"Failed to read certificate file {disp_cert}: {e}")
    try:
        key_bytes = key_path.read_bytes()
    except OSError as e:
        raise CertificateError(f"Failed to read private key file {disp_key}: {e}")

    certs = _validate_pem_certificate_bundle(cert_bytes, disp_cert)
    cert = certs[0]
    key = _validate_pem_private_key(key_bytes, disp_key)

    now = datetime.now(timezone.utc)
    valid_from = cert.not_valid_before_utc
    valid_to = cert.not_valid_after_utc

    if now < valid_from:
        raise CertificateExpiredError(
            f"Certificate is not yet valid (valid from {valid_from.isoformat()}, current {now.isoformat()})"
        )
    if now > valid_to:
        raise CertificateExpiredError(
            f"Certificate has expired on {valid_to.isoformat()} (current {now.isoformat()})"
        )

    cert_pub_bytes = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_pub_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if cert_pub_bytes != key_pub_bytes:
        raise CertificateKeyMismatchError(
            f"Public key in {disp_cert} does not match private key in {disp_key}"
        )

    sans_list: List[str] = []
    try:
        san_ext = cert.extensions.get_extension_for_oid(x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        for val in san_ext.value:
            sans_list.append(str(val.value))
    except x509.ExtensionNotFound:
        pass

    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    common_name = str(cn_attrs[0].value) if cn_attrs else None

    if expected_domain and not _domain_matches(expected_domain, sans_list, common_name):
        raise CertificateDomainMismatchError(
            f"Certificate SAN/CN ({', '.join(sans_list) or common_name or '<none>'}) "
            f"does not match expected domain '{expected_domain}'"
        )

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path), password="")
    except Exception as e:
        raise CertificateError(
            f"OpenSSL failed to load certificate chain and key pair ({disp_cert}, {disp_key}): {e}"
        )

    fingerprint = cert.fingerprint(hashes.SHA256()).hex()

    return {
        "status": "valid",
        "cert_path": str(cert_path),
        "key_path": str(key_path),
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "days_remaining": (valid_to - now).days,
        "sha256_fingerprint": fingerprint,
        "sans": sans_list,
        "chain_length": len(certs),
    }


def generate_self_signed_cert(
    cert_dir: Path,
    domain: str = "localhost",
    staging_domain: str = "staging.localhost",
    extra_sans: Optional[List[str]] = None,
    days: int = 365,
    force: bool = False,
    expected_domain: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generates a self-signed RSA-2048 certificate and private key for local/staging use.
    Writes folio.crt and folio.key into cert_dir.
    Never overwrites existing or partial files unless force=True.
    """
    if not HAVE_CRYPTOGRAPHY:
        raise CertificateError(
            "The 'cryptography' library is required to generate SSL certificates. "
            "Please ensure it is installed in the active environment."
        )

    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "folio.crt"
    key_path = cert_dir / "folio.key"

    if cert_path.exists() and key_path.exists() and not force:
        print(f"[INFO] Certificate files already exist in {cert_dir}. Verifying without overwriting...")
        target_domain = expected_domain if expected_domain is not None else domain
        return verify_certificates(cert_dir, expected_domain=target_domain)

    if (cert_path.exists() or key_path.exists()) and not force:
        present = cert_path if cert_path.exists() else key_path
        missing = key_path if cert_path.exists() else cert_path
        raise CertificateNotFoundError(
            f"Incomplete certificate state in {cert_dir}: {present.name} exists without {missing.name}. "
            "Refusing to overwrite existing file without --force."
        )

    print(f"[INFO] Generating self-signed local/staging SSL certificate for domain: {domain} ...")

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Folio Local/Staging Self-Signed"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Engineering Operations"),
        x509.NameAttribute(NameOID.COMMON_NAME, domain),
    ])

    san_entries: List[x509.GeneralName] = []
    seen_sans = set()

    raw_sans = [domain, staging_domain, "localhost", "127.0.0.1", "::1"]
    if extra_sans:
        raw_sans.extend(extra_sans)

    for item in raw_sans:
        if not item or item in seen_sans:
            continue
        seen_sans.add(item)
        try:
            ip = ipaddress.ip_address(item)
            san_entries.append(x509.IPAddress(ip))
        except ValueError:
            san_entries.append(x509.DNSName(item))

    now = datetime.now(timezone.utc)
    not_valid_before = now - timedelta(minutes=5)
    not_valid_after = now + timedelta(days=days)

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.SERVER_AUTH,
                ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(san_entries),
            critical=False,
        )
    )

    cert = builder.sign(private_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    tmp_cert = cert_dir / ".folio.crt.tmp"
    tmp_key = cert_dir / ".folio.key.tmp"
    tmp_cert.write_bytes(cert_pem)
    tmp_key.write_bytes(key_pem)
    _set_cert_permissions(cert_dir, tmp_cert, tmp_key)
    tmp_cert.replace(cert_path)
    tmp_key.replace(key_path)
    _set_cert_permissions(cert_dir, cert_path, key_path)

    print(f"[OK] SSL certificate written to: {cert_path}")
    print(f"[OK] SSL private key written to:  {key_path}")

    return verify_certificates(cert_dir, expected_domain=expected_domain or domain)


def install_certificate_pair(
    cert_dir: Path,
    source_cert: Path,
    source_key: Path,
    expected_domain: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Validates an externally issued (e.g. Let's Encrypt / CA) fullchain certificate & private key pair
    from an isolated temporary staging copy (including all PEM/X.509 blocks and OpenSSL SSLContext
    loadability) before touching cert_dir, then installs them as folio.crt and folio.key.
    Fails closed before touching cert_dir if source files are invalid, truncated, expired, mismatched,
    or wrong domain. Refuses to overwrite existing files unless force=True.
    Note: folio.crt and folio.key are replaced via two sequential per-file atomic renames, not a
    cross-file atomic transaction; run preflight/reload only after import completes.
    """
    cert_dir = Path(cert_dir)
    source_cert = Path(source_cert)
    source_key = Path(source_key)

    if not source_cert.exists() or not source_key.exists():
        _validate_cert_and_key_paths(source_cert, source_key, expected_domain=expected_domain)
    if not source_cert.is_file():
        raise CertificateError(f"Certificate path is not a regular file: {source_cert}")
    if not source_key.is_file():
        raise CertificateError(f"Private key path is not a regular file: {source_key}")

    try:
        cert_bytes = source_cert.read_bytes()
    except OSError as e:
        raise CertificateError(f"Failed to read certificate file {source_cert}: {e}")
    try:
        key_bytes = source_key.read_bytes()
    except OSError as e:
        raise CertificateError(f"Failed to read private key file {source_key}: {e}")

    with tempfile.TemporaryDirectory(prefix="folio-cert-stage-") as stage_dir:
        stage_path = Path(stage_dir)
        staged_cert = stage_path / "folio.crt"
        staged_key = stage_path / "folio.key"
        staged_cert.write_bytes(cert_bytes)
        staged_key.write_bytes(key_bytes)
        try:
            os.chmod(staged_key, 0o600)
        except OSError:
            pass
        _validate_cert_and_key_paths(
            staged_cert,
            staged_key,
            expected_domain=expected_domain,
            cert_label=str(source_cert),
            key_label=str(source_key),
        )

    cert_path = cert_dir / "folio.crt"
    key_path = cert_dir / "folio.key"

    if (cert_path.exists() or key_path.exists()) and not force:
        if cert_path.exists() and key_path.exists():
            raise CertificateError(
                f"Certificate files already exist in {cert_dir}. Pass --force to replace or renew existing certificates."
            )
        present = cert_path if cert_path.exists() else key_path
        missing = key_path if cert_path.exists() else cert_path
        raise CertificateNotFoundError(
            f"Incomplete certificate state in {cert_dir}: {present.name} exists without {missing.name}. "
            "Pass --force to replace."
        )

    cert_dir.mkdir(parents=True, exist_ok=True)
    tmp_cert = cert_dir / ".folio.crt.tmp"
    tmp_key = cert_dir / ".folio.key.tmp"
    try:
        tmp_cert.write_bytes(cert_bytes)
        tmp_key.write_bytes(key_bytes)
        _set_cert_permissions(cert_dir, tmp_cert, tmp_key)
        # Sequential per-file atomic renames (not a cross-file atomic pair transaction)
        tmp_cert.replace(cert_path)
        tmp_key.replace(key_path)
        _set_cert_permissions(cert_dir, cert_path, key_path)
    finally:
        for leftover in (tmp_cert, tmp_key):
            if leftover.exists():
                try:
                    leftover.unlink()
                except OSError:
                    pass

    print(f"[OK] Imported certificate to: {cert_path}")
    print(f"[OK] Imported private key to: {key_path}")

    return verify_certificates(cert_dir, expected_domain=expected_domain)


def verify_certificates(cert_dir: Path, expected_domain: Optional[str] = None) -> Dict[str, Any]:
    """
    Verifies that folio.crt and folio.key exist in cert_dir, are valid PEM, have not expired,
    have matching public/private keys, and optionally cover expected_domain.
    """
    cert_dir = Path(cert_dir)
    return _validate_cert_and_key_paths(
        cert_dir / "folio.crt",
        cert_dir / "folio.key",
        expected_domain=expected_domain,
    )


def main():
    env_cert_dir = os.environ.get("CERT_DIR", "").strip()
    default_cert_dir = Path(env_cert_dir) if env_cert_dir else (PROJECT_ROOT / "docker" / "proxy" / "certs")
    default_domain = os.environ.get("DOMAIN_NAME", "localhost")
    default_staging = os.environ.get("STAGING_DOMAIN", "staging.localhost")
    default_expected_domain = os.environ.get("CERT_EXPECTED_DOMAIN", "").strip() or None

    parser = argparse.ArgumentParser(
        description="Folio Reverse Proxy SSL Certificate Tool (P08 / Round 4 Operations)"
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=default_cert_dir,
        help=f"Target directory for folio.crt and folio.key (default: {default_cert_dir})",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=default_domain,
        help=f"Primary domain name for generated certificate Subject CN (default: {default_domain})",
    )
    parser.add_argument(
        "--staging-domain",
        type=str,
        default=default_staging,
        help=f"Secondary staging domain for generated SAN (default: {default_staging})",
    )
    parser.add_argument(
        "--expected-domain",
        type=str,
        default=default_expected_domain,
        help="Optional domain/IP that verified or imported certificates must cover via SAN or CN",
    )
    parser.add_argument(
        "--san",
        action="append",
        dest="extra_sans",
        help="Additional Subject Alternative Names (can be repeated)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Self-signed certificate validity period in days (default: 365)",
    )
    parser.add_argument(
        "--import-cert",
        type=Path,
        default=None,
        help="Path to an existing CA-issued certificate PEM (e.g. fullchain.pem) to install as folio.crt",
    )
    parser.add_argument(
        "--import-key",
        type=Path,
        default=None,
        help="Path to the matching private key PEM (e.g. privkey.pem) to install as folio.key",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing certificates (use explicitly for renewal or replacement)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify existing certificates without generating or overwriting",
    )

    args = parser.parse_args()

    if (args.import_cert is None) != (args.import_key is None):
        parser.error("--import-cert and --import-key must be provided together.")

    try:
        if args.check_only:
            print(f"[INFO] Performing certificate pre-flight check in: {args.cert_dir}")
            info = verify_certificates(args.cert_dir, expected_domain=args.expected_domain)
            print("[OK] Certificate validation PASSED:")
            print(f"  + Subject:     {info['subject']}")
            print(f"  + SANs:        {', '.join(info['sans'])}")
            print(f"  + Valid Until: {info['valid_to']} ({info['days_remaining']} days remaining)")
            print(f"  + SHA-256:     {info['sha256_fingerprint']}")
            sys.exit(0)
        elif args.import_cert is not None and args.import_key is not None:
            info = install_certificate_pair(
                cert_dir=args.cert_dir,
                source_cert=args.import_cert,
                source_key=args.import_key,
                expected_domain=args.expected_domain,
                force=args.force,
            )
            print("[OK] Production/custom certificate installed and verified:")
            print(f"  + Subject:     {info['subject']}")
            print(f"  + SANs:        {', '.join(info['sans'])}")
            print(f"  + Valid Until: {info['valid_to']} ({info['days_remaining']} days remaining)")
            print(f"  + SHA-256:     {info['sha256_fingerprint']}")
            sys.exit(0)
        else:
            info = generate_self_signed_cert(
                cert_dir=args.cert_dir,
                domain=args.domain,
                staging_domain=args.staging_domain,
                extra_sans=args.extra_sans,
                days=args.days,
                force=args.force,
                expected_domain=args.expected_domain,
            )
            print("[OK] Certificate setup verified successfully:")
            print(f"  + Subject:     {info['subject']}")
            print(f"  + SANs:        {', '.join(info['sans'])}")
            print(f"  + Valid Until: {info['valid_to']} ({info['days_remaining']} days remaining)")
            print(f"  + SHA-256:     {info['sha256_fingerprint']}")
            sys.exit(0)
    except Exception as exc:
        print(f"[ERROR] Certificate operation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
