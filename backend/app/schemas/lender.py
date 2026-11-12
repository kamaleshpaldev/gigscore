"""Pydantic schemas for Lender usage, billing, and score audit retrieval."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DisclaimerMixin


class BillingRecordItem(BaseModel):
    """Individual per-check billing entry."""

    billing_uid: str
    lender_id: str
    request_id: str
    worker_uid: str
    consent_handle: Optional[str] = None
    fee_inr: float
    currency: str = "INR"
    status: str = "BILLED"
    billed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LenderUsageResponse(DisclaimerMixin):
    """Response payload for GET /lenders/{id}/usage."""

    lender_id: str
    lender_name: str
    is_active: bool
    rate_limit_per_minute: int
    fee_per_check_inr: float
    currency: str = "INR"
    total_checks: int
    total_billed_inr: float
    recent_billing_records: List[BillingRecordItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AuditDetailResponse(DisclaimerMixin):
    """Response payload for GET /audit/{request_id}."""

    request_id: str
    worker_uid: str
    consent_handle: Optional[str] = None
    queried_by_lender_id: Optional[str] = None
    gig_score: Optional[int] = Field(default=None, ge=300, le=900)
    risk_tier: str
    score_band: Optional[str] = None
    calibrated_probability: Optional[float] = None
    reason_codes: List[str] = Field(default_factory=list)
    top_factors: Optional[List[Dict[str, Any]]] = None
    authenticity_status: Optional[str] = None
    authenticity_flags: Optional[List[str]] = None
    needs_review: bool = False
    model_version: Optional[str] = None
    scoring_engine: Optional[str] = None
    fee_charged_inr: Optional[float] = None
    calculated_at: datetime

    model_config = ConfigDict(from_attributes=True)

