"""Application configuration loaded from environment variables."""

from functools import lru_cache
import json
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the FastAPI application."""

    APP_NAME: str = "OFC HR – Office Function Consolidator (Human Resources)"
    APP_VERSION: str = "2.0.0"
    API_V1_PREFIX: str = "/api/v1"
    API_V2_PREFIX: str = "/api/v2"
    ENVIRONMENT: str = "local"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    ENABLE_DOCS: bool | None = Field(
        default=None,
        description="Explicitly enable or disable public API docs (/docs, /redoc, /openapi.json). Defaults to True in dev/local and False in production.",
    )

    @property
    def is_production(self) -> bool:
        """Check if environment is production (ENVIRONMENT in ('production', 'prod') or DEBUG is False)."""
        return self.ENVIRONMENT.lower() in {"production", "prod"} or not self.DEBUG

    @property
    def should_enable_docs(self) -> bool:
        """
        Determine whether API docs (/docs, /redoc, /openapi.json) should be enabled.
        - If ENABLE_DOCS is explicitly set (True/False), use that value.
        - Otherwise, enable in local/dev (True) and disable in production (False).
        """
        if self.ENABLE_DOCS is not None:
            return self.ENABLE_DOCS
        return not self.is_production

    DATABASE_URL: str = Field(
        default="",
        description="Async SQLAlchemy PostgreSQL URL. Must be set via env var in production.",
    )
    FORCE_IPV4_DB: bool = Field(
        default=False,
        description="Force IPv4 resolution for database host (legacy workaround for IPv6 direct connection issues - e.g., Supabase direct). Default False for Render/standard PostgreSQL.",
    )
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 300

    SECRET_KEY: SecretStr = Field(
        default="",
        description="Secret key used for OTP hashing and other symmetric operations. Must be 32+ chars. Set via env var.",
    )
    JWT_ALGORITHM: str = "RS256"
    JWT_PRIVATE_KEY: SecretStr = Field(
        default="",
        description="RSA private key (PEM format) for signing JWT tokens. Set via env var in production.",
    )
    JWT_PUBLIC_KEY: SecretStr = Field(
        default="",
        description="RSA public key (PEM format) for verifying JWT tokens. Set via env var in production.",
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    SUPER_ADMIN_EMAIL: str = "superadmin@ofc360.com"
    SUPER_ADMIN_PASSWORD: SecretStr = Field(
        default=SecretStr("SuperAdmin@2026"),
        description="Platform Super Admin initial password used during provisioning.",
    )

    BCRYPT_ROUNDS: int = 12
    # Production CORS origins - only explicitly configured origins
    BACKEND_CORS_ORIGINS: list[str] = [
        "https://api.ofc360.com",
        "https://ofc360.com",
        "https://www.ofc360.com",
        "https://ofc360.vercel.app",
    ]
    # Development origins - only used when ENVIRONMENT is local/development/dev
    DEV_CORS_ORIGINS: list[str] = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://192.168.31.230:8080",
        "http://192.168.31.235:8080",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    ALLOWED_ORIGINS: list[str] = [
        "https://api.ofc360.com",
        "https://ofc360.com",
        "https://www.ofc360.com",
        "https://ofc360.vercel.app",
    ]
    REGISTER_RATE_LIMIT: str = "5/minute"
    LOGIN_RATE_LIMIT_LIMIT: int = 5
    LOGIN_RATE_LIMIT_WINDOW: int = 60

    API_RATE_LIMIT_ENABLED: bool = True
    API_RATE_LIMIT_PER_MINUTE: int = 100
    API_RATE_LIMIT_PER_HOUR: int = 2000
    API_RATE_LIMIT_BURST: int = 20

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

    # ── GitHub OAuth settings ────────────────────────────────────────────────
    GITHUB_CLIENT_ID: str = Field(default="", description="GitHub OAuth App Client ID")
    GITHUB_CLIENT_SECRET: SecretStr = Field(default=SecretStr(""), description="GitHub OAuth App Client Secret")
    GITHUB_REDIRECT_URI: str = Field(default="", description="GitHub OAuth redirect URI")


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
    REDIS_URL: str = Field(
        default="",
        description="Redis URL. Must be set via env var in production. Empty defaults to redis://localhost:6379/0 in local dev only.",
    )
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

    # ── Multi-Provider LLM settings DISABLED ──────────────────────────────
    # Cloud LLM providers are DISABLED. Only Ollama is supported.
    # OPENAI_API_KEY: str = ""
    # OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    # OPENAI_MODEL: str = "gpt-4o-mini"
    # OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    # OPENAI_PRIORITY: int = 10
    #
    # # Anthropic Claude
    # ANTHROPIC_API_KEY: str = ""
    # ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    # ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    # ANTHROPIC_PRIORITY: int = 20
    #
    # # Google Gemini
    # GOOGLE_AI_API_KEY: str = ""
    # GOOGLE_AI_MODEL: str = "gemini-2.0-flash"
    # GOOGLE_AI_EMBEDDING_MODEL: str = "text-embedding-004"
    # GOOGLE_AI_PRIORITY: int = 15
    #
    # # OpenRouter (gateway for DeepSeek, Qwen, Mistral, etc.)
    # OPENROUTER_API_KEY: str = ""
    # OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # OPENROUTER_MODEL: str = "deepseek/deepseek-chat"
    # OPENROUTER_PRIORITY: int = 30

    OLLAMA_HOST: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen3:30b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
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
        """Ensure the database URL uses the async PostgreSQL driver and valid host."""

        if isinstance(value, str):
            val = value.strip().strip('"').strip("'")
            if val.startswith("DATABASE_URL="):
                val = val[len("DATABASE_URL="):].strip().strip('"').strip("'")
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

    @field_validator("SUPER_ADMIN_EMAIL", mode="before")
    @classmethod
    def validate_super_admin_email(cls, value: Any) -> str:
        """Enforce immutable single super admin identity."""
        if isinstance(value, str):
            clean_email = value.strip().lower()
            if clean_email != "superadmin@ofc360.com":
                raise ValueError("SUPER_ADMIN_EMAIL cannot be changed from 'superadmin@ofc360.com'.")
            return clean_email
        return "superadmin@ofc360.com"

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, value: Any) -> str:
        """Validate secret strength - must be provided via env, no default."""
        if isinstance(value, str):
            val = value.strip().strip('"').strip("'")
            if not val:
                raise ValueError("SECRET_KEY must be set via environment variable (32+ characters)")
            if len(val) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters long")
            return val
        return value

    @field_validator("JWT_PRIVATE_KEY", mode="before")
    @classmethod
    def validate_jwt_private_key(cls, value: Any) -> str:
        """Validate JWT private key is provided in production."""
        if isinstance(value, str):
            val = value.strip().strip('"').strip("'")
            return val
        return value

    @field_validator("JWT_PUBLIC_KEY", mode="before")
    @classmethod
    def validate_jwt_public_key(cls, value: Any) -> str:
        """Validate JWT public key is provided in production."""
        if isinstance(value, str):
            val = value.strip().strip('"').strip("'")
            return val
        return value

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        """Prevent default/empty secrets in deployed environments."""

        if self.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
            secret_val = self.SECRET_KEY.get_secret_value()
            if not secret_val or len(secret_val) < 32:
                raise ValueError("SECRET_KEY must be set via environment variable (32+ characters) in production")
            if not self.DATABASE_URL or not self.DATABASE_URL.startswith("postgresql+asyncpg://"):
                raise ValueError("DATABASE_URL must be set via environment variable in production")
            if not self.REDIS_URL or not self.REDIS_URL.strip():
                raise ValueError("REDIS_URL must be set via environment variable in production")
            # JWT keys required for RS256 in production
            if self.JWT_ALGORITHM.upper().startswith("RS"):
                private_key = self.JWT_PRIVATE_KEY.get_secret_value()
                public_key = self.JWT_PUBLIC_KEY.get_secret_value()
                if not private_key or not private_key.strip():
                    raise ValueError("JWT_PRIVATE_KEY must be set via environment variable in production when using RS256")
                if not public_key or not public_key.strip():
                    raise ValueError("JWT_PUBLIC_KEY must be set via environment variable in production when using RS256")
                # Validate key format
                if not private_key.strip().startswith("-----BEGIN"):
                    raise ValueError("JWT_PRIVATE_KEY must be in PEM format")
                if not public_key.strip().startswith("-----BEGIN"):
                    raise ValueError("JWT_PUBLIC_KEY must be in PEM format")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


settings = get_settings()