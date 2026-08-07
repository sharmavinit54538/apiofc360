"""Application configuration loaded from environment variables."""

from functools import lru_cache
import json
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET_KEY = "change-me-in-production-with-a-strong-random-secret"


class Settings(BaseSettings):
    """Runtime settings for the FastAPI application."""

    APP_NAME: str = "OFC HR – Office Function Consolidator (Human Resources)"
    APP_VERSION: str = "2.0.0"
    API_V1_PREFIX: str = "/api/v1"
    API_V2_PREFIX: str = "/api/v2"
    ENVIRONMENT: str = "local"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/hrms",
        description="Async SQLAlchemy PostgreSQL URL.",
    )
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 300

    SECRET_KEY: SecretStr = Field(
        default=DEFAULT_SECRET_KEY,
        description="Secret key used for JWT signing and OTP hashing.",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    BCRYPT_ROUNDS: int = 12
    BACKEND_CORS_ORIGINS: list[str] = ["https://ofc360.com", "https://www.ofc360.com", "https://ofc360.vercel.app", "http://localhost:3000", "http://localhost:8000", "http://localhost:8080", "http://127.0.0.1:8080", "http://127.0.0.1:3000"]
    ALLOWED_ORIGINS: list[str] = ["https://ofc360.com", "https://www.ofc360.com", "https://ofc360.vercel.app", "http://localhost:8080", "http://127.0.0.1:8080", "http://192.168.31.230:8080", "http://localhost:5173", "http://127.0.0.1:5173"]
    REGISTER_RATE_LIMIT: str = "5/minute"
    LOGIN_RATE_LIMIT_LIMIT: int = 5
    LOGIN_RATE_LIMIT_WINDOW: int = 60

    OTP_EXPIRE_MINUTES: int = 10
    OTP_RESEND_COOLDOWN_SECONDS: int = 30
    OTP_MAX_ATTEMPTS: int = 5

    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_FROM_EMAIL: str = "no-reply@example.com"
    SMTP_FROM_NAME: str = "HRMS Portal"
    SMTP_USE_TLS: bool = True   # STARTTLS on port 587
    SMTP_USE_SSL: bool = False  # SSL on port 465
    COMPANY_LOGO_URL: str = "/static/logo.png"

    # Employee module settings
    COMPANY_EMAIL_DOMAIN: str = "company.com"
    ACTIVATION_TOKEN_EXPIRE_HOURS: int = 72
    FRONTEND_BASE_URL: str = "https://ofc360.com"

    # ── Ollama / LLM settings ────────────────────────────────────────────────
    OLLAMA_ENABLED: bool = True
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_HOST: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3:latest"
    OLLAMA_DEFAULT_MODEL: str = "llama3:latest"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_TIMEOUT: int = 60
    OLLAMA_TIMEOUT_SECONDS: int = 60
    OLLAMA_KEEP_ALIVE: str = "30m"
    OLLAMA_MAX_CONNECTIONS: int = 50
    OLLAMA_TEMPERATURE: float = 0.3
    OLLAMA_TOP_P: float = 0.9
    OLLAMA_NUM_PREDICT: int = 2048


    # ── OCR settings ────────────────────────────────────────────────────────
    OCR_ENGINE_PREFERENCE: str = "auto"      # auto | paddle | easyocr | tesseract
    OCR_FALLBACK_CHAIN: list[str] = ["paddle", "easyocr", "tesseract"]
    OCR_IMAGE_MAX_SIZE_MB: int = 20
    OCR_PREPROCESSING_ENABLED: bool = True

    # ── Google Document AI OCR settings ──────────────────────────────────────
    GOOGLE_PROJECT_ID: str = ""
    GOOGLE_LOCATION: str = "us"
    GOOGLE_PROCESSOR_ID: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    DOCUMENT_OCR_MAX_FILE_SIZE_MB: int = 20
    ALLOWED_DOCUMENT_MIME_TYPES: list[str] = [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/tiff",
    ]

    # ── Vector store settings ────────────────────────────────────────────────
    VECTOR_STORE_TYPE: str = "faiss"         # faiss | qdrant | chroma
    VECTOR_STORE_PATH: str = "data/vector_store"
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    CHROMA_PERSIST_DIR: str = "data/chroma"
    VECTOR_EMBEDDING_DIM: int = 768

    # ── Redis / Celery settings ──────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_SOFT_TIME_LIMIT: int = 300
    CELERY_TASK_TIME_LIMIT: int = 600
    USE_CELERY: bool = False  # Graceful sync fallback when False

    # ── File upload settings ─────────────────────────────────────────────────
    UPLOAD_DIR: str = "uploads"
    RESUME_UPLOAD_DIR: str = "uploads/resumes"
    OFFER_LETTER_DIR: str = "uploads/offer_letters"
    MAX_RESUME_SIZE_MB: int = 10
    ALLOWED_RESUME_EXTENSIONS: list[str] = [".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".tiff"]

    # ── Cloudinary settings ──────────────────────────────────────────────────
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # ── Multi-Provider LLM settings ──────────────────────────────────────────
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_PRIORITY: int = 10

    # Anthropic Claude
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    ANTHROPIC_PRIORITY: int = 20

    # Google Gemini
    GOOGLE_AI_API_KEY: str = ""
    GOOGLE_AI_MODEL: str = "gemini-2.0-flash"
    GOOGLE_AI_EMBEDDING_MODEL: str = "text-embedding-004"
    GOOGLE_AI_PRIORITY: int = 15

    # OpenRouter (gateway for DeepSeek, Qwen, Mistral, etc.)
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "deepseek/deepseek-chat"
    OPENROUTER_PRIORITY: int = 30

    # Ollama priority (lower = higher priority)
    OLLAMA_PRIORITY: int = 1

    # LLM Routing & Limits
    LLM_PRIMARY_PROVIDER: str = "ollama"
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 3
    LLM_RATE_LIMIT_RPM: int = 60
    LLM_DAILY_BUDGET_USD: float = 100.0


    # ── AI Agent settings ────────────────────────────────────────────────────
    AI_SCREENING_THRESHOLD: float = 0.65     # Auto-shortlist above this score
    AI_REJECTION_THRESHOLD: float = 0.35     # Auto-reject below this score
    AI_RANKING_TOP_N: int = 50               # Default top-N for ranking
    AI_CONFIDENCE_MIN: float = 0.0
    AI_CONFIDENCE_MAX: float = 1.0

    # ── Rate limiting ────────────────────────────────────────────────────────
    AI_RATE_LIMIT_PER_MINUTE: int = 30
    AI_RATE_LIMIT_PER_HOUR: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("DEBUG", "DB_ECHO", "SMTP_USE_TLS", "SMTP_USE_SSL", "OCR_PREPROCESSING_ENABLED", "USE_CELERY", mode="before")
    @classmethod
    def parse_bool(cls, value: Any) -> bool:
        """Parse booleans defensively when global env vars are present."""

        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production", ""}:
                return False
        return value

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_database_url(cls, value: Any) -> str:
        """Ensure the database URL uses the async PostgreSQL driver and valid external host."""

        if isinstance(value, str):
            val = value.strip()
            if "postgres.railway.internal" in val:
                raise ValueError(
                    "DATABASE_URL contains Railway internal host 'postgres.railway.internal' which is unreachable from Render/outside Railway. "
                    "Please replace it with Railway's Public/External Connection URL (e.g. monorail.proxy.rlwy.net or TCP proxy domain)."
                )
            if val.startswith("postgres://"):
                val = val.replace("postgres://", "postgresql+asyncpg://", 1)
            elif val.startswith("postgresql://"):
                val = val.replace("postgresql://", "postgresql+asyncpg://", 1)
            
            if not val.startswith("postgresql+asyncpg://"):
                raise ValueError("DATABASE_URL must start with postgresql+asyncpg://")
            return val
        return value

    @field_validator("BACKEND_CORS_ORIGINS", "ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        """Accept CORS origins as a JSON list or comma-separated string."""

        if isinstance(value, str):
            stripped = value.strip().strip("'").strip('"').strip()
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(origin).strip().strip("'").strip('"') for origin in parsed]
                except Exception:
                    pass
            # Fallback to splitting by comma and cleaning up brackets/quotes
            cleaned = stripped.replace("[", "").replace("]", "").replace('"', '').replace("'", "")
            return [origin.strip() for origin in cleaned.split(",") if origin.strip()]
        return value

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: SecretStr) -> SecretStr:
        """Validate secret strength."""

        secret = value.get_secret_value()
        if len(secret) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return value

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        """Prevent default secrets in deployed environments."""

        if self.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
            if self.SECRET_KEY.get_secret_value() == DEFAULT_SECRET_KEY:
                raise ValueError("SECRET_KEY must be changed outside local development")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


settings = get_settings()