"""Phase 1 Foundation Tests: Configuration, SQLite FK Enforcement, Non-Destructive Schema Sync, CRUD (SQLite & PostgreSQL), and Pydantic Schemas."""
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from pydantic import ValidationError

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT, Settings, settings
from app.core.database import create_db_engine, init_db
from app.models import (
    BillingRecord,
    ConsentRecord,
    Lender,
    ScoreAudit,
    Worker,
)
from app.schemas import (
    AuditDetailResponse,
    AuthenticityReport,
    AuthenticityStatusEnum,
    ConsentPurposeEnum,
    ConsentRequestCreate,
    ConsentResponse,
    ConsentStatusEnum,
    ErrorResponse,
    ExplainabilityFactor,
    HealthResponse,
    LenderUsageResponse,
    MockAAFetchResponse,
    PlatformMonthlyEarning,
    ScoreRequest,
    ScoreResponse,
    ScoringEngineEnum,
)

EXPECTED_DISCLAIMER = "Prototype - synthetic data only. Not for real lending decisions."


def test_settings_defaults_and_disclaimer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default SQLite URL when env is unset and mandatory disclaimer."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    isolated_settings = Settings(_env_file=None)
    assert isolated_settings.DATABASE_URL == "sqlite:///./gigscore.db"
    assert isolated_settings.SCORE_CHECK_FEE_INR == 30.0
    assert isolated_settings.SCORE_MIN == 300
    assert isolated_settings.SCORE_MAX == 900
    assert isolated_settings.PROTOTYPE_DISCLAIMER == EXPECTED_DISCLAIMER
    assert PROTOTYPE_DISCLAIMER_TEXT == EXPECTED_DISCLAIMER


def test_sqlite_foreign_key_enforcement_and_cascade() -> None:
    """Verify PRAGMA foreign_keys=ON is enforced on SQLite and cascades deletes."""
    sqlite_engine = create_db_engine("sqlite:///:memory:")
    init_db(bind_engine=sqlite_engine)
    TestSession = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)

    with TestSession() as session:
        fk_pragma = session.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk_pragma == 1

        # Inserting a ConsentRecord for a non-existent worker must fail with IntegrityError
        orphan_consent = ConsentRecord(
            worker_uid="NON_EXISTENT_WORKER",
            consent_handle="CH_ORPHAN_001",
            status="PENDING",
        )
        session.add(orphan_consent)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Create valid Worker, Lender, ConsentRecord, ScoreAudit, BillingRecord
        worker = Worker(
            worker_uid="W_SQLITE_001",
            name="Aarav Kumar",
            phone="+919876543210",
            e_shram_id="ESHRAM-1001",
            persona="delivery_multi_platform",
            primary_city="Bengaluru",
            platforms=["Swiggy", "Zomato"],
            tenure_months=18,
        )
        lender = Lender(
            lender_id="LENDER_NBFC_01",
            name="Demo MicroFinance NBFC",
            api_key_hash="sha256_hashed_demo_key_001",
            api_key_prefix="gsk_live",
            fee_per_check_inr=30.0,
        )
        session.add_all([worker, lender])
        session.commit()

        now = datetime.now(timezone.utc)
        consent = ConsentRecord(
            worker_uid="W_SQLITE_001",
            consent_handle="CH_SQLITE_001",
            status="APPROVED",
            agg_provider="Setu_AA",
            purpose="CREDIT_SCORING",
            lender_id="LENDER_NBFC_01",
            requested_platforms=["Swiggy", "Zomato"],
            approved_at=now,
            expires_at=now + timedelta(hours=24),
        )
        audit = ScoreAudit(
            worker_uid="W_SQLITE_001",
            request_id="REQ_SQLITE_001",
            consent_handle="CH_SQLITE_001",
            gig_score=745,
            risk_tier="LOW_RISK",
            score_band="650-749 (Good)",
            calibrated_probability=0.84,
            reason_codes=["STEADY_EARNINGS", "MULTI_PLATFORM_DIVERSITY"],
            top_factors=[
                {
                    "feature_name": "tenure_months",
                    "shap_impact": 0.18,
                    "direction": "POSITIVE",
                }
            ],
            authenticity_status="VERIFIED",
            authenticity_flags=[],
            needs_review=False,
            model_version="xgboost-calibrated-v1.0",
            scoring_engine="xgboost",
            queried_by_lender_id="LENDER_NBFC_01",
            fee_charged_inr=30.0,
        )
        billing = BillingRecord(
            billing_uid="BILL_SQLITE_001",
            lender_id="LENDER_NBFC_01",
            request_id="REQ_SQLITE_001",
            worker_uid="W_SQLITE_001",
            consent_handle="CH_SQLITE_001",
            fee_inr=30.0,
            currency="INR",
            status="BILLED",
        )
        session.add_all([consent, audit, billing])
        session.commit()

        assert session.query(ConsentRecord).count() == 1
        assert session.query(ScoreAudit).count() == 1
        assert session.query(BillingRecord).count() == 1

        # Deleting the worker should cascade delete its consent, audit, and billing records
        session.delete(worker)
        session.commit()

        assert session.query(ConsentRecord).count() == 0
        assert session.query(ScoreAudit).count() == 0
        assert session.query(BillingRecord).count() == 0


def test_non_destructive_schema_sync_preserves_existing_data() -> None:
    """Verify init_db() adds nullable columns to pre-existing legacy tables without losing data."""
    legacy_engine = create_engine("sqlite:///:memory:")
    with legacy_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE workers ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "worker_uid VARCHAR(64) NOT NULL UNIQUE, "
                "name VARCHAR(255) NOT NULL, "
                "phone VARCHAR(20), "
                "e_shram_id VARCHAR(50), "
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO workers (worker_uid, name, phone) "
                "VALUES ('LEGACY_W1', 'Legacy Worker', '9999999999')"
            )
        )

    # Run init_db() on the legacy database
    init_db(bind_engine=legacy_engine)

    inspector = inspect(legacy_engine)
    worker_cols = {c["name"] for c in inspector.get_columns("workers")}
    assert {"persona", "primary_city", "platforms", "tenure_months"}.issubset(
        worker_cols
    )
    assert "lenders" in inspector.get_table_names()
    assert "billing_records" in inspector.get_table_names()

    # Verify the existing row is completely intact
    with legacy_engine.connect() as conn:
        row = conn.execute(
            text("SELECT worker_uid, name, phone, persona FROM workers WHERE worker_uid='LEGACY_W1'")
        ).fetchone()
        assert row is not None
        assert row[0] == "LEGACY_W1"
        assert row[1] == "Legacy Worker"
        assert row[2] == "9999999999"
        assert row[3] is None


def test_postgresql_schema_sync_and_crud_if_configured() -> None:
    """Verify non-destructive schema sync and CRUD on the configured PostgreSQL database."""
    init_db()
    from app.core.database import engine, SessionLocal

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "workers",
        "consent_records",
        "lenders",
        "score_audits",
        "billing_records",
    }.issubset(tables)

    consent_cols = {c["name"] for c in inspector.get_columns("consent_records")}
    assert {
        "purpose",
        "lender_id",
        "requested_platforms",
        "expires_at",
        "revoked_at",
        "revocation_reason",
    }.issubset(consent_cols)

    audit_cols = {c["name"] for c in inspector.get_columns("score_audits")}
    assert {
        "request_id",
        "consent_handle",
        "score_band",
        "calibrated_probability",
        "top_factors",
        "authenticity_status",
        "authenticity_flags",
        "needs_review",
        "model_version",
        "scoring_engine",
        "fee_charged_inr",
    }.issubset(audit_cols)

    # Perform CRUD and clean up our synthetic test records
    test_worker_uid = "TEST_PG_PHASE1_WORKER"
    test_lender_id = "TEST_PG_PHASE1_LENDER"
    with SessionLocal() as session:
        try:
            worker = Worker(
                worker_uid=test_worker_uid,
                name="Synthetic Postgres Test Worker",
                persona="rideshare_veteran",
                platforms=["Uber", "Ola"],
                tenure_months=24,
            )
            lender = Lender(
                lender_id=test_lender_id,
                name="Synthetic Postgres Test Lender",
                api_key_hash="pg_test_hash_phase1_999",
                fee_per_check_inr=30.0,
            )
            session.add_all([worker, lender])
            session.flush()

            consent = ConsentRecord(
                worker_uid=test_worker_uid,
                consent_handle="CH_PG_PHASE1_TEST",
                status="APPROVED",
                purpose="CREDIT_SCORING",
                lender_id=test_lender_id,
                requested_platforms=["Uber", "Ola"],
            )
            audit = ScoreAudit(
                worker_uid=test_worker_uid,
                request_id="REQ_PG_PHASE1_TEST",
                consent_handle="CH_PG_PHASE1_TEST",
                gig_score=780,
                risk_tier="LOW_RISK",
                score_band="750-900 (Excellent)",
                calibrated_probability=0.91,
                reason_codes=["HIGH_TENURE"],
                authenticity_status="VERIFIED",
                model_version="xgboost-calibrated-v1.0",
                scoring_engine="xgboost",
                queried_by_lender_id=test_lender_id,
                fee_charged_inr=30.0,
            )
            billing = BillingRecord(
                billing_uid="BILL_PG_PHASE1_TEST",
                lender_id=test_lender_id,
                request_id="REQ_PG_PHASE1_TEST",
                worker_uid=test_worker_uid,
                consent_handle="CH_PG_PHASE1_TEST",
                fee_inr=30.0,
            )
            session.add_all([consent, audit, billing])
            session.commit()

            fetched_audit = (
                session.query(ScoreAudit)
                .filter_by(request_id="REQ_PG_PHASE1_TEST")
                .one()
            )
            assert fetched_audit.gig_score == 780
            assert fetched_audit.model_version == "xgboost-calibrated-v1.0"
        finally:
            # Clean up test records so existing DB state remains clean
            session.query(BillingRecord).filter_by(
                billing_uid="BILL_PG_PHASE1_TEST"
            ).delete()
            session.query(ScoreAudit).filter_by(
                request_id="REQ_PG_PHASE1_TEST"
            ).delete()
            session.query(ConsentRecord).filter_by(
                consent_handle="CH_PG_PHASE1_TEST"
            ).delete()
            session.query(Worker).filter_by(worker_uid=test_worker_uid).delete()
            session.query(Lender).filter_by(lender_id=test_lender_id).delete()
            session.commit()


def test_pydantic_schemas_validation_and_disclaimer() -> None:
    """Verify Pydantic schemas enforce constraints and include the prototype disclaimer."""
    now = datetime.now(timezone.utc)

    # 1. Invalid purpose should raise ValidationError
    with pytest.raises(ValidationError):
        ConsentRequestCreate(
            worker_uid="W001",
            purpose="UNAPPROVED_MARKETING_SPAM",
        )

    # 2. Valid consent request & response
    req = ConsentRequestCreate(
        worker_uid="W001",
        purpose=ConsentPurposeEnum.CREDIT_SCORING.value,
    )
    assert req.purpose == "CREDIT_SCORING"

    consent_resp = ConsentResponse(
        consent_handle="CH001",
        worker_uid="W001",
        status=ConsentStatusEnum.APPROVED,
        agg_provider="Setu_AA",
        created_at=now,
    )
    assert consent_resp.disclaimer == EXPECTED_DISCLAIMER

    # 3. ScoreResponse enforces 300-900 bounds and includes disclaimer
    with pytest.raises(ValidationError):
        ScoreResponse(
            request_id="REQ1",
            worker_uid="W001",
            consent_handle="CH001",
            gig_score=250,  # Below 300 minimum
            risk_tier="VERY_HIGH_RISK",
            score_band="300-549 (Poor)",
            calibrated_probability=0.1,
            reason_codes=[],
            top_factors=[],
            authenticity=AuthenticityReport(status=AuthenticityStatusEnum.VERIFIED),
            authenticity_status=AuthenticityStatusEnum.VERIFIED,
            needs_review=False,
            model_version="xgboost-calibrated-v1.0",
            scoring_engine=ScoringEngineEnum.XGBOOST,
            calculated_at=now,
        )

    valid_score = ScoreResponse(
        request_id="REQ1",
        worker_uid="W001",
        consent_handle="CH001",
        gig_score=760,
        risk_tier="LOW_RISK",
        score_band="750-900 (Excellent)",
        calibrated_probability=0.88,
        reason_codes=["CONSISTENT_MONTHLY_EARNINGS"],
        top_factors=[
            ExplainabilityFactor(
                feature_name="avg_monthly_earnings",
                feature_value=32000.0,
                shap_impact=0.25,
                direction="POSITIVE",
                reason_code="CONSISTENT_MONTHLY_EARNINGS",
                plain_english="Consistent monthly bank-verified earnings above ₹30,000",
            )
        ],
        authenticity=AuthenticityReport(status=AuthenticityStatusEnum.VERIFIED),
        authenticity_status=AuthenticityStatusEnum.VERIFIED,
        needs_review=False,
        model_version="xgboost-calibrated-v1.0",
        scoring_engine=ScoringEngineEnum.XGBOOST,
        calculated_at=now,
    )
    assert valid_score.disclaimer == EXPECTED_DISCLAIMER
    assert valid_score.fee_charged_inr == 30.0

    # 4. Verify disclaimer on HealthResponse, MockAAFetchResponse, LenderUsageResponse, AuditDetailResponse, ErrorResponse
    health = HealthResponse(
        app_name="GigScore Backend",
        environment="development",
        database_connected=True,
        primary_model_version="xgboost-calibrated-v1.0",
        fallback_model_version="rule-scorecard-v1.0",
        timestamp=now,
    )
    aa_resp = MockAAFetchResponse(
        consent_handle="CH001",
        worker_uid="W001",
        agg_provider="Setu_AA",
        consent_status=ConsentStatusEnum.APPROVED,
        tenure_months=12,
        platforms_connected=["Swiggy"],
        monthly_earnings=[
            PlatformMonthlyEarning(
                month="2026-10",
                platform="Swiggy",
                claimed_earnings_inr=25000.0,
                bank_verified_credit_inr=25000.0,
                trips_or_orders_completed=420,
                active_days=26,
                platform_rating=4.8,
            )
        ],
        aggregated_summary={"total_verified_inr": 25000.0},
        fetched_at=now,
    )
    usage_resp = LenderUsageResponse(
        lender_id="L001",
        lender_name="Test Lender",
        is_active=True,
        rate_limit_per_minute=60,
        fee_per_check_inr=30.0,
        total_checks=1,
        total_billed_inr=30.0,
    )
    audit_resp = AuditDetailResponse(
        request_id="REQ1",
        worker_uid="W001",
        gig_score=760,
        risk_tier="LOW_RISK",
        calculated_at=now,
    )
    err_resp = ErrorResponse(
        error_code="CONSENT_REQUIRED",
        message="Valid approved consent is required before scoring.",
    )
    score_req = ScoreRequest(worker_uid="W001", consent_handle="CH001")
    assert score_req.worker_uid == "W001"
    for schema_obj in (health, aa_resp, usage_resp, audit_resp, err_resp):
        assert schema_obj.disclaimer == EXPECTED_DISCLAIMER

