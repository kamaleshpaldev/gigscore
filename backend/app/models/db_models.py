"""SQLAlchemy database models for GigScore."""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


# Use JSONB for PostgreSQL dialect, with standard JSON fallback for SQLite
JSONType = JSON().with_variant(JSONB, "postgresql")


class Worker(Base):
    """Worker entity representing gig platform workers."""

    __tablename__ = "workers"

    # Existing columns (preserved)
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

    # Phase 1 additive nullable columns
    persona = Column(String(64), nullable=True)
    primary_city = Column(String(100), nullable=True)
    platforms = Column(JSONType, nullable=True)
    tenure_months = Column(Integer, nullable=True)

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
    billing_records = relationship(
        "BillingRecord",
        back_populates="worker",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Worker(id={self.id}, worker_uid='{self.worker_uid}', name='{self.name}')>"


class ConsentRecord(Base):
    """Consent record tracking Account Aggregator permissions."""

    __tablename__ = "consent_records"

    # Existing columns (preserved)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    worker_uid = Column(
        String(64),
        ForeignKey("workers.worker_uid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    consent_handle = Column(String(255), unique=True, index=True, nullable=False)
    status = Column(
        String(50), default="PENDING", server_default="PENDING", nullable=False
    )
    agg_provider = Column(
        String(50), default="Setu_AA", server_default="Setu_AA", nullable=False
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Phase 1 additive nullable columns for full consent lifecycle
    purpose = Column(String(100), default="CREDIT_SCORING", nullable=True)
    lender_id = Column(String(100), index=True, nullable=True)
    requested_platforms = Column(JSONType, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revocation_reason = Column(String(255), nullable=True)

    # Relationships
    worker = relationship("Worker", back_populates="consent_records")

    def __repr__(self) -> str:
        return (
            f"<ConsentRecord(id={self.id}, worker_uid='{self.worker_uid}', "
            f"status='{self.status}', provider='{self.agg_provider}')>"
        )


class Lender(Base):
    """Registered lender organization with hashed API-key authentication and billing configuration."""

    __tablename__ = "lenders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lender_id = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    api_key_hash = Column(String(128), unique=True, index=True, nullable=False)
    api_key_prefix = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    rate_limit_per_minute = Column(
        Integer, default=60, server_default="60", nullable=False
    )
    fee_per_check_inr = Column(
        Float, default=30.0, server_default="30.0", nullable=False
    )
    total_checks = Column(Integer, default=0, server_default="0", nullable=False)
    total_billed_inr = Column(
        Float, default=0.0, server_default="0.0", nullable=False
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    billing_records = relationship(
        "BillingRecord",
        back_populates="lender",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Lender(id={self.id}, lender_id='{self.lender_id}', "
            f"name='{self.name}', active={self.is_active})>"
        )


class ScoreAudit(Base):
    """Audit log of computed alternative credit scores queried by lenders."""

    __tablename__ = "score_audits"

    # Existing columns (preserved)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    worker_uid = Column(
        String(64),
        ForeignKey("workers.worker_uid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    gig_score = Column(Integer, nullable=True)
    risk_tier = Column(String(50), nullable=False)
    reason_codes = Column(JSONType, nullable=True)
    queried_by_lender_id = Column(String(100), nullable=True)
    calculated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Phase 1 additive nullable columns for auditability, authenticity & model provenance
    request_id = Column(String(64), unique=True, index=True, nullable=True)
    consent_handle = Column(String(255), index=True, nullable=True)
    score_band = Column(String(50), nullable=True)
    calibrated_probability = Column(Float, nullable=True)
    top_factors = Column(JSONType, nullable=True)
    authenticity_status = Column(String(50), nullable=True)
    authenticity_flags = Column(JSONType, nullable=True)
    needs_review = Column(Boolean, default=False, nullable=True)
    model_version = Column(String(100), nullable=True)
    scoring_engine = Column(String(50), nullable=True)
    fee_charged_inr = Column(Float, nullable=True)

    # Relationships
    worker = relationship("Worker", back_populates="score_audits")

    def __repr__(self) -> str:
        return (
            f"<ScoreAudit(id={self.id}, request_id='{self.request_id}', "
            f"worker_uid='{self.worker_uid}', score={self.gig_score}, "
            f"risk_tier='{self.risk_tier}', model='{self.model_version}')>"
        )


class BillingRecord(Base):
    """Per-check billing ledger entry for lender score queries (default ₹30 per check)."""

    __tablename__ = "billing_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    billing_uid = Column(String(64), unique=True, index=True, nullable=False)
    lender_id = Column(
        String(100),
        ForeignKey("lenders.lender_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    request_id = Column(String(64), unique=True, index=True, nullable=False)
    worker_uid = Column(
        String(64),
        ForeignKey("workers.worker_uid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    consent_handle = Column(String(255), nullable=True)
    fee_inr = Column(Float, default=30.0, server_default="30.0", nullable=False)
    currency = Column(String(10), default="INR", server_default="INR", nullable=False)
    status = Column(
        String(50), default="BILLED", server_default="BILLED", nullable=False
    )
    billed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    lender = relationship("Lender", back_populates="billing_records")
    worker = relationship("Worker", back_populates="billing_records")

    def __repr__(self) -> str:
        return (
            f"<BillingRecord(id={self.id}, billing_uid='{self.billing_uid}', "
            f"lender_id='{self.lender_id}', fee_inr={self.fee_inr}, status='{self.status}')>"
        )
