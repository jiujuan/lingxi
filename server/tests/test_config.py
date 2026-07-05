from server.app.core.config import (
    Settings,
    build_database_url,
    build_redis_url,
    load_env_file,
    parse_csv_env,
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
    assert settings.secret_encryption_key == "secret-envelope-key"
    assert settings.seed_admin_email == "root@example.com"
    assert settings.seed_admin_password == "Root123!"
    assert settings.seed_employee_email == "staff@example.com"
    assert settings.seed_employee_password == "Staff123!"


def test_empty_secret_encryption_key_falls_back_to_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-secret")
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "")

    settings = Settings()

    assert settings.secret_encryption_key == "jwt-secret"
