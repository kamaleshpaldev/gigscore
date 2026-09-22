"""Database engine, connection pooling, and session management for GigScore."""
from contextlib import contextmanager
from typing import Generator
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_normalized_database_url(raw_url: str) -> str:
    """Normalize database URL for SQLAlchemy and psycopg2 driver compatibility."""
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = get_normalized_database_url(settings.DATABASE_URL)

# Configure engine with connection pooling optimized for Neon PostgreSQL (serverless / PgBouncer)
is_sqlite = DATABASE_URL.startswith("sqlite")

engine_kwargs = {
    "echo": settings.APP_ENV.lower() == "development" and False,  # set True if query logging desired
}

if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Neon serverless pooler settings
    engine_kwargs.update(
        {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_recycle": 300,  # 5 minutes to prevent stale PgBouncer connections
            "pool_pre_ping": True,  # Test connection health before dispensing
            "pool_timeout": 30,
        }
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for obtaining a database session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager for standalone tasks, background workers, or scripts."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Initialize all registered database tables."""
    # Import all models here so that they are registered on the metadata
    import app.models.db_models  # noqa: F401

    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialized successfully.")
