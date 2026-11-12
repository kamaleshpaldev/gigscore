"""Scoring Pipeline Endpoint (POST /score).

Enforces:
1. Lender API-Key authentication & per-lender rate limiting.
2. Active, approved, unrevoked, unexpired, purpose-matched, lender-authorized consent.
3. Ephemeral AA data retrieval and Data Authenticity verification.
4. NEEDS_REVIEW handling (no credit score generated, ₹0 billed).
5. Calibrated XGBoost (or explicit rule-scorecard fallback) scoring + SHAP plain-English explanations.
6. Transactional ₹30 billing and full audit logging for both successful and failed attempts.

Prototype - synthetic data only. Not for real lending decisions.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT, settings
from app.core.database import get_db
from app.core.security import get_authenticated_lender
from app.ml.authenticity import evaluate_earnings_authenticity
from app.ml.features import compute_worker_features
from app.ml.model import model_service
from app.models.db_models import (
    BillingRecord,
    ConsentRecord,
    Lender,
    ScoreAudit,
    Worker,
)
from app.routes.consent import expire_and_deduplicate_consents
from app.schemas.consent import ConsentStatusEnum
from app.schemas.score import (
    AuthenticityStatusEnum,
    ScoreRequest,
    ScoreResponse,
    ScoringEngineEnum,
)
from app.services.mock_aa import fetch_ephemeral_aa_earnings

router = APIRouter(tags=["Scoring Engine"])


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _record_failed_score_audit(
    db: Session,
    worker_uid: str,
    consent_handle: str,
    lender_id: str,
    request_id: str,
    error_code: str,
) -> None:
    """Record an audit log entry for rejected/failed scoring attempts with ₹0 billed."""
    worker = db.query(Worker).filter(Worker.worker_uid == worker_uid).first()
    if worker is None:
        return
    audit = ScoreAudit(
        worker_uid=worker_uid,
        request_id=request_id,
        consent_handle=consent_handle,
        gig_score=None,
        risk_tier=f"REJECTED_{error_code}",
        score_band="N/A",
        calibrated_probability=None,
        reason_codes=[error_code],
        top_factors=[],
        authenticity_status="NOT_EVALUATED",
        authenticity_flags=[error_code],
        needs_review=False,
        model_version=model_service.active_model_version,
        scoring_engine=(
            ScoringEngineEnum.XGBOOST.value
            if model_service.is_xgboost_loaded
            else ScoringEngineEnum.RULE_SCORECARD.value
        ),
        queried_by_lender_id=lender_id,
        fee_charged_inr=0.0,
    )
    db.add(audit)
    db.commit()


@router.post("/score", response_model=ScoreResponse)
def compute_worker_score(
    payload: ScoreRequest,
    force_fallback: bool = Query(
        default=False,
        description="Optional flag to explicitly evaluate with the baseline rule scorecard.",
    ),
    lender: Lender = Depends(get_authenticated_lender),
    db: Session = Depends(get_db),
) -> ScoreResponse:
    """Compute a portable GigScore (300-900) after verifying consent and data authenticity."""
    request_id = f"req_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)

    # 1. Verify lender_id consistency if explicitly provided in request body
    if payload.lender_id and payload.lender_id != lender.lender_id:
        _record_failed_score_audit(
            db,
            payload.worker_uid,
            payload.consent_handle,
            lender.lender_id,
            request_id,
            "LENDER_ID_MISMATCH",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "LENDER_ID_MISMATCH",
                "message": "Authenticated lender API key does not match requested lender_id.",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # 2. Expire/deduplicate consents and fetch ConsentRecord
    expire_and_deduplicate_consents(db, payload.worker_uid)
    db.commit()

    consent: Optional[ConsentRecord] = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.consent_handle == payload.consent_handle)
        .first()
    )
    if consent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "CONSENT_NOT_FOUND",
                "message": f"Consent handle '{payload.consent_handle}' does not exist.",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    if consent.worker_uid != payload.worker_uid:
        _record_failed_score_audit(
            db,
            consent.worker_uid,
            payload.consent_handle,
            lender.lender_id,
            request_id,
            "CONSENT_WORKER_MISMATCH",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_WORKER_MISMATCH",
                "message": "Consent handle does not belong to the specified worker_uid.",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # Enforce lender isolation on consent ownership
    if consent.lender_id and consent.lender_id != lender.lender_id:
        _record_failed_score_audit(
            db,
            payload.worker_uid,
            payload.consent_handle,
            lender.lender_id,
            request_id,
            "LENDER_UNAUTHORIZED_FOR_CONSENT",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "LENDER_UNAUTHORIZED_FOR_CONSENT",
                "message": f"Lender '{lender.lender_id}' is not authorized to use consent granted to '{consent.lender_id}'.",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # Check revocation
    if (
        consent.status == ConsentStatusEnum.REVOKED.value
        or consent.revoked_at is not None
    ):
        _record_failed_score_audit(
            db,
            payload.worker_uid,
            payload.consent_handle,
            lender.lender_id,
            request_id,
            "CONSENT_REVOKED",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_REVOKED",
                "message": "Scoring blocked: worker has revoked this consent.",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # Check expiry
    exp = _ensure_utc(consent.expires_at)
    if (exp is not None and exp <= now) or (
        consent.status == ConsentStatusEnum.EXPIRED.value
    ):
        consent.status = ConsentStatusEnum.EXPIRED.value
        db.commit()
        _record_failed_score_audit(
            db,
            payload.worker_uid,
            payload.consent_handle,
            lender.lender_id,
            request_id,
            "CONSENT_EXPIRED",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_EXPIRED",
                "message": "Scoring blocked: consent has expired.",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # Check approval status
    if consent.status != ConsentStatusEnum.APPROVED.value:
        _record_failed_score_audit(
            db,
            payload.worker_uid,
            payload.consent_handle,
            lender.lender_id,
            request_id,
            "CONSENT_NOT_APPROVED",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_NOT_APPROVED",
                "message": f"Scoring blocked: consent status is '{consent.status}' (must be APPROVED).",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # Check purpose validation
    allowed_purposes = {p.upper() for p in settings.ALLOWED_CONSENT_PURPOSES}
    consent_purpose = (consent.purpose or "CREDIT_SCORING").strip().upper()
    if consent_purpose not in allowed_purposes:
        _record_failed_score_audit(
            db,
            payload.worker_uid,
            payload.consent_handle,
            lender.lender_id,
            request_id,
            "CONSENT_PURPOSE_MISMATCH",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_PURPOSE_MISMATCH",
                "message": f"Consent purpose '{consent.purpose}' is not valid for credit scoring.",
                "request_id": request_id,
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # 3. Retrieve ephemeral AA earnings in memory
    worker = (
        db.query(Worker).filter(Worker.worker_uid == payload.worker_uid).first()
    )
    declared_tenure = worker.tenure_months if worker else None

    if payload.override_earnings is not None:
        monthly_records = [item.model_dump() for item in payload.override_earnings]
    else:
        aa_payload = fetch_ephemeral_aa_earnings(
            worker_uid=payload.worker_uid,
            declared_tenure_override=declared_tenure,
        )
        monthly_records = aa_payload["monthly_earnings"]
        if declared_tenure is None:
            declared_tenure = aa_payload["tenure_months"]

    # 4. Run Data Authenticity Engine
    authenticity_report = evaluate_earnings_authenticity(
        monthly_records=monthly_records,
        declared_tenure_months=declared_tenure,
    )

    if authenticity_report.status == AuthenticityStatusEnum.NEEDS_REVIEW:
        # Flagged worker: do NOT generate a credit score and do NOT charge the lender
        active_engine = (
            ScoringEngineEnum.RULE_SCORECARD
            if (force_fallback or not model_service.is_xgboost_loaded)
            else ScoringEngineEnum.XGBOOST
        )
        active_version = (
            settings.FALLBACK_MODEL_VERSION
            if active_engine == ScoringEngineEnum.RULE_SCORECARD
            else model_service.active_model_version
        )
        flagged_audit = ScoreAudit(
            worker_uid=payload.worker_uid,
            request_id=request_id,
            consent_handle=payload.consent_handle,
            gig_score=None,
            risk_tier="NEEDS_REVIEW",
            score_band="NEEDS_REVIEW",
            calibrated_probability=None,
            reason_codes=["AUTHENTICITY_FLAGGED_NEEDS_REVIEW"],
            top_factors=[],
            authenticity_status=AuthenticityStatusEnum.NEEDS_REVIEW.value,
            authenticity_flags=authenticity_report.flags,
            needs_review=True,
            model_version=active_version,
            scoring_engine=active_engine.value,
            queried_by_lender_id=lender.lender_id,
            fee_charged_inr=0.0,
        )
        db.add(flagged_audit)
        db.commit()
        db.refresh(flagged_audit)

        return ScoreResponse(
            request_id=request_id,
            worker_uid=payload.worker_uid,
            consent_handle=payload.consent_handle,
            gig_score=None,
            risk_tier="NEEDS_REVIEW",
            score_band="NEEDS_REVIEW",
            calibrated_probability=None,
            reason_codes=["AUTHENTICITY_FLAGGED_NEEDS_REVIEW"],
            top_factors=[],
            top_positive_factors=[],
            top_negative_factors=[],
            improvement_tips=[
                "Your platform payout records require manual verification due to discrepancies between claimed earnings and bank-verified credits."
            ],
            authenticity=authenticity_report,
            authenticity_status=AuthenticityStatusEnum.NEEDS_REVIEW,
            needs_review=True,
            model_version=active_version,
            scoring_engine=active_engine,
            queried_by_lender_id=lender.lender_id,
            fee_charged_inr=0.0,
            calculated_at=flagged_audit.calculated_at or now,
        )

    # 5. Compute features & run model inference
    features = compute_worker_features(
        monthly_records=monthly_records,
        declared_tenure_months=declared_tenure,
    )
    prediction = model_service.predict_score(
        raw_features=features,
        force_fallback=force_fallback,
    )

    fee_inr = float(
        lender.fee_per_check_inr
        if lender.fee_per_check_inr is not None
        else settings.SCORE_CHECK_FEE_INR
    )
    billing_uid = f"bill_{uuid.uuid4().hex[:16]}"

    # 6. Atomic database transaction for ScoreAudit + BillingRecord + Lender usage counters
    audit_record = ScoreAudit(
        worker_uid=payload.worker_uid,
        request_id=request_id,
        consent_handle=payload.consent_handle,
        gig_score=prediction["gig_score"],
        risk_tier=prediction["risk_tier"],
        score_band=prediction["score_band"],
        calibrated_probability=prediction["calibrated_probability"],
        reason_codes=prediction["reason_codes"],
        top_factors=[f.model_dump() for f in prediction["top_factors"]],
        authenticity_status=AuthenticityStatusEnum.VERIFIED.value,
        authenticity_flags=[],
        needs_review=False,
        model_version=prediction["model_version"],
        scoring_engine=prediction["scoring_engine"],
        queried_by_lender_id=lender.lender_id,
        fee_charged_inr=fee_inr,
    )
    billing_record = BillingRecord(
        billing_uid=billing_uid,
        lender_id=lender.lender_id,
        request_id=request_id,
        worker_uid=payload.worker_uid,
        consent_handle=payload.consent_handle,
        fee_inr=fee_inr,
        currency=settings.CURRENCY,
        status="BILLED",
    )
    lender.total_checks = int(lender.total_checks or 0) + 1
    lender.total_billed_inr = round(float(lender.total_billed_inr or 0.0) + fee_inr, 2)

    db.add(audit_record)
    db.add(billing_record)
    db.commit()
    db.refresh(audit_record)

    return ScoreResponse(
        request_id=request_id,
        worker_uid=payload.worker_uid,
        consent_handle=payload.consent_handle,
        gig_score=prediction["gig_score"],
        risk_tier=prediction["risk_tier"],
        score_band=prediction["score_band"],
        calibrated_probability=prediction["calibrated_probability"],
        reason_codes=prediction["reason_codes"],
        top_factors=prediction["top_factors"],
        top_positive_factors=prediction.get("top_positive_factors", []),
        top_negative_factors=prediction.get("top_negative_factors", []),
        improvement_tips=prediction.get("improvement_tips", []),
        authenticity=authenticity_report,
        authenticity_status=AuthenticityStatusEnum.VERIFIED,
        needs_review=False,
        model_version=prediction["model_version"],
        scoring_engine=ScoringEngineEnum(prediction["scoring_engine"]),
        queried_by_lender_id=lender.lender_id,
        fee_charged_inr=fee_inr,
        calculated_at=audit_record.calculated_at or now,
    )

