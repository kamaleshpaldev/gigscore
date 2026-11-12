"""Pydantic schemas for POST /score, explainability, and data authenticity."""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DisclaimerMixin
from app.schemas.consent import PlatformMonthlyEarning


class RiskTierEnum(str, Enum):
    """Risk tier classifications mapped from 300-900 GigScore."""

    LOW_RISK = "LOW_RISK"
    MODERATE_RISK = "MODERATE_RISK"
    HIGH_RISK = "HIGH_RISK"
    VERY_HIGH_RISK = "VERY_HIGH_RISK"


class ScoreBandEnum(str, Enum):
    """Standardized score bands between 300 and 900."""

    EXCELLENT_750_900 = "750-900 (Excellent)"
    GOOD_650_749 = "650-749 (Good)"
    FAIR_550_649 = "550-649 (Fair)"
    POOR_300_549 = "300-549 (Poor)"


class AuthenticityStatusEnum(str, Enum):
    """Data authenticity evaluation outcomes."""

    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


class ScoringEngineEnum(str, Enum):
    """Underlying scoring model engine identifier."""

    XGBOOST = "xgboost"
    RULE_SCORECARD = "rule_scorecard"


class ExplainabilityFactor(BaseModel):
    """Plain-English and quantitative SHAP/feature factor explaining the score."""

    feature_name: str
    feature_value: Optional[float] = None
    shap_impact: float = Field(
        ..., description="Signed contribution to creditworthiness"
    )
    direction: str = Field(..., description="POSITIVE or NEGATIVE")
    reason_code: str = Field(..., description="Standardized machine reason code")
    plain_english: str = Field(
        ..., description="Human-readable explanation for worker/lender"
    )


class AuthenticityReport(BaseModel):
    """Structured output of the data authenticity & fraud detection engine."""

    status: AuthenticityStatusEnum
    needs_review: bool = False
    flags: List[str] = Field(default_factory=list)
    bank_vs_claimed_ratio: float = Field(default=1.0, ge=0.0)
    round_number_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_transaction_count: int = Field(default=0, ge=0)
    max_monthly_jump_ratio: float = Field(default=1.0, ge=0.0)
    tenure_consistent: bool = True


class ScoreRequest(BaseModel):
    """Request payload for POST /score."""

    worker_uid: str = Field(..., min_length=2, max_length=64)
    consent_handle: str = Field(..., min_length=3, max_length=255)
    lender_id: Optional[str] = Field(default=None, max_length=100)
    override_earnings: Optional[List[PlatformMonthlyEarning]] = Field(
        default=None,
        description="Optional synthetic earnings override for testing/what-if evaluation.",
    )


class ScoreResponse(DisclaimerMixin):
    """Response payload for POST /score.

    When authenticity_status is NEEDS_REVIEW, gig_score is None (no score is generated)
    and fee_charged_inr is 0.0.
    """

    request_id: str
    worker_uid: str
    consent_handle: str
    gig_score: Optional[int] = Field(default=None, ge=300, le=900)
    risk_tier: str
    score_band: str
    calibrated_probability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)
    top_factors: List[ExplainabilityFactor] = Field(default_factory=list)
    top_positive_factors: List[ExplainabilityFactor] = Field(default_factory=list)
    top_negative_factors: List[ExplainabilityFactor] = Field(default_factory=list)
    improvement_tips: List[str] = Field(default_factory=list)
    authenticity: AuthenticityReport
    authenticity_status: AuthenticityStatusEnum
    needs_review: bool
    model_version: str
    scoring_engine: ScoringEngineEnum
    queried_by_lender_id: Optional[str] = None
    fee_charged_inr: float = Field(default=30.0, ge=0.0)
    calculated_at: datetime

    model_config = ConfigDict(from_attributes=True)

