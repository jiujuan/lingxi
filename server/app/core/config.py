from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import quote_plus


def load_env_file(path: str | Path = ".env") -> int:
    env_path = Path(path)
    if not env_path.exists():
        return 0

    loaded = 0
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
        loaded += 1
    return loaded


def build_database_url() -> str:
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    user = quote_plus(os.getenv("POSTGRES_USER", "postgres"))
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = quote_plus(os.getenv("POSTGRES_DB", "lingxi"))
    password_part = f":{quote_plus(password)}" if password else ""
    return f"postgresql+psycopg://{user}{password_part}@{host}:{port}/{database}"


def build_redis_url(url_env: str, db_env: str, default_db: int) -> str:
    explicit_url = os.getenv(url_env)
    if explicit_url:
        return explicit_url

    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD", "")
    database = os.getenv(db_env, str(default_db))
    password_part = f":{quote_plus(password)}@" if password else ""
    return f"redis://{password_part}{host}:{port}/{database}"


def parse_csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    values = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    return values or default


def build_secret_encryption_key() -> str:
    return (
        os.getenv("SECRET_ENCRYPTION_KEY")
        or os.getenv("JWT_SECRET_KEY")
        or "dev-only-change-before-deployment"
    )


load_env_file()


@dataclass(frozen=True)
class Settings:
    app_name: str = field(
        default_factory=lambda: os.getenv("APP_NAME", "Lingxi Knowledge Base")
    )
    environment: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    database_url: str = field(default_factory=build_database_url)
    redis_url: str = field(
        default_factory=lambda: build_redis_url("REDIS_URL", "REDIS_DB", 0)
    )
    celery_broker_url: str = field(
        default_factory=lambda: build_redis_url(
            "CELERY_BROKER_URL", "REDIS_CELERY_BROKER_DB", 1
        )
    )
    celery_result_backend: str = field(
        default_factory=lambda: build_redis_url(
            "CELERY_RESULT_BACKEND", "REDIS_CELERY_RESULT_DB", 2
        )
    )
    celery_queue_names: tuple[str, ...] = field(
        default_factory=lambda: parse_csv_env(
            "CELERY_QUEUE_NAMES", ("parse", "qa", "embedding", "maintenance")
        )
    )
    celery_default_queue: str = field(
        default_factory=lambda: os.getenv("CELERY_DEFAULT_QUEUE", "maintenance")
    )
    object_storage_backend: str = field(
        default_factory=lambda: os.getenv("OBJECT_STORAGE_BACKEND", "local")
    )
    local_storage_root: str = field(
        default_factory=lambda: os.getenv(
            "LOCAL_STORAGE_ROOT", ".data/object-storage"
        )
    )
    upload_allowed_extensions: tuple[str, ...] = field(
        default_factory=lambda: parse_csv_env(
            "UPLOAD_ALLOWED_EXTENSIONS", (".md", ".markdown", ".txt")
        )
    )
    upload_max_file_size_bytes: int = field(
        default_factory=lambda: int(
            os.getenv("UPLOAD_MAX_FILE_SIZE_BYTES", str(10 * 1024 * 1024))
        )
    )
    import_max_files_per_job: int = field(
        default_factory=lambda: int(os.getenv("IMPORT_MAX_FILES_PER_JOB", "1"))
    )
    jwt_secret_key: str = field(
        default_factory=lambda: os.getenv(
            "JWT_SECRET_KEY", "dev-only-change-before-deployment"
        )
    )
    secret_encryption_key: str = field(
        default_factory=build_secret_encryption_key
    )
    jwt_algorithm: str = field(default_factory=lambda: os.getenv("JWT_ALGORITHM", "HS256"))
    access_token_minutes: int = field(
        default_factory=lambda: int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
    )
    refresh_token_minutes: int = field(
        default_factory=lambda: int(os.getenv("REFRESH_TOKEN_MINUTES", "43200"))
    )
    seed_tenant_name: str = field(
        default_factory=lambda: os.getenv("SEED_TENANT_NAME", "Default Tenant")
    )
    seed_admin_email: str = field(
        default_factory=lambda: os.getenv("SEED_ADMIN_EMAIL", "admin@example.com")
    )
    seed_admin_password: str = field(
        default_factory=lambda: os.getenv("SEED_ADMIN_PASSWORD", "Admin123!")
    )
    seed_employee_email: str = field(
        default_factory=lambda: os.getenv("SEED_EMPLOYEE_EMAIL", "employee@example.com")
    )
    seed_employee_password: str = field(
        default_factory=lambda: os.getenv("SEED_EMPLOYEE_PASSWORD", "Employee123!")
    )
    retrieval_vector_top_k: int = field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_VECTOR_TOP_K", "20"))
    )
    retrieval_text_top_k: int = field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_TEXT_TOP_K", "20"))
    )
    retrieval_final_top_k: int = field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_FINAL_TOP_K", "5"))
    )
    retrieval_rrf_k: int = field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_RRF_K", "60"))
    )
    retrieval_low_confidence_threshold: float = field(
        default_factory=lambda: float(
            os.getenv("RETRIEVAL_LOW_CONFIDENCE_THRESHOLD", "1.35")
        )
    )

    @property
    def access_token_expires_seconds(self) -> int:
        return self.access_token_minutes * 60


settings = Settings()
