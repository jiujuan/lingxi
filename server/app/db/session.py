from collections.abc import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server.app.core.config import build_db_engine_options, settings

# Role selects pool sizing: the Celery worker sets DB_ROLE=worker (see
# celery_app) so it can be tuned independently from the API process.
_DB_ROLE = os.getenv("DB_ROLE", "api")

engine = create_engine(
    settings.database_url,
    **build_db_engine_options(_DB_ROLE, url=settings.database_url),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session

