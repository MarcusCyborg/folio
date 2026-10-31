import hashlib
import hmac
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=2,
    hash_len=32,
    salt_len=16
)

def hash_password(password: str) -> str:
    """Hashes a password using Argon2id."""
    return ph.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    """Verifies a password against an Argon2id hash."""
    try:
        return ph.verify(hashed, password)
    except (VerifyMismatchError, VerificationError):
        return False

def generate_session_token() -> str:
    """Generates an opaque, high-entropy raw session token (256 bits)."""
    return secrets.token_hex(32)

def hash_session_token(token: str) -> str:
    """Hashes a session token with SHA-256 for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def generate_csrf_token() -> str:
    """Generates a random CSRF token."""
    return secrets.token_hex(32)

def generate_actor_key() -> str:
    """Generates an opaque actor key for anonymous or authenticated browser linking."""
    return secrets.token_hex(32)

def constant_time_compare(val1: str, val2: str) -> bool:
    """Constant-time string comparison against timing attacks."""
    return hmac.compare_digest(val1.encode("utf-8"), val2.encode("utf-8"))
