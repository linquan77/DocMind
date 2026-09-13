"""SQLite database setup.

The API handlers are async, while SQLAlchemy's synchronous SQLite driver is
run in worker threads by the document service. This keeps the first iteration
small and allows a later switch to PostgreSQL without changing API contracts.
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_engine():
    database_url = get_settings().database_url
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    # Import models before create_all so SQLAlchemy knows every table.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def reset_database_cache() -> None:
    """Reset cached engine/session objects for isolated tests."""

    engine = get_engine()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    engine.dispose()
