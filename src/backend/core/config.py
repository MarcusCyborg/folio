import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root if it exists
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

class Settings:
    PROJECT_ROOT: Path = PROJECT_ROOT
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_SECRET: str = os.getenv("APP_SECRET", "folio_dev_insecure_secret_key_change_in_production_32bytes_min")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/folio")
    TEST_DATABASE_URL: str = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/folio_test")
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
    ENABLE_LEGACY_SEARCH: bool = os.getenv("ENABLE_LEGACY_SEARCH", "false").lower() in ("true", "1", "yes")
    DEMO_PASSWORD: str = os.getenv("DEMO_PASSWORD", "FolioDemo2026!")
    SESSION_COOKIE_NAME: str = "folio_session"
    SESSION_MAX_AGE_DAYS: int = 7

    # Ensure secret is strong in production
    def validate_production(self):
        if self.APP_ENV == "production":
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE must be True in production")
            if "folio_dev_insecure" in self.APP_SECRET or len(self.APP_SECRET) < 32:
                raise ValueError("APP_SECRET must be securely configured with at least 32 characters in production")

settings = Settings()
