import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load .env file from project root if it exists
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

VALID_ENVIRONMENTS = {"development", "test", "staging", "production"}
ENV_ALIASES = {
    "dev": "development",
    "local": "development",
    "testing": "test",
    "stage": "staging",
    "prod": "production",
}

def normalize_database_url(url: str) -> str:
    """Use the installed psycopg driver for provider-issued PostgreSQL URLs."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url

def normalize_env(raw_env: str) -> str:
    cleaned = (raw_env or "development").strip().lower()
    return ENV_ALIASES.get(cleaned, cleaned)

def parse_cors_origins(raw_origins: str, env: str) -> List[str]:
    if raw_origins and raw_origins.strip():
        return [o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()]
    
    if env == "development":
        return [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    elif env == "test":
        return ["http://testserver", "http://localhost"]
    
    # In production or staging, default to empty list (same-origin only)
    return []

class Settings:
    def __init__(self):
        self.PROJECT_ROOT: Path = PROJECT_ROOT
        self.APP_ENV: str = normalize_env(os.getenv("APP_ENV", "development"))
        self.APP_SECRET: str = os.getenv("APP_SECRET", "folio_dev_insecure_secret_key_change_in_production_32bytes_min")
        self.DATABASE_URL: str = normalize_database_url(os.getenv("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/folio"))
        self.TEST_DATABASE_URL: str = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/folio_test")
        self.COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
        self.COOKIE_SAMESITE: str = os.getenv("COOKIE_SAMESITE", "lax").lower()
        self.ENABLE_LEGACY_SEARCH: bool = os.getenv("ENABLE_LEGACY_SEARCH", "false").lower() in ("true", "1", "yes")
        self.DEMO_PASSWORD: str = os.getenv("DEMO_PASSWORD", "FolioDemo2026!")
        self.SESSION_COOKIE_NAME: str = "folio_session"
        self.SESSION_MAX_AGE_DAYS: int = 7
        
        # CORS & Origin settings
        self.CORS_ALLOWED_ORIGINS: List[str] = parse_cors_origins(
            os.getenv("CORS_ALLOWED_ORIGINS", ""),
            self.APP_ENV,
        )

        # Reverse Proxy & Trusted Proxy Headers
        raw_proxies = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1")
        self.TRUSTED_PROXIES: List[str] = [p.strip() for p in raw_proxies.split(",") if p.strip()]

        # Rate Limiting Configuration
        self.RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
        self.RATE_LIMIT_LOGIN_MAX_FAILED: int = int(os.getenv("RATE_LIMIT_LOGIN_MAX_FAILED", "5"))
        self.RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "60"))
        self.RATE_LIMIT_REGISTER_MAX: int = int(os.getenv("RATE_LIMIT_REGISTER_MAX", "10"))
        self.RATE_LIMIT_REGISTER_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_REGISTER_WINDOW_SECONDS", "60"))
        self.RATE_LIMIT_SEARCH_MAX: int = int(os.getenv("RATE_LIMIT_SEARCH_MAX", "60"))
        self.RATE_LIMIT_SEARCH_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_SEARCH_WINDOW_SECONDS", "60"))

        # P05 Search & Semantic Engine Configuration
        self.SEARCH_CONTEXT_TTL_MINUTES: int = int(os.getenv("SEARCH_CONTEXT_TTL_MINUTES", "15"))
        self.SEARCH_TIMEOUT_SECONDS: float = float(os.getenv("SEARCH_TIMEOUT_SECONDS", "5.0"))
        self.SEMANTIC_EXECUTOR_WORKERS: int = max(1, int(os.getenv("SEMANTIC_EXECUTOR_WORKERS", "2")))
        self.SEMANTIC_MAX_PENDING: int = max(0, int(os.getenv("SEMANTIC_MAX_PENDING", "2")))
        self.CHROMA_PATH: str = os.getenv("CHROMA_PATH", str(PROJECT_ROOT / "data" / "vector"))
        self.CHROMA_HOST: str = os.getenv("CHROMA_HOST", "").strip()
        self.CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8000"))
        self.CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "wiki_ai_english")
        self.EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
        self.RRF_K: int = int(os.getenv("RRF_K", "60"))
        self.W_SPARSE_HIGH: float = float(os.getenv("W_SPARSE_HIGH", "1.0"))
        self.W_DENSE_HIGH: float = float(os.getenv("W_DENSE_HIGH", "1.0"))
        self.W_SPARSE_LOW: float = float(os.getenv("W_SPARSE_LOW", "0.1"))
        self.RRF_LAMBDA: float = float(os.getenv("RRF_LAMBDA", "2.0932"))
        self.COSINE_THRESHOLD: float = float(os.getenv("COSINE_THRESHOLD", "0.658"))

    def reload(self):
        """Reload settings from environment (useful in tests when os.environ is mutated)."""
        self.__init__()

    def validate_production(self):
        """
        Validates configuration security invariants.
        Fails fast during application startup/lifespan when insecure configurations are detected.
        """
        env = normalize_env(self.APP_ENV)
        if env not in VALID_ENVIRONMENTS:
            raise ValueError(
                f"Invalid APP_ENV: '{self.APP_ENV}'. Must be one of: {', '.join(sorted(VALID_ENVIRONMENTS))}"
            )

        if env in ("production", "staging"):
            # Enforce HTTPS Cookie Secure in production
            if env == "production" and not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE must be True in production environment (HTTPS required)")

            # Check APP_SECRET strength and entropy
            weak_patterns = [
                "folio_dev_insecure",
                "changeme",
                "default",
                "development",
                "insecure",
                "test_secret",
                "replace_with",
                "placeholder",
            ]
            secret_lower = self.APP_SECRET.lower()
            if any(pattern in secret_lower for pattern in weak_patterns):
                raise ValueError(
                    f"APP_SECRET contains insecure or default pattern in {env} environment"
                )
            if secret_lower in ("secret", "password", "admin", "root", "123456", "12345678"):
                raise ValueError(
                    f"APP_SECRET is a trivial dictionary word in {env} environment"
                )
            if len(self.APP_SECRET) < 32:
                raise ValueError(
                    f"APP_SECRET must be at least 32 characters long in {env} environment (got {len(self.APP_SECRET)})"
                )
            if len(set(self.APP_SECRET)) < 10:
                raise ValueError(
                    f"APP_SECRET has insufficient character diversity/entropy in {env} environment"
                )

            # Database URL checks
            if not self.DATABASE_URL or not self.DATABASE_URL.strip():
                raise ValueError(f"DATABASE_URL is required in {env} environment")
            if env == "production" and "postgres:postgres" in self.DATABASE_URL.lower():
                raise ValueError("DATABASE_URL uses default 'postgres:postgres' development credentials in production")

            # Wildcard CORS cannot be combined with credentials
            if "*" in self.CORS_ALLOWED_ORIGINS:
                raise ValueError(
                    f"CORS_ALLOWED_ORIGINS cannot contain wildcard '*' when credentialed CORS is enabled in {env}"
                )

settings = Settings()
