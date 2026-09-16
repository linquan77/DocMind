"""SQLite database setup.

The API handlers are async, while SQLAlchemy's synchronous SQLite driver is
run in worker threads by the document service. This keeps the first iteration
small and allows a later switch to PostgreSQL without changing API contracts.
"""

from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_engine():
    database_url = get_settings().database_url
    # SQLite 默认限制连接只能在创建它的线程使用；API 会把数据库操作调度到工作线程。
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    if database_url.startswith("sqlite"):
        # SQLite 默认不执行外键级联；显式开启后，删除文档或 Wiki 来源时关联记录才会同步清理。
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache(maxsize=1)
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    # 必须先导入模型，SQLAlchemy 的 metadata 才能发现并创建全部表。
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def reset_database_cache() -> None:
    """Reset cached engine/session objects for isolated tests."""

    # 仅供测试切换临时数据库，业务代码不应在运行期间重置连接池。
    engine = get_engine()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    engine.dispose()
