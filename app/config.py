"""App settings, read from environment variables or the .env file.

pydantic-settings matches each field to a variable of the same name, converts
it to the right type, and falls back to the default when it isn't set.
Use it anywhere with:  from app.config import settings
"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "change-me-in-env"  # noqa: S105 - placeholder; production refuses to start with it


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "BA WorkTrack"
    # "development" or "production". Production refuses to start with the default secret
    # and marks cookies Secure (HTTPS only).
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = INSECURE_SECRET
    # Fernet key that encrypts JIRA / ADO tokens in the database. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # When empty, a key is derived from SECRET_KEY.
    ENCRYPTION_KEY: str = ""
    DATABASE_URL: str = "sqlite:///./worktrack.db"
    ACCESS_TOKEN_MINUTES: int = 8 * 60
    UPLOAD_DIR: Path = Path("data/uploads")
    MAX_UPLOAD_MB: int = 10

    # Login protection. BCRYPT_ROUNDS: cost of password hashing (each +1 doubles the time).
    BCRYPT_ROUNDS: int = 12
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    # AI (local model through Ollama). Set AI_PROVIDER=disabled to hide AI features.
    AI_PROVIDER: str = "ollama"
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_URL: str = "http://localhost:11434"
    AI_TIMEOUT_SECONDS: int = 120

    # Background jobs: weekly report (Friday) and integration status sync
    SCHEDULER_ENABLED: bool = True
    WEEKLY_REPORT_DAY: str = "fri"
    WEEKLY_REPORT_HOUR: int = 17
    SYNC_INTERVAL_MINUTES: int = 30

    # Bootstrap admin, created on first start when the users table is empty
    FIRST_ADMIN_EMAIL: str = ""
    FIRST_ADMIN_PASSWORD: str = ""

    @field_validator("ENVIRONMENT")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower().strip()

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


# One shared instance, created when the module is first imported
settings = Settings()
