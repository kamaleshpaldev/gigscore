"""Lender Usage, Billing, Audit Retrieval, and Transparency/Demo Support Endpoints.

Implements:
- GET /lenders/{id}/usage
- GET /audit/{request_id}
- GET /api/demo/catalog
- GET /api/model/transparency
- GET /api/workers/{worker_uid}/overview

Prototype - synthetic data only. Not for real lending decisions.
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT
from app.core.database import get_db
from app.core.security import get_authenticated_lender, hash_api_key
from app.ml.model import model_service
from app.models.db_models import (
    BillingRecord,
    ConsentRecord,
    Lender,
    ScoreAudit,
    Worker,
)
from app.routes.consent import expire_and_deduplicate_consents
from app.schemas.lender import (
    AuditDetailResponse,
    BillingRecordItem,
    LenderUsageResponse,
)
from app.services.mock_aa import DEMO_LENDERS_CATALOG, DEMO_WORKERS_CATALOG

router = APIRouter(tags=["Lender & Audit Infrastructure"])


@router.get("/lenders/{id}/usage", response_model=LenderUsageResponse)
def get_lender_usage(
    id: str,
    authenticated_lender: Lender = Depends(get_authenticated_lender),
    db: Session = Depends(get_db),
) -> LenderUsageResponse:
    """Return usage counters and recent ₹30 billing ledger entries for an authenticated lender."""
    if authenticated_lender.lender_id != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "LENDER_ISOLATION_VIOLATION",
                "message": f"Authenticated lender '{authenticated_lender.lender_id}' cannot view usage for '{id}'.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    records = (
        db.query(BillingRecord)
        .filter(BillingRecord.lender_id == id)
        .order_by(BillingRecord.billed_at.desc(), BillingRecord.id.desc())
        .limit(50)
        .all()
    )

    return LenderUsageResponse(
        lender_id=authenticated_lender.lender_id,
        lender_name=authenticated_lender.name,
        is_active=authenticated_lender.is_active,
        rate_limit_per_minute=authenticated_lender.rate_limit_per_minute,
        fee_per_check_inr=authenticated_lender.fee_per_check_inr,
        currency="INR",
        total_checks=int(authenticated_lender.total_checks or 0),
        total_billed_inr=round(float(authenticated_lender.total_billed_inr or 0.0), 2),
        recent_billing_records=[
            BillingRecordItem.model_validate(r) for r in records
        ],
    )


@router.get("/audit/{request_id}", response_model=AuditDetailResponse)
def get_score_audit_record(
    request_id: str,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> AuditDetailResponse:
    """Retrieve an immutable score audit trail entry by its unique request_id."""
    audit = (
        db.query(ScoreAudit)
        .filter(ScoreAudit.request_id == request_id)
        .first()
    )
    if audit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "AUDIT_RECORD_NOT_FOUND",
                "message": f"No score audit record found for request_id '{request_id}'.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    # If an X-API-Key header is provided, verify lender isolation
    if x_api_key and x_api_key.strip():
        key_hash = hash_api_key(x_api_key)
        caller_lender = (
            db.query(Lender).filter(Lender.api_key_hash == key_hash).first()
        )
        if caller_lender is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error_code": "INVALID_API_KEY",
                    "message": "Invalid X-API-Key.",
                    "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
                },
            )
        if (
            audit.queried_by_lender_id
            and audit.queried_by_lender_id != caller_lender.lender_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "LENDER_ISOLATION_VIOLATION",
                    "message": "Lender is not authorized to view another lender's audit trail.",
                    "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
                },
            )

    return AuditDetailResponse(
        request_id=audit.request_id or request_id,
        worker_uid=audit.worker_uid,
        consent_handle=audit.consent_handle,
        queried_by_lender_id=audit.queried_by_lender_id,
        gig_score=audit.gig_score,
        risk_tier=audit.risk_tier,
        score_band=audit.score_band,
        calibrated_probability=audit.calibrated_probability,
        reason_codes=audit.reason_codes or [],
        top_factors=audit.top_factors or [],
        authenticity_status=audit.authenticity_status,
        authenticity_flags=audit.authenticity_flags or [],
        needs_review=bool(audit.needs_review),
        model_version=audit.model_version,
        scoring_engine=audit.scoring_engine,
        fee_charged_inr=audit.fee_charged_inr,
        calculated_at=audit.calculated_at,
    )


@router.get("/api/demo/catalog")
def get_demo_catalog(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return predefined demo workers, demo lender credentials (dev/demo only), and recent consents."""
    consents = (
        db.query(ConsentRecord)
        .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
        .limit(20)
        .all()
    )
    audits = (
        db.query(ScoreAudit)
        .order_by(ScoreAudit.calculated_at.desc(), ScoreAudit.id.desc())
        .limit(20)
        .all()
    )
    return {
        "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
        "demo_workers": list(DEMO_WORKERS_CATALOG.values()),
        "demo_lenders": DEMO_LENDERS_CATALOG,
        "active_model_version": model_service.active_model_version,
        "recent_consents": [
            {
                "consent_handle": c.consent_handle,
                "worker_uid": c.worker_uid,
                "status": c.status,
                "purpose": c.purpose,
                "lender_id": c.lender_id,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in consents
        ],
        "recent_audits": [
            {
                "request_id": a.request_id,
                "worker_uid": a.worker_uid,
                "gig_score": a.gig_score,
                "risk_tier": a.risk_tier,
                "score_band": a.score_band,
                "authenticity_status": a.authenticity_status,
                "model_version": a.model_version,
                "queried_by_lender_id": a.queried_by_lender_id,
                "fee_charged_inr": a.fee_charged_inr,
                "calculated_at": a.calculated_at.isoformat() if a.calculated_at else None,
            }
            for a in audits
        ],
    }


@router.get("/api/workers/{worker_uid}/overview")
def get_worker_overview(
    worker_uid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return worker profile, active/historical consents, and consent-gated latest score.

    NEVER creates consents or scores.
    Only returns a valid latest_score if the worker currently has an APPROVED, unrevoked,
    unexpired consent and the score was computed under that active consent.
    """
    expire_and_deduplicate_consents(db, worker_uid)
    db.commit()

    worker = db.query(Worker).filter(Worker.worker_uid == worker_uid).first()
    demo_info = DEMO_WORKERS_CATALOG.get(worker_uid, {})

    consents = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.worker_uid == worker_uid)
        .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
        .limit(10)
        .all()
    )

    active_approved_consent = next(
        (c for c in consents if c.status == "APPROVED" and c.revoked_at is None),
        None,
    )
    active_pending_consent = next(
        (c for c in consents if c.status == "PENDING" and c.revoked_at is None),
        None,
    )

    if active_approved_consent is not None:
        consent_status = "APPROVED"
    elif active_pending_consent is not None:
        consent_status = "PENDING"
    elif consents and consents[0].status == "REVOKED":
        consent_status = "REVOKED"
    elif consents and consents[0].status == "EXPIRED":
        consent_status = "EXPIRED"
    else:
        consent_status = "NONE"

    # Only retrieve a valid score if there is currently an active APPROVED consent,
    # and the audit record was produced for that active consent (never a REJECTED_* audit or stale revoked consent).
    valid_latest_audit = None
    if active_approved_consent is not None:
        candidate_audits = (
            db.query(ScoreAudit)
            .filter(
                ScoreAudit.worker_uid == worker_uid,
                ScoreAudit.consent_handle == active_approved_consent.consent_handle,
            )
            .order_by(ScoreAudit.calculated_at.desc(), ScoreAudit.id.desc())
            .all()
        )
        for aud in candidate_audits:
            tier_str = str(aud.risk_tier or "")
            if tier_str.startswith("REJECTED_"):
                continue
            if aud.gig_score is not None or aud.authenticity_status == "NEEDS_REVIEW" or aud.needs_review:
                valid_latest_audit = aud
                break

    return {
        "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
        "consent_status": consent_status,
        "active_consent_handle": (
            active_approved_consent.consent_handle
            if active_approved_consent is not None
            else (
                active_pending_consent.consent_handle
                if active_pending_consent is not None
                else None
            )
        ),
        "worker": {
            "worker_uid": worker_uid,
            "name": (worker.name if worker else None)
            or demo_info.get("name", worker_uid),
            "phone": (worker.phone if worker else None)
            or demo_info.get("phone", "+91-9800000000"),
            "e_shram_id": (worker.e_shram_id if worker else None)
            or demo_info.get("e_shram_id", "ESHRAM-SYNTH-001"),
            "persona": (worker.persona if worker else None)
            or demo_info.get("persona", "stable_full_time"),
            "primary_city": (worker.primary_city if worker else None)
            or demo_info.get("primary_city", "Bengaluru"),
            "platforms": (worker.platforms if worker else None)
            or demo_info.get("platforms", ["Swiggy", "Zomato"]),
            "tenure_months": (worker.tenure_months if worker else None)
            or demo_info.get("tenure_months", 12),
        },
        "consents": [
            {
                "consent_handle": c.consent_handle,
                "status": c.status,
                "purpose": c.purpose,
                "lender_id": c.lender_id,
                "agg_provider": c.agg_provider,
                "requested_platforms": c.requested_platforms,
                "approved_at": c.approved_at.isoformat() if c.approved_at else None,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
                "revocation_reason": c.revocation_reason,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in consents
        ],
        "latest_score": (
            {
                "request_id": valid_latest_audit.request_id,
                "consent_handle": valid_latest_audit.consent_handle,
                "gig_score": valid_latest_audit.gig_score,
                "risk_tier": valid_latest_audit.risk_tier,
                "score_band": valid_latest_audit.score_band,
                "calibrated_probability": valid_latest_audit.calibrated_probability,
                "reason_codes": valid_latest_audit.reason_codes or [],
                "top_factors": valid_latest_audit.top_factors or [],
                "authenticity_status": valid_latest_audit.authenticity_status,
                "authenticity_flags": valid_latest_audit.authenticity_flags or [],
                "needs_review": bool(valid_latest_audit.needs_review),
                "model_version": valid_latest_audit.model_version,
                "scoring_engine": valid_latest_audit.scoring_engine,
                "calculated_at": (
                    valid_latest_audit.calculated_at.isoformat()
                    if valid_latest_audit.calculated_at
                    else None
                ),
            }
            if valid_latest_audit is not None
            else None
        ),
    }


@router.get("/api/model/transparency")
def get_model_transparency() -> Dict[str, Any]:
    """Return full model metrics, calibration curve, fairness diagnostics, and model card."""
    return model_service.get_transparency_metadata()

