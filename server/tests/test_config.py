import pytest

from server.app.core.config import (
    ConfigurationError,
    DEV_ENCRYPTION_SECRET_DEFAULT,
    Settings,
    build_database_url,
    build_db_engine_options,
    build_redis_url,
    load_env_file,
    parse_csv_env,
    validate_secret_config,
)


def test_database_url_defaults_to_local_postgres(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    assert build_database_url() == "postgresql+psycopg://postgres@localhost:5432/lingxi"


def test_database_url_uses_explicit_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    assert build_database_url() == "sqlite+pysqlite:///:memory:"


def test_database_url_uses_local_postgres_parts(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "lingxi_test")
    monkeypatch.setenv("POSTGRES_USER", "lingxi")
    monkeypatch.setenv("POSTGRES_PASSWORD", "local pass")

    assert (
        build_database_url()
        == "postgresql+psycopg://lingxi:local+pass@127.0.0.1:5433/lingxi_test"
    )


def test_load_env_file_sets_missing_values_without_overriding_existing(
    monkeypatch, tmp_path
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=from-file\nPOSTGRES_USER=file-user\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POSTGRES_USER", "existing-user")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    loaded = load_env_file(env_file)

    assert loaded == 1
    assert build_database_url().startswith(
        "postgresql+psycopg://existing-user:from-file@"
    )


def test_redis_url_defaults_to_local_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_PORT", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("REDIS_DB", raising=False)

    assert build_redis_url("REDIS_URL", "REDIS_DB", 0) == "redis://localhost:6379/0"


def test_redis_url_uses_explicit_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/8")

    assert build_redis_url("REDIS_URL", "REDIS_DB", 0) == "redis://example:6379/8"


def test_redis_url_uses_parts_and_password(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_PASSWORD", "local pass")
    monkeypatch.setenv("REDIS_DB", "3")

    assert (
        build_redis_url("REDIS_URL", "REDIS_DB", 0)
        == "redis://:local+pass@127.0.0.1:6380/3"
    )


def test_celery_redis_url_can_use_separate_db(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_CELERY_BROKER_DB", "1")

    assert (
        build_redis_url("CELERY_BROKER_URL", "REDIS_CELERY_BROKER_DB", 1)
        == "redis://localhost:6379/1"
    )


def test_parse_csv_env_uses_default_and_trims_values(monkeypatch):
    monkeypatch.delenv("CELERY_QUEUE_NAMES", raising=False)
    assert parse_csv_env("CELERY_QUEUE_NAMES", ("parse", "qa")) == ("parse", "qa")

    monkeypatch.setenv("CELERY_QUEUE_NAMES", "parse, qa, embedding ,, maintenance")
    assert parse_csv_env("CELERY_QUEUE_NAMES", ("fallback",)) == (
        "parse",
        "qa",
        "embedding",
        "maintenance",
    )


def test_settings_read_runtime_and_seed_values_from_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Lingxi Local")
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    monkeypatch.setenv("ACCESS_TOKEN_MINUTES", "45")
    monkeypatch.setenv("REFRESH_TOKEN_MINUTES", "1000")
    monkeypatch.setenv("CELERY_QUEUE_NAMES", "parse,qa")
    monkeypatch.setenv("CELERY_DEFAULT_QUEUE", "parse")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", "D:/tmp/lingxi-storage")
    monkeypatch.setenv("UPLOAD_ALLOWED_EXTENSIONS", ".md,.txt")
    monkeypatch.setenv("UPLOAD_MAX_FILE_SIZE_BYTES", "12345")
    monkeypatch.setenv("IMPORT_MAX_FILES_PER_JOB", "2")
    monkeypatch.setenv("EMBEDDING_VECTOR_DIMENSION", "1536")
    monkeypatch.setenv("MINERU_BASE_URL", "http://mineru.local:8000/")
    monkeypatch.setenv("MINERU_API_KEY", "mineru-token")
    monkeypatch.setenv("MINERU_TIMEOUT_MS", "45000")
    monkeypatch.setenv("MINERU_MAX_WAIT_SECONDS", "120")
    monkeypatch.setenv("MINERU_POLL_INTERVAL_SECONDS", "1.5")
    monkeypatch.setenv("MINERU_BACKEND", "pipeline")
    monkeypatch.setenv("MINERU_LANG", "ch")
    monkeypatch.setenv("DOC_PARSER_ENGINE", "docling")
    monkeypatch.setenv("DOCLING_BASE_URL", "http://docling.local:5001/")
    monkeypatch.setenv("DOCLING_API_KEY", "docling-token")
    monkeypatch.setenv("DOCLING_TIMEOUT_MS", "20000")
    monkeypatch.setenv("DOCLING_MAX_WAIT_SECONDS", "240")
    monkeypatch.setenv("DOCLING_POLL_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("DOCLING_DO_OCR", "true")
    monkeypatch.setenv("DOCLING_OCR_LANG", "zh")
    monkeypatch.setenv("DOCLING_PDF_BACKEND", "dlparse_v4")
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "secret-envelope-key")
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "Root123!")
    monkeypatch.setenv("SEED_EMPLOYEE_EMAIL", "staff@example.com")
    monkeypatch.setenv("SEED_EMPLOYEE_PASSWORD", "Staff123!")

    settings = Settings()

    assert settings.app_name == "Lingxi Local"
    assert settings.jwt_algorithm == "HS512"
    assert settings.access_token_minutes == 45
    assert settings.access_token_expires_seconds == 2700
    assert settings.refresh_token_minutes == 1000
    assert settings.celery_queue_names == ("parse", "qa")
    assert settings.celery_default_queue == "parse"
    assert settings.object_storage_backend == "local"
    assert settings.local_storage_root == "D:/tmp/lingxi-storage"
    assert settings.upload_allowed_extensions == (".md", ".txt")
    assert settings.upload_max_file_size_bytes == 12345
    assert settings.import_max_files_per_job == 2
    assert settings.embedding_vector_dimension == 1536
    assert settings.mineru_base_url == "http://mineru.local:8000/"
    assert settings.mineru_api_key == "mineru-token"
    assert settings.mineru_timeout_ms == 45000
    assert settings.mineru_max_wait_seconds == 120
    assert settings.mineru_poll_interval_seconds == 1.5
    assert settings.mineru_backend == "pipeline"
    assert settings.mineru_lang == "ch"
    assert settings.doc_parser_engine == "docling"
    assert settings.docling_base_url == "http://docling.local:5001/"
    assert settings.docling_api_key == "docling-token"
    assert settings.docling_timeout_ms == 20000
    assert settings.docling_max_wait_seconds == 240
    assert settings.docling_poll_interval_seconds == 2.5
    assert settings.docling_do_ocr == "true"
    assert settings.docling_ocr_lang == "zh"
    assert settings.docling_pdf_backend == "dlparse_v4"
    assert settings.secret_encryption_key == "secret-envelope-key"
    assert settings.seed_admin_email == "root@example.com"
    assert settings.seed_admin_password == "Root123!"
    assert settings.seed_employee_email == "staff@example.com"
    assert settings.seed_employee_password == "Staff123!"


def test_settings_upload_and_mineru_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("UPLOAD_ALLOWED_EXTENSIONS", raising=False)
    monkeypatch.delenv("MINERU_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_PARSER_ENGINE", raising=False)
    monkeypatch.delenv("DOCLING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_VECTOR_DIMENSION", raising=False)

    settings = Settings()

    # Empty tuple = "unset": the upload gate then derives the allowlist from
    # the parser registry instead of this env value.
    assert settings.upload_allowed_extensions == ()
    assert settings.mineru_base_url is None
    assert settings.mineru_timeout_ms == 30000
    assert settings.mineru_max_wait_seconds == 600
    assert settings.mineru_poll_interval_seconds == 3.0
    assert settings.doc_parser_engine == "auto"
    assert settings.docling_base_url is None
    assert settings.docling_timeout_ms == 30000
    assert settings.docling_max_wait_seconds == 600
    assert settings.docling_poll_interval_seconds == 3.0
    assert settings.embedding_vector_dimension == 1024


def test_qa_split_settings_read_defaults_and_environment_overrides(monkeypatch):
    for name in (
        "QA_SPLIT_MAX_INPUT_TOKENS",
        "QA_SPLIT_RESERVED_OUTPUT_TOKENS",
        "QA_SPLIT_MAX_RETRIES",
        "QA_SPLIT_MAX_SPLIT_DEPTH",
        "QA_SPLIT_INITIAL_CONCURRENCY",
        "QA_SPLIT_MIN_CONCURRENCY",
        "QA_SPLIT_MAX_CONCURRENCY",
    ):
        monkeypatch.delenv(name, raising=False)

    defaults = Settings()
    assert defaults.qa_split_max_input_tokens == 4096
    assert defaults.qa_split_reserved_output_tokens == 2048
    assert defaults.qa_split_max_retries == 1
    assert defaults.qa_split_max_split_depth == 1
    assert defaults.qa_split_initial_concurrency == 1
    assert defaults.qa_split_min_concurrency == 1
    assert defaults.qa_split_max_concurrency == 4

    monkeypatch.setenv("QA_SPLIT_MAX_INPUT_TOKENS", "8192")
    monkeypatch.setenv("QA_SPLIT_RESERVED_OUTPUT_TOKENS", "1024")
    monkeypatch.setenv("QA_SPLIT_MAX_RETRIES", "3")
    monkeypatch.setenv("QA_SPLIT_MAX_SPLIT_DEPTH", "2")
    monkeypatch.setenv("QA_SPLIT_INITIAL_CONCURRENCY", "2")
    monkeypatch.setenv("QA_SPLIT_MIN_CONCURRENCY", "1")
    monkeypatch.setenv("QA_SPLIT_MAX_CONCURRENCY", "6")

    overridden = Settings()
    assert overridden.qa_split_max_input_tokens == 8192
    assert overridden.qa_split_reserved_output_tokens == 1024
    assert overridden.qa_split_max_retries == 3
    assert overridden.qa_split_max_split_depth == 2
    assert overridden.qa_split_initial_concurrency == 2
    assert overridden.qa_split_min_concurrency == 1
    assert overridden.qa_split_max_concurrency == 6


def test_empty_secret_encryption_key_uses_independent_dev_default(monkeypatch):
    # The encryption key no longer falls back to JWT_SECRET_KEY: an unset value
    # resolves to its own dev default so the two secrets stay independent.
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret")
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "")

    settings = Settings()

    assert settings.secret_encryption_key == DEV_ENCRYPTION_SECRET_DEFAULT
    assert settings.secret_encryption_key != settings.jwt_secret_key


def _production_settings(monkeypatch, *, jwt: str, enc: str) -> Settings:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", jwt)
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", enc)
    return Settings()


def test_validate_secret_config_is_noop_in_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_ENCRYPTION_KEY", raising=False)

    # dev defaults must not raise
    validate_secret_config(Settings())


def test_validate_secret_config_rejects_weak_production_secrets(monkeypatch):
    settings = _production_settings(
        monkeypatch, jwt="dev-only-change-before-deployment", enc=""
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_secret_config(settings)
    assert "JWT_SECRET_KEY" in str(excinfo.value)
    assert "SECRET_ENCRYPTION_KEY" in str(excinfo.value)


def test_validate_secret_config_rejects_short_production_secrets(monkeypatch):
    settings = _production_settings(monkeypatch, jwt="short", enc="alsoshort")
    with pytest.raises(ConfigurationError) as excinfo:
        validate_secret_config(settings)
    assert "长度" in str(excinfo.value)


def test_validate_secret_config_rejects_identical_production_secrets(monkeypatch):
    shared = "x" * 40
    settings = _production_settings(monkeypatch, jwt=shared, enc=shared)
    with pytest.raises(ConfigurationError) as excinfo:
        validate_secret_config(settings)
    assert "职责分离" in str(excinfo.value)


def test_validate_secret_config_accepts_strong_distinct_production_secrets(monkeypatch):
    settings = _production_settings(
        monkeypatch, jwt="J" * 40, enc="E" * 40
    )
    validate_secret_config(settings)  # must not raise


def _clear_db_pool_env(monkeypatch):
    for name in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_RECYCLE",
        "DB_POOL_TIMEOUT",
        "DB_POOL_PRE_PING",
        "WORKER_DB_POOL_SIZE",
        "WORKER_DB_MAX_OVERFLOW",
        "WORKER_DB_POOL_RECYCLE",
        "WORKER_DB_POOL_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_db_engine_options_defaults_for_postgres(monkeypatch):
    _clear_db_pool_env(monkeypatch)
    options = build_db_engine_options("api", url="postgresql+psycopg://x@localhost/db")

    assert options == {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 1800,
        "pool_timeout": 30,
        "pool_pre_ping": True,
    }


def test_db_engine_options_env_overrides(monkeypatch):
    _clear_db_pool_env(monkeypatch)
    monkeypatch.setenv("DB_POOL_SIZE", "20")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "40")
    monkeypatch.setenv("DB_POOL_RECYCLE", "600")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "15")
    monkeypatch.setenv("DB_POOL_PRE_PING", "false")

    options = build_db_engine_options("api", url="postgresql+psycopg://x@localhost/db")

    assert options["pool_size"] == 20
    assert options["max_overflow"] == 40
    assert options["pool_recycle"] == 600
    assert options["pool_timeout"] == 15
    assert options["pool_pre_ping"] is False


def test_db_engine_options_worker_role_overrides_then_falls_back(monkeypatch):
    _clear_db_pool_env(monkeypatch)
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("WORKER_DB_POOL_SIZE", "12")  # worker-specific override

    worker = build_db_engine_options("worker", url="postgresql+psycopg://x@localhost/db")
    api = build_db_engine_options("api", url="postgresql+psycopg://x@localhost/db")

    assert worker["pool_size"] == 12  # uses worker override
    assert api["pool_size"] == 5  # api uses shared base
    assert worker["max_overflow"] == 10  # no worker override -> falls back to default


def test_db_engine_options_sqlite_uses_default_pool(monkeypatch):
    _clear_db_pool_env(monkeypatch)
    options = build_db_engine_options("api", url="sqlite+pysqlite:///:memory:")

    # SQLite rejects QueuePool sizing args -> only pre_ping is passed
    assert options == {"pool_pre_ping": True}

_ADAPTIVE_CHUNK_ENV_NAMES = (
    "CHUNKING_MODE",
    "CHUNK_MIN_TOKENS",
    "CHUNK_TARGET_TOKENS",
    "CHUNK_MAX_TOKENS",
    "CHUNK_OVERLAP_TOKENS",
    "CHUNK_PARENT_MAX_TOKENS",
    "CHUNK_TOKENIZER_NAME",
    "CHUNK_SEMANTIC_SPLIT_ENABLED",
    "QA_STRICT_PROVENANCE_ENABLED",
    "CHUNK_INDEXING_ENABLED",
    "HYBRID_CHUNK_RETRIEVAL_ENABLED",
    "PARENT_CONTEXT_ENABLED",
    "RETRIEVAL_VECTOR_TOP_K",
    "RETRIEVAL_TEXT_TOP_K",
    "RETRIEVAL_FINAL_TOP_K",
    "RETRIEVAL_HYBRID_QA_VECTOR_TOP_K",
    "RETRIEVAL_HYBRID_CHUNK_VECTOR_TOP_K",
    "RETRIEVAL_HYBRID_QA_TEXT_TOP_K",
    "RETRIEVAL_HYBRID_CHUNK_TEXT_TOP_K",
    "RETRIEVAL_RRF_K",
    "RETRIEVAL_CHUNK_VECTOR_WEIGHT",
    "RETRIEVAL_CHUNK_TEXT_WEIGHT",
    "RETRIEVAL_QA_VECTOR_WEIGHT",
    "RETRIEVAL_QA_TEXT_WEIGHT",
)


def _clear_adaptive_chunk_env(monkeypatch):
    for name in _ADAPTIVE_CHUNK_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_adaptive_chunking_settings_defaults_are_spec_values(monkeypatch):
    _clear_adaptive_chunk_env(monkeypatch)

    current = Settings()

    assert current.chunking_mode == "legacy"
    assert (current.chunk_min_tokens, current.chunk_target_tokens, current.chunk_max_tokens) == (100, 450, 800)
    assert current.chunk_overlap_tokens == 64
    assert current.chunk_parent_max_tokens == 1800
    assert current.chunk_tokenizer_name == "local-tiktoken-cl100k_base"
    assert current.chunk_semantic_split_enabled is False
    assert current.qa_strict_provenance_enabled is False
    assert current.chunk_indexing_enabled is False
    assert current.hybrid_chunk_retrieval_enabled is False
    assert current.parent_context_enabled is False
    assert current.retrieval_rrf_k == 60
    assert (
        current.retrieval_hybrid_qa_vector_top_k,
        current.retrieval_hybrid_chunk_vector_top_k,
        current.retrieval_hybrid_qa_text_top_k,
        current.retrieval_hybrid_chunk_text_top_k,
    ) == (10, 10, 10, 10)
    assert current.retrieval_rrf_channel_weights == {
        "qa_vector": 1.0,
        "qa_text": 1.0,
        "chunk_vector": 1.0,
        "chunk_text": 1.0,
    }


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({"CHUNKING_MODE": "unknown"}, "CHUNKING_MODE"),
        ({"CHUNK_TOKENIZER_NAME": "unknown-tokenizer"}, "CHUNK_TOKENIZER_NAME"),
        ({"CHUNK_MIN_TOKENS": "451"}, "min_tokens"),
        ({"CHUNK_OVERLAP_TOKENS": "100"}, "overlap_tokens"),
        ({"CHUNK_PARENT_MAX_TOKENS": "799"}, "parent_max_tokens"),
        ({"RETRIEVAL_RRF_K": "0"}, "RETRIEVAL_RRF_K"),
        ({"RETRIEVAL_QA_VECTOR_WEIGHT": "-0.1"}, "RETRIEVAL_QA_VECTOR_WEIGHT"),
        ({"RETRIEVAL_CHUNK_TEXT_WEIGHT": "nan"}, "RETRIEVAL_CHUNK_TEXT_WEIGHT"),
        ({"RETRIEVAL_CHUNK_VECTOR_WEIGHT": "inf"}, "RETRIEVAL_CHUNK_VECTOR_WEIGHT"),
    ],
)
def test_validate_chunking_config_rejects_invalid_values(monkeypatch, environment, expected):
    from server.app.core.config import validate_chunking_config

    _clear_adaptive_chunk_env(monkeypatch)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=expected):
        validate_chunking_config(Settings())


def test_validate_chunking_config_rejects_hybrid_candidate_budgets_above_qa_only_cap(monkeypatch):
    from server.app.core.config import validate_chunking_config

    _clear_adaptive_chunk_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_VECTOR_TOP_K", "10")
    monkeypatch.setenv("RETRIEVAL_HYBRID_QA_VECTOR_TOP_K", "6")
    monkeypatch.setenv("RETRIEVAL_HYBRID_CHUNK_VECTOR_TOP_K", "5")

    with pytest.raises(ConfigurationError, match="RETRIEVAL_HYBRID_QA_VECTOR_TOP_K"):
        validate_chunking_config(Settings())


def test_validate_chunking_config_requires_hybrid_for_parent_context(monkeypatch):
    from server.app.core.config import validate_chunking_config

    _clear_adaptive_chunk_env(monkeypatch)
    monkeypatch.setenv("PARENT_CONTEXT_ENABLED", "true")

    with pytest.raises(ConfigurationError, match="PARENT_CONTEXT_ENABLED"):
        validate_chunking_config(Settings())
