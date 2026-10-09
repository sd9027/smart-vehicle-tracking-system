"""Database engine, session factory and the FastAPI session dependency.

Transactions are explicit in this project: route handlers call db.commit()
(through services.audit.transactional) when every step has succeeded and
db.rollback() when any step fails. Nothing is committed automatically.
"""
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # drop dead MySQL connections instead of failing a request
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:
    # SQLite (used only by the automated tests) ignores foreign keys unless asked.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """One session per request. close() rolls back anything left uncommitted."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
