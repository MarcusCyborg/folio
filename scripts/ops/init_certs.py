#!/usr/bin/env python3
"""
Folio Reverse Proxy SSL Certificate Initialization & Validation Tool.
Ensures folio.crt and folio.key exist and are valid for Nginx/Caddy proxy service.
Supports:
1. Generating self-signed development/staging SSL certificates with Subject Alternative Names (SANs).
2. Verifying existing certificates (validity dates, SANs, and private key matching).
3. Non-mutating --check-only verification for pre-flight deployment audits.
"""

import os
import sys
import argparse
import ipaddress
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


def generate_self_signed_cert(
    cert_dir: Path,
    domain: str = "localhost",
    staging_domain: str = "staging.localhost",
    extra_sans: Optional[List[str]] = None,
    days: int = 365,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Generates a high-security self-signed RSA-2048 certificate and private key.
    Writes folio.crt and folio.key into cert_dir.
    """
    if not HAVE_CRYPTOGRAPHY:
        raise CertificateError(
            "The 'cryptography' library is required to generate SSL certificates. "
            "Please ensure it is installed in the active environment."
        )

    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "folio.crt"
    key_path = cert_dir / "folio.key"

    if cert_path.exists() and key_path.exists() and not force:
        # Existing certificates present; verify instead of clobbering
        print(f"[INFO] Certificate files already exist in {cert_dir}. Verifying...")
        return verify_certificates(cert_dir)

    print(f"[INFO] Generating self-signed SSL certificate for domain: {domain} ...")

    # 1. Generate RSA Private Key (2048-bit)
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 2. Build Subject & Issuer Names
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Folio Development"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Engineering Operations"),
        x509.NameAttribute(NameOID.COMMON_NAME, domain),
    ])

    # 3. Build Subject Alternative Names (SANs)
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

    # 4. Validity period
    now = datetime.now(timezone.utc)
    not_valid_before = now - timedelta(minutes=5)
    not_valid_after = now + timedelta(days=days)

    # 5. Build X.509 Certificate
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

    # 6. Serialize PEM outputs
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # 7. Write to disk
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)

    # Restrict permissions on private key on POSIX systems
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass

    print(f"[OK] SSL certificate written to: {cert_path}")
    print(f"[OK] SSL private key written to:  {key_path}")

    return verify_certificates(cert_dir)


def verify_certificates(cert_dir: Path) -> Dict[str, Any]:
    """
    Verifies that folio.crt and folio.key exist, are valid PEM, have not expired,
    and have matching public/private keys.
    """
    if not HAVE_CRYPTOGRAPHY:
        raise CertificateError("The 'cryptography' library is required to verify certificates.")

    cert_path = cert_dir / "folio.crt"
    key_path = cert_dir / "folio.key"

    if not cert_path.exists():
        raise CertificateNotFoundError(f"Missing certificate file: {cert_path}")
    if not key_path.exists():
        raise CertificateNotFoundError(f"Missing private key file: {key_path}")

    # Load Certificate
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except Exception as e:
        raise CertificateError(f"Failed to parse PEM certificate {cert_path}: {e}")

    # Load Private Key
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except Exception as e:
        raise CertificateError(f"Failed to parse PEM private key {key_path}: {e}")

    now = datetime.now(timezone.utc)

    # Check validity dates
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

    # Check key-pair match
    cert_pub_numbers = cert.public_key().public_numbers()
    key_pub_numbers = key.public_key().public_numbers()
    if cert_pub_numbers != key_pub_numbers:
        raise CertificateKeyMismatchError(
            f"Public key in {cert_path} does not match private key in {key_path}"
        )

    # Extract SANs
    sans_list = []
    try:
        san_ext = cert.extensions.get_extension_for_oid(x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        for val in san_ext.value:
            sans_list.append(str(val.value))
    except x509.ExtensionNotFound:
        pass

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
    }


def main():
    default_cert_dir = PROJECT_ROOT / "docker" / "proxy" / "certs"
    default_domain = os.environ.get("DOMAIN_NAME", "localhost")
    default_staging = os.environ.get("STAGING_DOMAIN", "staging.localhost")

    parser = argparse.ArgumentParser(
        description="Folio Reverse Proxy SSL Certificate Tool (P08 / Operations)"
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
        help=f"Primary domain name for certificate Subject CN (default: {default_domain})",
    )
    parser.add_argument(
        "--staging-domain",
        type=str,
        default=default_staging,
        help=f"Secondary staging domain for SAN (default: {default_staging})",
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
        help="Certificate validity period in days (default: 365)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing certificates",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify existing certificates without generating new ones",
    )

    args = parser.parse_args()

    try:
        if args.check_only:
            print(f"[INFO] Performing certificate pre-flight check in: {args.cert_dir}")
            info = verify_certificates(args.cert_dir)
            print("[OK] Certificate validation PASSED:")
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
