"""Consent Management and Mock Account Aggregator Endpoints.

Implements:
- POST /consent/request
- POST /consent/approve
- POST /consent/revoke
- GET /mock-aa/fetch/{consent_id}

Prototype - synthetic data only. Not for real lending decisions.
"""
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT
from app.core.database import get_db
from app.models.db_models import ConsentRecord, Worker
from app.schemas.consent import (
    ConsentApproveRequest,
    ConsentRequestCreate,
    ConsentResponse,
    ConsentRevokeRequest,
    ConsentStatusEnum,
    MockAAFetchResponse,
    PlatformMonthlyEarning,
)
from app.services.mock_aa import DEMO_WORKERS_CATALOG, fetch_ephemeral_aa_earnings

router = APIRouter(tags=["Consent & Account Aggregator"])


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def expire_and_deduplicate_consents(
    db: Session,
    worker_uid: str,
    lender_id: str | None = None,
    purpose: str | None = None,
    agg_provider: str | None = None,
) -> None:
    """Expire past-due consents and ensure at most one active/pending consent per (worker, lender, purpose, AA).

    Never deletes historical records; superseded duplicate active rows are marked EXPIRED.
    """
    now = datetime.now(timezone.utc)
    active_rows = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.worker_uid == worker_uid,
            ConsentRecord.status.in_(
                [ConsentStatusEnum.PENDING.value, ConsentStatusEnum.APPROVED.value]
            ),
        )
        .order_by(ConsentRecord.id.desc())
        .all()
    )

    seen_keys: set[tuple[str, str, str, str]] = set()
    dirty = False

    for row in active_rows:
        exp = _ensure_utc(row.expires_at)
        if exp is not None and exp <= now:
            row.status = ConsentStatusEnum.EXPIRED.value
            dirty = True
            continue

        if row.revoked_at is not None:
            row.status = ConsentStatusEnum.REVOKED.value
            dirty = True
            continue

        combo_key = (
            row.worker_uid,
            str(row.lender_id or ""),
            str(row.purpose or "CREDIT_SCORING").upper(),
            str(row.agg_provider or "Setu_AA"),
        )
        if combo_key in seen_keys:
            row.status = ConsentStatusEnum.EXPIRED.value
            row.revocation_reason = (
                row.revocation_reason or "Superseded by newer consent record"
            )
            dirty = True
        else:
            seen_keys.add(combo_key)

    if dirty:
        db.flush()


@router.post(
    "/consent/request",
    response_model=ConsentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_consent_request(
    payload: ConsentRequestCreate,
    db: Session = Depends(get_db),
) -> ConsentResponse:
    """Create a new Account Aggregator consent request (status=PENDING) with duplicate protection."""
    worker = (
        db.query(Worker)
        .filter(Worker.worker_uid == payload.worker_uid)
        .first()
    )
    demo_meta = DEMO_WORKERS_CATALOG.get(payload.worker_uid, {})

    if worker is None:
        worker = Worker(
            worker_uid=payload.worker_uid,
            name=demo_meta.get("name") or payload.worker_name or f"Worker {payload.worker_uid}",
            phone=demo_meta.get("phone") or payload.phone,
            e_shram_id=demo_meta.get("e_shram_id") or payload.e_shram_id,
            persona=demo_meta.get("persona", "stable_full_time"),
            primary_city=demo_meta.get("primary_city", "Bengaluru"),
            platforms=demo_meta.get("platforms") or payload.requested_platforms,
            tenure_months=demo_meta.get("tenure_months", 12),
        )
        db.add(worker)
        db.flush()

    # Clean up expired or duplicate active consents for this worker
    expire_and_deduplicate_consents(db, payload.worker_uid)

    now = datetime.now(timezone.utc)

    # Idempotency / duplicate protection: if an unexpired PENDING consent already exists
    # for the same (worker_uid, lender_id, purpose, agg_provider), return it instead of creating duplicates.
    existing_pending = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.worker_uid == payload.worker_uid,
            ConsentRecord.lender_id == payload.lender_id,
            ConsentRecord.purpose == payload.purpose,
            ConsentRecord.agg_provider == payload.agg_provider,
            ConsentRecord.status == ConsentStatusEnum.PENDING.value,
            ConsentRecord.revoked_at.is_(None),
        )
        .order_by(ConsentRecord.id.desc())
        .first()
    )
    if existing_pending is not None:
        exp = _ensure_utc(existing_pending.expires_at)
        if exp is None or exp > now:
            db.commit()
            db.refresh(existing_pending)
            return ConsentResponse.model_validate(existing_pending)

    # Supersede any prior active APPROVED consent for the exact same (worker, lender, purpose, AA)
    # so there are never multiple active consents for the same combination.
    existing_approved = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.worker_uid == payload.worker_uid,
            ConsentRecord.lender_id == payload.lender_id,
            ConsentRecord.purpose == payload.purpose,
            ConsentRecord.agg_provider == payload.agg_provider,
            ConsentRecord.status == ConsentStatusEnum.APPROVED.value,
        )
        .all()
    )
    for old_rec in existing_approved:
        old_rec.status = ConsentStatusEnum.EXPIRED.value
        old_rec.revocation_reason = "Superseded by new consent request"

    expires_at = now + timedelta(hours=payload.expiry_hours)
    consent_handle = f"consent_{uuid.uuid4().hex[:16]}"

    record = ConsentRecord(
        worker_uid=payload.worker_uid,
        consent_handle=consent_handle,
        status=ConsentStatusEnum.PENDING.value,
        agg_provider=payload.agg_provider,
        purpose=payload.purpose,
        lender_id=payload.lender_id,
        requested_platforms=payload.requested_platforms,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return ConsentResponse.model_validate(record)


@router.post("/consent/approve", response_model=ConsentResponse)
def approve_consent(
    payload: ConsentApproveRequest,
    db: Session = Depends(get_db),
) -> ConsentResponse:
    """Approve a pending Account Aggregator consent handle."""
    record = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.consent_handle == payload.consent_handle)
        .first()
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "CONSENT_NOT_FOUND",
                "message": f"Consent handle '{payload.consent_handle}' not found.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    if record.worker_uid != payload.worker_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_WORKER_MISMATCH",
                "message": "Worker UID does not match the owner of this consent handle.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    if record.status == ConsentStatusEnum.REVOKED.value or record.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "CONSENT_ALREADY_REVOKED",
                "message": "A revoked consent cannot be re-approved. Create a new consent request.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    now = datetime.now(timezone.utc)
    exp = _ensure_utc(record.expires_at)
    if exp is not None and exp <= now:
        record.status = ConsentStatusEnum.EXPIRED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "CONSENT_EXPIRED",
                "message": "Consent has already expired.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    record.status = ConsentStatusEnum.APPROVED.value
    record.approved_at = now

    # Ensure no other active/pending consent exists for the same (worker, lender, purpose, AA)
    sibling_rows = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.worker_uid == record.worker_uid,
            ConsentRecord.lender_id == record.lender_id,
            ConsentRecord.purpose == record.purpose,
            ConsentRecord.agg_provider == record.agg_provider,
            ConsentRecord.id != record.id,
            ConsentRecord.status.in_(
                [ConsentStatusEnum.PENDING.value, ConsentStatusEnum.APPROVED.value]
            ),
        )
        .all()
    )
    for sib in sibling_rows:
        sib.status = ConsentStatusEnum.EXPIRED.value
        sib.revocation_reason = "Superseded by newly approved consent"

    db.commit()
    db.refresh(record)
    return ConsentResponse.model_validate(record)


@router.post("/consent/revoke", response_model=ConsentResponse)
def revoke_consent(
    payload: ConsentRevokeRequest,
    db: Session = Depends(get_db),
) -> ConsentResponse:
    """Revoke an Account Aggregator consent immediately."""
    record = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.consent_handle == payload.consent_handle)
        .first()
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "CONSENT_NOT_FOUND",
                "message": f"Consent handle '{payload.consent_handle}' not found.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    if record.worker_uid != payload.worker_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_WORKER_MISMATCH",
                "message": "Worker UID does not match the owner of this consent handle.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    now = datetime.now(timezone.utc)
    record.status = ConsentStatusEnum.REVOKED.value
    record.revoked_at = now
    record.revocation_reason = payload.reason or "Worker revoked consent"

    # Also revoke any other lingering active/pending consents for the same (worker, lender, purpose, AA)
    # so revocation immediately stops all authorization for that combination.
    sibling_active = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.worker_uid == record.worker_uid,
            ConsentRecord.lender_id == record.lender_id,
            ConsentRecord.purpose == record.purpose,
            ConsentRecord.agg_provider == record.agg_provider,
            ConsentRecord.id != record.id,
            ConsentRecord.status.in_(
                [ConsentStatusEnum.PENDING.value, ConsentStatusEnum.APPROVED.value]
            ),
        )
        .all()
    )
    for sib in sibling_active:
        sib.status = ConsentStatusEnum.REVOKED.value
        sib.revoked_at = now
        sib.revocation_reason = payload.reason or "Revoked with active consent"

    db.commit()
    db.refresh(record)
    return ConsentResponse.model_validate(record)


@router.get("/mock-aa/fetch/{consent_id}", response_model=MockAAFetchResponse)
def fetch_mock_aa_data(
    consent_id: str,
    db: Session = Depends(get_db),
) -> MockAAFetchResponse:
    """Retrieve deterministic mock AA bank-verified & platform earnings in memory."""
    record = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.consent_handle == consent_id)
        .first()
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "CONSENT_NOT_FOUND",
                "message": f"Consent '{consent_id}' not found.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    now = datetime.now(timezone.utc)
    if record.status == ConsentStatusEnum.REVOKED.value or record.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_REVOKED",
                "message": "Cannot fetch AA earnings: consent has been revoked by the worker.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    exp = _ensure_utc(record.expires_at)
    if (exp is not None and exp <= now) or record.status == ConsentStatusEnum.EXPIRED.value:
        record.status = ConsentStatusEnum.EXPIRED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_EXPIRED",
                "message": "Cannot fetch AA earnings: consent has expired.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    if record.status != ConsentStatusEnum.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONSENT_NOT_APPROVED",
                "message": f"Cannot fetch AA earnings: consent status is '{record.status}' (must be APPROVED).",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    worker = (
        db.query(Worker)
        .filter(Worker.worker_uid == record.worker_uid)
        .first()
    )
    declared_tenure = worker.tenure_months if worker else None
    aa_data = fetch_ephemeral_aa_earnings(
        worker_uid=record.worker_uid,
        declared_tenure_override=declared_tenure,
    )

    return MockAAFetchResponse(
        consent_handle=record.consent_handle,
        worker_uid=record.worker_uid,
        agg_provider=record.agg_provider,
        consent_status=ConsentStatusEnum.APPROVED,
        persona=aa_data["persona"],
        tenure_months=aa_data["tenure_months"],
        platforms_connected=aa_data["platforms_connected"],
        monthly_earnings=[
            PlatformMonthlyEarning(**item) for item in aa_data["monthly_earnings"]
        ],
        aggregated_summary=aa_data["aggregated_summary"],
        raw_data_persisted=False,
        fetched_at=now,
    )

