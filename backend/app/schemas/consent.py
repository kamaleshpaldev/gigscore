"""Pydantic schemas for Consent lifecycle and Mock Account Aggregator endpoints."""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.schemas.common import DisclaimerMixin


class ConsentStatusEnum(str, Enum):
    """Supported Account Aggregator consent lifecycle states."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConsentPurposeEnum(str, Enum):
    """Supported Account Aggregator consent purposes."""

    CREDIT_SCORING = "CREDIT_SCORING"
    LOAN_UNDERWRITING = "LOAN_UNDERWRITING"
    GIG_SCORE_VERIFICATION = "GIG_SCORE_VERIFICATION"


class ConsentRequestCreate(BaseModel):
    """Request payload for POST /consent/request."""

    worker_uid: str = Field(..., min_length=2, max_length=64)
    worker_name: Optional[str] = Field(default="Synthetic Gig Worker", max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)
    e_shram_id: Optional[str] = Field(default=None, max_length=50)
    lender_id: Optional[str] = Field(default=None, max_length=100)
    purpose: str = Field(default=ConsentPurposeEnum.CREDIT_SCORING.value)
    requested_platforms: List[str] = Field(
        default_factory=lambda: ["Swiggy", "Zomato", "Uber"]
    )
    agg_provider: str = Field(default="Setu_AA")
    expiry_hours: int = Field(default=24, ge=1, le=720)

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, v: str) -> str:
        normalized = v.strip().upper()
        allowed = {p.upper() for p in settings.ALLOWED_CONSENT_PURPOSES}
        if normalized not in allowed:
            raise ValueError(
                f"Invalid consent purpose '{v}'. Allowed purposes: {sorted(allowed)}"
            )
        return normalized


class ConsentApproveRequest(BaseModel):
    """Request payload for POST /consent/approve."""

    consent_handle: str = Field(..., min_length=3, max_length=255)
    worker_uid: str = Field(..., min_length=2, max_length=64)


class ConsentRevokeRequest(BaseModel):
    """Request payload for POST /consent/revoke."""

    consent_handle: str = Field(..., min_length=3, max_length=255)
    worker_uid: str = Field(..., min_length=2, max_length=64)
    reason: Optional[str] = Field(
        default="Worker revoked consent", max_length=255
    )


class ConsentResponse(DisclaimerMixin):
    """Response payload for consent creation, approval, and revocation."""

    id: Optional[int] = None
    consent_handle: str
    worker_uid: str
    status: ConsentStatusEnum
    purpose: Optional[str] = ConsentPurposeEnum.CREDIT_SCORING.value
    lender_id: Optional[str] = None
    agg_provider: str
    requested_platforms: Optional[List[str]] = None
    approved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlatformMonthlyEarning(BaseModel):
    """Single month platform & bank-verified earnings entry (ephemeral AA payload)."""

    month: str = Field(..., description="YYYY-MM period identifier")
    platform: str = Field(..., description="Gig platform name (e.g., Swiggy, Uber)")
    claimed_earnings_inr: float = Field(..., ge=0.0)
    bank_verified_credit_inr: float = Field(..., ge=0.0)
    trips_or_orders_completed: int = Field(default=0, ge=0)
    active_days: int = Field(default=0, ge=0, le=31)
    platform_rating: Optional[float] = Field(default=None, ge=1.0, le=5.0)


class MockAAFetchResponse(DisclaimerMixin):
    """Response payload for GET /mock-aa/fetch/{consent_id}."""

    consent_handle: str
    worker_uid: str
    agg_provider: str
    consent_status: ConsentStatusEnum
    persona: Optional[str] = None
    tenure_months: int = Field(..., ge=0)
    platforms_connected: List[str]
    monthly_earnings: List[PlatformMonthlyEarning]
    aggregated_summary: Dict[str, float]
    raw_data_persisted: bool = Field(
        default=False,
        description="Always False: raw financial data is processed ephemerally and never persisted.",
    )
    fetched_at: datetime

