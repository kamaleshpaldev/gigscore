"""Database Seeding Script for GigScore Demo Workers, Lenders, and Initial Consents.

Idempotent: safe to run repeatedly against SQLite or PostgreSQL without deleting existing records.

Prototype - synthetic data only. Not for real lending decisions.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, init_db
from app.core.security import hash_api_key
from app.models.db_models import ConsentRecord, Lender, Worker
from app.routes.consent import expire_and_deduplicate_consents
from app.services.mock_aa import DEMO_LENDERS_CATALOG, DEMO_WORKERS_CATALOG


def seed_database(db: Optional[Session] = None) -> Dict[str, Any]:
    """Seed the 5 demonstration workers, 2 demonstration lenders, and initial sample consents."""
    own_session = False
    if db is None:
        init_db()
        db = SessionLocal()
        own_session = True

    try:
        workers_seeded = 0
        for w_uid, w_meta in DEMO_WORKERS_CATALOG.items():
            existing_w = db.query(Worker).filter(Worker.worker_uid == w_uid).first()
            if existing_w is None:
                worker = Worker(
                    worker_uid=w_uid,
                    name=w_meta["name"],
                    phone=w_meta["phone"],
                    e_shram_id=w_meta["e_shram_id"],
                    persona=w_meta["persona"],
                    primary_city=w_meta["primary_city"],
                    platforms=w_meta["platforms"],
                    tenure_months=w_meta["tenure_months"],
                )
                db.add(worker)
                workers_seeded += 1
            else:
                existing_w.persona = existing_w.persona or w_meta["persona"]
                existing_w.primary_city = existing_w.primary_city or w_meta["primary_city"]
                existing_w.platforms = existing_w.platforms or w_meta["platforms"]
                existing_w.tenure_months = existing_w.tenure_months or w_meta["tenure_months"]

        lenders_seeded = 0
        for l_meta in DEMO_LENDERS_CATALOG:
            l_id = l_meta["lender_id"]
            key_hash = hash_api_key(l_meta["demo_api_key"])
            existing_l = db.query(Lender).filter(Lender.lender_id == l_id).first()
            if existing_l is None:
                lender = Lender(
                    lender_id=l_id,
                    name=l_meta["name"],
                    api_key_hash=key_hash,
                    api_key_prefix=l_meta["api_key_prefix"],
                    is_active=True,
                    rate_limit_per_minute=l_meta["rate_limit_per_minute"],
                    fee_per_check_inr=l_meta["fee_per_check_inr"],
                )
                db.add(lender)
                lenders_seeded += 1
            else:
                existing_l.api_key_hash = key_hash
                existing_l.is_active = True

        db.flush()

        # Create initial sample approved consents ONLY if a demo worker has no consent history yet,
        # and normalize any duplicate active consents without deleting history or restoring revoked consents.
        now = datetime.now(timezone.utc)
        consents_seeded = 0
        primary_lender_id = DEMO_LENDERS_CATALOG[0]["lender_id"]

        for w_uid, w_meta in DEMO_WORKERS_CATALOG.items():
            expire_and_deduplicate_consents(db, w_uid)
            existing_count = (
                db.query(ConsentRecord)
                .filter(ConsentRecord.worker_uid == w_uid)
                .count()
            )
            if existing_count == 0:
                sample_handle = f"consent_demo_{w_uid.lower()}"
                consent = ConsentRecord(
                    worker_uid=w_uid,
                    consent_handle=sample_handle,
                    status="APPROVED",
                    agg_provider="Setu_AA",
                    purpose="CREDIT_SCORING",
                    lender_id=primary_lender_id,
                    requested_platforms=w_meta["platforms"],
                    approved_at=now,
                    expires_at=now + timedelta(hours=72),
                )
                db.add(consent)
                consents_seeded += 1

        db.commit()
        return {
            "workers_seeded": workers_seeded,
            "lenders_seeded": lenders_seeded,
            "consents_seeded": consents_seeded,
            "demo_workers": list(DEMO_WORKERS_CATALOG.keys()),
            "demo_lenders": [l["lender_id"] for l in DEMO_LENDERS_CATALOG],
        }
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    summary = seed_database()
    print("Seeded GigScore Demo Environment:", summary)

