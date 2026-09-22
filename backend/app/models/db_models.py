"""SQLAlchemy database models for GigScore."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


# Use JSONB for PostgreSQL dialect, with standard JSON fallback
JSONType = JSON().with_variant(JSONB, "postgresql")


class Worker(Base):
    """Worker entity representing gig platform workers."""

    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    worker_uid = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    e_shram_id = Column(String(50), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    consent_records = relationship(
        "ConsentRecord",
        back_populates="worker",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    score_audits = relationship(
        "ScoreAudit",
        back_populates="worker",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Worker(id={self.id}, worker_uid='{self.worker_uid}', name='{self.name}')>"


class ConsentRecord(Base):
    """Consent record tracking Account Aggregator permissions."""

    __tablename__ = "consent_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    worker_uid = Column(
        String(64),
        ForeignKey("workers.worker_uid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    consent_handle = Column(String(255), unique=True, index=True, nullable=False)
    status = Column(String(50), default="PENDING", nullable=False)
    agg_provider = Column(String(50), default="Setu_AA", nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    worker = relationship("Worker", back_populates="consent_records")

    def __repr__(self) -> str:
        return (
            f"<ConsentRecord(id={self.id}, worker_uid='{self.worker_uid}', "
            f"status='{self.status}', provider='{self.agg_provider}')>"
        )


class ScoreAudit(Base):
    """Audit log of computed alternative credit scores queried by lenders."""

    __tablename__ = "score_audits"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    worker_uid = Column(
        String(64),
        ForeignKey("workers.worker_uid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    gig_score = Column(Integer, nullable=False)
    risk_tier = Column(String(50), nullable=False)
    reason_codes = Column(JSONType, nullable=True)
    queried_by_lender_id = Column(String(100), nullable=True)
    calculated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    worker = relationship("Worker", back_populates="score_audits")

    def __repr__(self) -> str:
        return (
            f"<ScoreAudit(id={self.id}, worker_uid='{self.worker_uid}', "
            f"score={self.gig_score}, risk_tier='{self.risk_tier}')>"
        )
