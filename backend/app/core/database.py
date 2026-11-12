"""Database engine, connection pooling, and session management for GigScore."""
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional
import logging

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
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


def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    """Ensure SQLite enforces FOREIGN KEY constraints and ON DELETE CASCADE."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_db_engine(raw_url: str) -> Engine:
    """Create a SQLAlchemy Engine with appropriate dialect pooling and SQLite FK enforcement."""
    normalized_url = get_normalized_database_url(raw_url)
    is_sqlite_url = normalized_url.startswith("sqlite")

    kwargs: Dict[str, Any] = {
        "echo": False,
    }

    if is_sqlite_url:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Neon serverless / PostgreSQL pooler settings
        kwargs.update(
            {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_recycle": 300,  # 5 minutes to prevent stale PgBouncer connections
                "pool_pre_ping": True,  # Test connection health before dispensing
                "pool_timeout": 30,
            }
        )

    db_engine = create_engine(normalized_url, **kwargs)
    if is_sqlite_url:
        event.listen(db_engine, "connect", _enable_sqlite_foreign_keys)
    return db_engine


DATABASE_URL = get_normalized_database_url(settings.DATABASE_URL)
is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_db_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


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


def _sync_nullable_columns(target_engine: Engine) -> None:
    """Non-destructively add any missing nullable columns to pre-existing tables."""
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    dialect_name = target_engine.dialect.name

    with target_engine.begin() as conn:
        for table_name, table_obj in Base.metadata.tables.items():
            if table_name not in existing_tables:
                continue
            existing_cols = {
                col["name"] for col in inspector.get_columns(table_name)
            }
            if dialect_name == "postgresql" and table_name == "score_audits":
                conn.execute(
                    text(
                        'ALTER TABLE "score_audits" ALTER COLUMN "gig_score" DROP NOT NULL'
                    )
                )
            for col in table_obj.columns:
                if col.name not in existing_cols and col.nullable:
                    col_type_sql = col.type.compile(dialect=target_engine.dialect)
                    if dialect_name == "postgresql":
                        stmt = f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col.name}" {col_type_sql}'
                    else:
                        stmt = f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type_sql}'
                    logger.info(
                        "Adding missing nullable column %s.%s (%s)",
                        table_name,
                        col.name,
                        col_type_sql,
                    )
                    conn.execute(text(stmt))


def init_db(bind_engine: Optional[Engine] = None) -> None:
    """Initialize all registered database tables and sync additive nullable columns."""
    # Import all models here so that they are registered on the metadata
    import app.models.db_models  # noqa: F401

    target_engine = bind_engine or engine
    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=target_engine)
    _sync_nullable_columns(target_engine)
    logger.info("Database schema initialized successfully.")
