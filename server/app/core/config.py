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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def build_db_engine_options(role: str = "api", *, url: str | None = None) -> dict:
    """Explicit SQLAlchemy pool configuration, tunable per process role.

    The API and Celery worker run in separate processes and size their pools
    independently: the worker reads ``WORKER_DB_*`` env vars (falling back to the
    shared ``DB_*`` values) so a busy worker fleet does not starve the API — or
    vice versa. SQLite (tests/local) uses its default pool since it rejects
    QueuePool sizing arguments.
    """

    resolved_url = url or build_database_url()
    if resolved_url.startswith("sqlite"):
        return {"pool_pre_ping": _env_bool("DB_POOL_PRE_PING", True)}

    worker = role == "worker"

    def pick_int(base_env: str, worker_env: str, default: int) -> int:
        if worker:
            override = os.getenv(worker_env)
            if override is not None:
                return int(override)
        return int(os.getenv(base_env, str(default)))

    return {
        "pool_size": pick_int("DB_POOL_SIZE", "WORKER_DB_POOL_SIZE", 5),
        "max_overflow": pick_int("DB_MAX_OVERFLOW", "WORKER_DB_MAX_OVERFLOW", 10),
        "pool_recycle": pick_int("DB_POOL_RECYCLE", "WORKER_DB_POOL_RECYCLE", 1800),
        "pool_timeout": pick_int("DB_POOL_TIMEOUT", "WORKER_DB_POOL_TIMEOUT", 30),
        "pool_pre_ping": _env_bool("DB_POOL_PRE_PING", True),
    }


def build_secret_encryption_key() -> str:
    # Independent from JWT_SECRET_KEY: never fall back to the JWT key so the two
    # secrets can be rotated separately and a leak of one does not compromise the
    # other. In non-production a distinct dev default keeps local setup friction low;
    # production is enforced by validate_secret_config().
    return os.getenv("SECRET_ENCRYPTION_KEY") or DEV_ENCRYPTION_SECRET_DEFAULT


load_env_file()


# Well-known development-only secret defaults. Production must override these;
# validate_secret_config() refuses to start if any survive into production.
DEV_JWT_SECRET_DEFAULT = "dev-only-change-before-deployment"
DEV_ENCRYPTION_SECRET_DEFAULT = "dev-only-encryption-change-before-deployment"
_WEAK_SECRET_VALUES = frozenset(
    {
        "",
        DEV_JWT_SECRET_DEFAULT,
        DEV_ENCRYPTION_SECRET_DEFAULT,
        "change-me-in-local-dev",
        "change-me-in-local-dev-encryption",
        "change-me",
    }
)
MIN_SECRET_LENGTH = 32


class ConfigurationError(RuntimeError):
    """Raised at startup when runtime configuration is unsafe for production."""


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
        # Empty tuple = "unset": the effective allowlist is then derived from
        # the parser registry (see integrations/parsers/registry.py). When set,
        # it can only restrict — the gate intersects it with parser support.
        default_factory=lambda: parse_csv_env("UPLOAD_ALLOWED_EXTENSIONS", ())
    )
    upload_max_file_size_bytes: int = field(
        default_factory=lambda: int(
            os.getenv("UPLOAD_MAX_FILE_SIZE_BYTES", str(10 * 1024 * 1024))
        )
    )
    import_max_files_per_job: int = field(
        default_factory=lambda: int(os.getenv("IMPORT_MAX_FILES_PER_JOB", "1"))
    )
    mineru_base_url: str | None = field(
        default_factory=lambda: os.getenv("MINERU_BASE_URL") or None
    )
    mineru_api_key: str | None = field(
        default_factory=lambda: os.getenv("MINERU_API_KEY") or None
    )
    mineru_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("MINERU_TIMEOUT_MS", "30000"))
    )
    mineru_max_wait_seconds: int = field(
        default_factory=lambda: int(os.getenv("MINERU_MAX_WAIT_SECONDS", "600"))
    )
    mineru_poll_interval_seconds: float = field(
        default_factory=lambda: float(os.getenv("MINERU_POLL_INTERVAL_SECONDS", "3.0"))
    )
    mineru_backend: str | None = field(
        default_factory=lambda: os.getenv("MINERU_BACKEND") or None
    )
    mineru_lang: str | None = field(
        default_factory=lambda: os.getenv("MINERU_LANG") or None
    )
    # Heavy-parser engine selection: "auto" registers both MinerU and Docling
    # (MinerU first), "mineru"/"docling" registers only that engine.
    doc_parser_engine: str = field(
        default_factory=lambda: os.getenv("DOC_PARSER_ENGINE", "auto")
    )
    docling_base_url: str | None = field(
        default_factory=lambda: os.getenv("DOCLING_BASE_URL") or None
    )
    docling_api_key: str | None = field(
        default_factory=lambda: os.getenv("DOCLING_API_KEY") or None
    )
    docling_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("DOCLING_TIMEOUT_MS", "30000"))
    )
    docling_max_wait_seconds: int = field(
        default_factory=lambda: int(os.getenv("DOCLING_MAX_WAIT_SECONDS", "600"))
    )
    docling_poll_interval_seconds: float = field(
        default_factory=lambda: float(
            os.getenv("DOCLING_POLL_INTERVAL_SECONDS", "3.0")
        )
    )
    docling_do_ocr: str | None = field(
        default_factory=lambda: os.getenv("DOCLING_DO_OCR") or None
    )
    docling_ocr_lang: str | None = field(
        default_factory=lambda: os.getenv("DOCLING_OCR_LANG") or None
    )
    docling_pdf_backend: str | None = field(
        default_factory=lambda: os.getenv("DOCLING_PDF_BACKEND") or None
    )
    jwt_secret_key: str = field(
        default_factory=lambda: os.getenv("JWT_SECRET_KEY", DEV_JWT_SECRET_DEFAULT)
    )
    secret_encryption_key: str = field(
        default_factory=build_secret_encryption_key
    )
    jwt_algorithm: str = field(default_factory=lambda: os.getenv("JWT_ALGORITHM", "HS256"))
    jwt_issuer: str = field(default_factory=lambda: os.getenv("JWT_ISSUER", "lingxi"))
    jwt_audience: str = field(
        default_factory=lambda: os.getenv("JWT_AUDIENCE", "lingxi-api")
    )
    access_token_minutes: int = field(
        default_factory=lambda: int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
    )
    refresh_token_minutes: int = field(
        default_factory=lambda: int(os.getenv("REFRESH_TOKEN_MINUTES", "20160"))
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
    retrieval_snapshot_max_items_per_stage: int = field(
        default_factory=lambda: int(
            os.getenv("RETRIEVAL_SNAPSHOT_MAX_ITEMS_PER_STAGE", "10")
        )
    )
    jieba_user_dict_path: str | None = field(
        default_factory=lambda: os.getenv("JIEBA_USER_DICT_PATH") or None
    )
    embedding_batch_size: int = field(
        default_factory=lambda: int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
    )
    embedding_max_concurrency: int = field(
        default_factory=lambda: int(os.getenv("EMBEDDING_MAX_CONCURRENCY", "4"))
    )
    embedding_batch_max_retries: int = field(
        default_factory=lambda: int(os.getenv("EMBEDDING_BATCH_MAX_RETRIES", "2"))
    )
    qa_split_max_batch_chars: int = field(
        default_factory=lambda: int(os.getenv("QA_SPLIT_MAX_BATCH_CHARS", "6000"))
    )
    qa_split_max_concurrency: int = field(
        default_factory=lambda: int(os.getenv("QA_SPLIT_MAX_CONCURRENCY", "4"))
    )
    sse_heartbeat_seconds: float = field(
        default_factory=lambda: float(os.getenv("SSE_HEARTBEAT_SECONDS", "15"))
    )
    cors_allow_origins: tuple[str, ...] = field(
        default_factory=lambda: parse_csv_env(
            "CORS_ALLOW_ORIGINS", ("http://localhost:5173", "http://localhost:3000")
        )
    )

    @property
    def access_token_expires_seconds(self) -> int:
        return self.access_token_minutes * 60


settings = Settings()


def _secret_problems(current: "Settings") -> list[str]:
    problems: list[str] = []
    checks = (
        ("JWT_SECRET_KEY", current.jwt_secret_key),
        ("SECRET_ENCRYPTION_KEY", current.secret_encryption_key),
    )
    for name, value in checks:
        if value in _WEAK_SECRET_VALUES:
            problems.append(f"{name} 未设置或仍为开发默认值，生产环境必须设置强随机值")
        elif len(value) < MIN_SECRET_LENGTH:
            problems.append(f"{name} 长度须不少于 {MIN_SECRET_LENGTH} 个字符")
    if (
        current.jwt_secret_key == current.secret_encryption_key
        and current.jwt_secret_key not in _WEAK_SECRET_VALUES
    ):
        problems.append("SECRET_ENCRYPTION_KEY 必须与 JWT_SECRET_KEY 不同（职责分离）")
    return problems


def validate_secret_config(current: "Settings | None" = None) -> None:
    """Fail-fast guard for production secret hygiene.

    In non-production environments this is a no-op (dev defaults are allowed).
    In production it raises :class:`ConfigurationError` unless both the JWT and
    the secret-encryption keys are explicitly set, sufficiently long, and
    distinct from each other. Call it once at application/worker startup.
    """

    current = current or settings
    if current.environment.strip().lower() != "production":
        return
    problems = _secret_problems(current)
    if problems:
        raise ConfigurationError(
            "生产环境密钥配置不合法，拒绝启动：\n- " + "\n- ".join(problems)
        )
