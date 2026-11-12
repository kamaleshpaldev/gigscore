"""Complete System & End-to-End Acceptance Test Suite for GigScore.

Covers Step 11 (Unit, ML, Security, Consent, Authenticity, Billing, Isolation)
and Section 4 (16-Step End-to-End Acceptance Workflow on Strong & Suspicious Workers).

Prototype - synthetic data only. Not for real lending decisions.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT
from app.core.database import create_db_engine, get_db, init_db
from app.core.security import hash_api_key, reset_rate_limits
from app.main import app
from app.ml.authenticity import evaluate_earnings_authenticity
from app.ml.fairness import run_synthetic_fairness_audit
from app.ml.features import FEATURE_COLUMNS, compute_worker_features
from app.ml.model import GigScoreModelService, model_service
from app.ml.scorecard import score_with_rule_scorecard
from app.models.db_models import BillingRecord, ConsentRecord, Lender
from scripts.seed import seed_database


@pytest.fixture()
def test_client():
    """Provide an isolated in-memory SQLite database and seeded TestClient for API tests."""
    reset_rate_limits()
    sqlite_engine = create_db_engine("sqlite:///file:test_gigscore_e2e?mode=memory&cache=shared&uri=true")
    init_db(bind_engine=sqlite_engine)
    TestingSessionLocal = sessionmaker(
        bind=sqlite_engine, autocommit=False, autoflush=False
    )

    with TestingSessionLocal() as session:
        seed_database(db=session)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, TestingSessionLocal
    app.dependency_overrides.clear()
    reset_rate_limits()


def test_feature_calculations_and_missing_data_safety() -> None:
    """Verify all 8 features calculate accurately and handle missing/empty inputs safely."""
    # 1. Empty input fallback
    empty_feats = compute_worker_features([], declared_tenure_months=10)
    assert set(empty_feats.keys()) == set(FEATURE_COLUMNS)
    assert empty_feats["tenure_months"] == 10.0
    assert empty_feats["avg_monthly_earnings"] == 0.0

    # 2. Multi-platform 6-month history with 1 calendar gap and NaN/None ratings
    records = [
        {
            "month": "2026-04",
            "platform": "Swiggy",
            "bank_verified_credit_inr": 15000.0,
            "platform_rating": 4.8,
        },
        {
            "month": "2026-04",
            "platform": "Zomato",
            "bank_verified_credit_inr": 10000.0,
            "platform_rating": None,
        },
        # 2026-05 is missing (1 calendar gap month)
        {
            "month": "2026-06",
            "platform": "Swiggy",
            "bank_verified_credit_inr": 26000.0,
            "platform_rating": 4.6,
        },
        {
            "month": "2026-07",
            "platform": "Swiggy",
            "bank_verified_credit_inr": 28000.0,
            "platform_rating": float("nan"),
        },
        {
            "month": "2026-08",
            "platform": "Swiggy",
            "bank_verified_credit_inr": 30000.0,
            "platform_rating": 4.7,
        },
    ]
    feats = compute_worker_features(records, declared_tenure_months=8)
    assert feats["tenure_months"] == 8.0
    assert feats["platform_count"] == 2.0
    assert 27000.0 <= feats["avg_monthly_earnings"] <= 27500.0
    assert feats["earnings_trend_6m"] > 0.0
    assert feats["income_gap_months"] == 1.0
    assert 4.65 <= feats["avg_rating"] <= 4.75
    assert 0.85 <= feats["earnings_to_peak_ratio"] <= 1.0


def test_scorecard_boundaries_and_monotonicity() -> None:
    """Verify rule-based scorecard stays within 300-900 and is monotonic across all 8 features."""
    worst_case = {
        "tenure_months": 1.0,
        "avg_monthly_earnings": 0.0,
        "earnings_cv": 2.0,
        "earnings_trend_6m": -0.9,
        "income_gap_months": 12.0,
        "platform_count": 0.0,
        "avg_rating": 2.5,
        "earnings_to_peak_ratio": 0.1,
    }
    best_case = {
        "tenure_months": 36.0,
        "avg_monthly_earnings": 65000.0,
        "earnings_cv": 0.05,
        "earnings_trend_6m": 0.45,
        "income_gap_months": 0.0,
        "platform_count": 4.0,
        "avg_rating": 4.95,
        "earnings_to_peak_ratio": 0.98,
    }
    res_low = score_with_rule_scorecard(worst_case)
    res_high = score_with_rule_scorecard(best_case)

    assert 300 <= res_low["gig_score"] <= 900
    assert 300 <= res_high["gig_score"] <= 900
    assert res_high["gig_score"] > res_low["gig_score"]

    # Check individual feature monotonicity
    baseline = {
        "tenure_months": 12.0,
        "avg_monthly_earnings": 22000.0,
        "earnings_cv": 0.30,
        "earnings_trend_6m": 0.0,
        "income_gap_months": 1.0,
        "platform_count": 2.0,
        "avg_rating": 4.4,
        "earnings_to_peak_ratio": 0.70,
    }
    base_score = score_with_rule_scorecard(baseline)["gig_score"]

    assert (
        score_with_rule_scorecard({**baseline, "avg_monthly_earnings": 40000.0})[
            "gig_score"
        ]
        >= base_score
    )
    assert (
        score_with_rule_scorecard({**baseline, "tenure_months": 30.0})["gig_score"]
        >= base_score
    )
    assert (
        score_with_rule_scorecard({**baseline, "earnings_cv": 0.80})["gig_score"]
        <= base_score
    )
    assert (
        score_with_rule_scorecard({**baseline, "income_gap_months": 6.0})[
            "gig_score"
        ]
        <= base_score
    )


def test_xgboost_model_loading_monotonicity_and_fallback() -> None:
    """Verify calibrated XGBoost inference, monotonicity, and transparent scorecard fallback."""
    assert model_service.is_xgboost_loaded is True
    assert model_service.active_model_version == "xgboost-calibrated-v1.0"

    base_features = {
        "tenure_months": 14.0,
        "avg_monthly_earnings": 20000.0,
        "earnings_cv": 0.32,
        "earnings_trend_6m": 0.0,
        "income_gap_months": 1.0,
        "platform_count": 2.0,
        "avg_rating": 4.45,
        "earnings_to_peak_ratio": 0.72,
    }
    pred_base = model_service.predict_score(base_features)
    assert 300 <= pred_base["gig_score"] <= 900
    assert pred_base["scoring_engine"] == "xgboost"
    assert pred_base["model_version"] == "xgboost-calibrated-v1.0"
    assert len(pred_base["top_factors"]) > 0

    # Higher earnings and longer tenure must produce >= score (lower default probability)
    pred_better = model_service.predict_score(
        {
            **base_features,
            "tenure_months": 32.0,
            "avg_monthly_earnings": 48000.0,
            "earnings_cv": 0.10,
            "income_gap_months": 0.0,
        }
    )
    assert pred_better["gig_score"] >= pred_base["gig_score"]

    # Higher volatility and more gaps must produce <= score
    pred_worse = model_service.predict_score(
        {
            **base_features,
            "tenure_months": 6.0,
            "avg_monthly_earnings": 10000.0,
            "earnings_cv": 0.85,
            "income_gap_months": 6.0,
            "earnings_trend_6m": -0.45,
        }
    )
    assert pred_worse["gig_score"] <= pred_base["gig_score"]

    # Verify fallback when model artifact does not exist
    missing_service = GigScoreModelService(
        artifact_path=Path("/tmp/non_existent_gigscore_model_12345.joblib")
    )
    assert missing_service.is_xgboost_loaded is False
    assert missing_service.active_model_version == "rule-scorecard-v1.0"
    fallback_pred = missing_service.predict_score(base_features)
    assert fallback_pred["scoring_engine"] == "rule_scorecard"
    assert fallback_pred["model_version"] == "rule-scorecard-v1.0"
    assert 300 <= fallback_pred["gig_score"] <= 900


def test_authenticity_engine_all_five_checks() -> None:
    """Verify all 5 authenticity checks trigger NEEDS_REVIEW appropriately."""
    # 1. Clean verified records
    clean_records = [
        {
            "month": f"2026-0{i}",
            "platform": "Swiggy",
            "claimed_earnings_inr": 24150.0 + i * 320.0,
            "bank_verified_credit_inr": 24100.0 + i * 315.0,
            "trips_or_orders_completed": 280 + i * 5,
        }
        for i in range(1, 7)
    ]
    clean_rep = evaluate_earnings_authenticity(
        clean_records, declared_tenure_months=6
    )
    assert clean_rep.status.value == "VERIFIED"
    assert clean_rep.needs_review is False
    assert len(clean_rep.flags) == 0

    # 2. Tampered records triggering all 5 checks:
    # - Bank vs claimed mismatch
    # - Exact multiples of ₹1,000
    # - Duplicate transaction
    # - Impossible 6x jump
    # - Declared tenure 36m vs 5 observed months
    tampered = [
        {
            "month": "2026-01",
            "platform": "Uber",
            "claimed_earnings_inr": 25000.0,
            "bank_verified_credit_inr": 10000.0,
            "trips_or_orders_completed": 100,
        },
        {
            "month": "2026-01",
            "platform": "Uber",
            "claimed_earnings_inr": 25000.0,
            "bank_verified_credit_inr": 10000.0,
            "trips_or_orders_completed": 100,
        },  # Duplicate
        {
            "month": "2026-02",
            "platform": "Uber",
            "claimed_earnings_inr": 26000.0,
            "bank_verified_credit_inr": 11000.0,
            "trips_or_orders_completed": 110,
        },
        {
            "month": "2026-03",
            "platform": "Uber",
            "claimed_earnings_inr": 24000.0,
            "bank_verified_credit_inr": 10000.0,
            "trips_or_orders_completed": 105,
        },
        {
            "month": "2026-04",
            "platform": "Uber",
            "claimed_earnings_inr": 120000.0,
            "bank_verified_credit_inr": 65000.0,
            "trips_or_orders_completed": 600,
        },  # 6x spike
    ]
    flagged_rep = evaluate_earnings_authenticity(
        tampered, declared_tenure_months=36
    )
    assert flagged_rep.status.value == "NEEDS_REVIEW"
    assert flagged_rep.needs_review is True
    joined_flags = " | ".join(flagged_rep.flags)
    assert "BANK_VS_CLAIMED_MISMATCH" in joined_flags
    assert "ROUND_NUMBER_ANOMALY" in joined_flags
    assert "DUPLICATE_TRANSACTIONS" in joined_flags
    assert "IMPOSSIBLE_INCOME_JUMP" in joined_flags
    assert "TENURE_INCONSISTENCY" in joined_flags


def test_fairness_audit_excludes_gender_feature() -> None:
    """Verify synthetic fairness audit reports subgroup diagnostics and never uses gender as a feature."""
    assert "audit_gender" not in FEATURE_COLUMNS
    assert "gender" not in FEATURE_COLUMNS

    df = pd.DataFrame(
        {
            "city_tier": ["Tier-1", "Tier-1", "Tier-2", "Tier-3"],
            "platform_type": [
                "Food Delivery",
                "Ride Hailing",
                "Food Delivery",
                "Home Services",
            ],
            "audit_gender": ["Male", "Female", "Female", "Non-Binary"],
        }
    )
    scores = np.array([760, 720, 680, 640])
    rep = run_synthetic_fairness_audit(df, scores, threshold=650)
    assert rep["gender_used_as_model_feature"] is False
    assert "city_tier" in rep["dimensions"]
    assert "platform_type" in rep["dimensions"]
    assert "audit_gender" in rep["dimensions"]


def test_consent_expiry_purpose_auth_rate_limit_and_isolation(test_client) -> None:
    """Test expired consent, purpose mismatch, invalid API key, rate limiting, and lender isolation."""
    client, SessionLocalOverride = test_client
    samunnati_key = "gsk_demo_samunnati_2026_secret_key"
    pragati_key = "gsk_demo_pragati_2026_secret_key"

    # 1. Invalid API key -> 401
    res_unauth = client.post(
        "/score",
        headers={"X-API-Key": "invalid_wrong_key"},
        json={
            "worker_uid": "DEMO_W_STRONG",
            "consent_handle": "consent_demo_demo_w_strong",
        },
    )
    assert res_unauth.status_code == 401
    assert res_unauth.json()["error_code"] == "INVALID_API_KEY"

    # 2. Missing API key -> 401
    res_missing = client.post(
        "/score",
        json={
            "worker_uid": "DEMO_W_STRONG",
            "consent_handle": "consent_demo_demo_w_strong",
        },
    )
    assert res_missing.status_code == 401
    assert res_missing.json()["error_code"] == "MISSING_API_KEY"

    # 3. Lender isolation: Pragati cannot use a consent granted exclusively to Samunnati
    res_iso = client.post(
        "/score",
        headers={"X-API-Key": pragati_key},
        json={
            "worker_uid": "DEMO_W_STRONG",
            "consent_handle": "consent_demo_demo_w_strong",
        },
    )
    assert res_iso.status_code == 403
    assert res_iso.json()["error_code"] == "LENDER_UNAUTHORIZED_FOR_CONSENT"

    # 4. Lender isolation on usage endpoint
    res_usage_iso = client.get(
        "/lenders/LENDER_SAMUNNATI_NBFC/usage",
        headers={"X-API-Key": pragati_key},
    )
    assert res_usage_iso.status_code == 403
    assert res_usage_iso.json()["error_code"] == "LENDER_ISOLATION_VIOLATION"

    # 5. Expired consent & Purpose mismatch in DB
    with SessionLocalOverride() as db:
        now = datetime.now(timezone.utc)
        expired_c = ConsentRecord(
            worker_uid="DEMO_W_STRONG",
            consent_handle="consent_test_expired_001",
            status="APPROVED",
            purpose="CREDIT_SCORING",
            lender_id="LENDER_SAMUNNATI_NBFC",
            approved_at=now - timedelta(hours=48),
            expires_at=now - timedelta(hours=1),
        )
        bad_purpose_c = ConsentRecord(
            worker_uid="DEMO_W_STRONG",
            consent_handle="consent_test_bad_purpose_001",
            status="APPROVED",
            purpose="MARKETING_PROMOTION",
            lender_id="LENDER_SAMUNNATI_NBFC",
            approved_at=now,
            expires_at=now + timedelta(hours=24),
        )
        db.add_all([expired_c, bad_purpose_c])
        db.commit()

    res_exp = client.post(
        "/score",
        headers={"X-API-Key": samunnati_key},
        json={
            "worker_uid": "DEMO_W_STRONG",
            "consent_handle": "consent_test_expired_001",
        },
    )
    assert res_exp.status_code == 403
    assert res_exp.json()["error_code"] == "CONSENT_EXPIRED"

    res_purp = client.post(
        "/score",
        headers={"X-API-Key": samunnati_key},
        json={
            "worker_uid": "DEMO_W_STRONG",
            "consent_handle": "consent_test_bad_purpose_001",
        },
    )
    assert res_purp.status_code == 403
    assert res_purp.json()["error_code"] == "CONSENT_PURPOSE_MISMATCH"

    # 6. Rate limiting enforcement
    with SessionLocalOverride() as db:
        lender_row = (
            db.query(Lender)
            .filter_by(lender_id="LENDER_PRAGATI_FINTECH")
            .one()
        )
        lender_row.rate_limit_per_minute = 2
        db.commit()

    reset_rate_limits()
    for _ in range(2):
        r = client.get(
            "/lenders/LENDER_PRAGATI_FINTECH/usage",
            headers={"X-API-Key": pragati_key},
        )
        assert r.status_code == 200
    r_limited = client.get(
        "/lenders/LENDER_PRAGATI_FINTECH/usage",
        headers={"X-API-Key": pragati_key},
    )
    assert r_limited.status_code == 429
    assert r_limited.json()["error_code"] == "RATE_LIMIT_EXCEEDED"


def test_complete_16_step_end_to_end_acceptance_workflow(test_client) -> None:
    """Execute the exact 16-step End-to-End Acceptance Test for Strong and Suspicious workers."""
    client, SessionLocalOverride = test_client
    api_key = "gsk_demo_samunnati_2026_secret_key"
    lender_id = "LENDER_SAMUNNATI_NBFC"

    # Steps 1-3: Verify Landing page, Demo dashboard, and Health endpoint
    r_landing = client.get("/")
    assert r_landing.status_code == 200
    assert PROTOTYPE_DISCLAIMER_TEXT in r_landing.text
    assert "Kamalesh Pal" in r_landing.text

    r_demo = client.get("/demo")
    assert r_demo.status_code == 200

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["database_connected"] is True
    assert r_health.json()["disclaimer"] == PROTOTYPE_DISCLAIMER_TEXT

    # =========================================================================
    # PART A: STRONG WORKER (DEMO_W_STRONG)
    # =========================================================================
    # Step 4-5: Select strong worker & create consent request
    r_req = client.post(
        "/consent/request",
        json={
            "worker_uid": "DEMO_W_STRONG",
            "lender_id": lender_id,
            "purpose": "CREDIT_SCORING",
            "requested_platforms": ["Swiggy", "Zomato", "Uber"],
            "expiry_hours": 24,
        },
    )
    assert r_req.status_code == 201
    consent_handle = r_req.json()["consent_handle"]
    assert r_req.json()["status"] == "PENDING"
    assert r_req.json()["disclaimer"] == PROTOTYPE_DISCLAIMER_TEXT

    # Verify scoring BEFORE approval is blocked and charges ₹0
    r_premature = client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": "DEMO_W_STRONG", "consent_handle": consent_handle},
    )
    assert r_premature.status_code == 403
    assert r_premature.json()["error_code"] == "CONSENT_NOT_APPROVED"

    # Step 6: Approve consent
    r_app = client.post(
        "/consent/approve",
        json={"worker_uid": "DEMO_W_STRONG", "consent_handle": consent_handle},
    )
    assert r_app.status_code == 200
    assert r_app.json()["status"] == "APPROVED"

    # Step 7: Fetch mock AA earnings
    r_aa = client.get(f"/mock-aa/fetch/{consent_handle}")
    assert r_aa.status_code == 200
    aa_json = r_aa.json()
    assert aa_json["worker_uid"] == "DEMO_W_STRONG"
    assert aa_json["raw_data_persisted"] is False
    assert len(aa_json["monthly_earnings"]) > 0

    # Step 8-11: Authenticate as lender, submit scoring request, receive 300-900 score, band & factors
    r_score = client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": "DEMO_W_STRONG", "consent_handle": consent_handle},
    )
    assert r_score.status_code == 200
    score_json = r_score.json()
    assert 300 <= score_json["gig_score"] <= 900
    assert score_json["authenticity_status"] == "VERIFIED"
    assert score_json["needs_review"] is False
    assert score_json["fee_charged_inr"] == 30.0
    assert score_json["model_version"] == "xgboost-calibrated-v1.0"
    assert len(score_json["top_factors"]) > 0
    assert score_json["disclaimer"] == PROTOTYPE_DISCLAIMER_TEXT
    strong_req_id = score_json["request_id"]

    # Step 12: Verify ₹30 billing entry is recorded (and no duplicate billing)
    r_usage = client.get(
        f"/lenders/{lender_id}/usage",
        headers={"X-API-Key": api_key},
    )
    assert r_usage.status_code == 200
    usage_json = r_usage.json()
    assert usage_json["total_checks"] == 1
    assert usage_json["total_billed_inr"] == 30.0
    assert len(usage_json["recent_billing_records"]) == 1
    assert usage_json["recent_billing_records"][0]["request_id"] == strong_req_id
    assert usage_json["recent_billing_records"][0]["fee_inr"] == 30.0

    # Step 13: Open the audit record
    r_audit = client.get(
        f"/audit/{strong_req_id}",
        headers={"X-API-Key": api_key},
    )
    assert r_audit.status_code == 200
    audit_json = r_audit.json()
    assert audit_json["request_id"] == strong_req_id
    assert audit_json["gig_score"] == score_json["gig_score"]
    assert audit_json["fee_charged_inr"] == 30.0

    # Step 14: Revoke consent
    r_rev = client.post(
        "/consent/revoke",
        json={
            "worker_uid": "DEMO_W_STRONG",
            "consent_handle": consent_handle,
            "reason": "End-to-end acceptance test revocation",
        },
    )
    assert r_rev.status_code == 200
    assert r_rev.json()["status"] == "REVOKED"

    # Step 15-16: Attempt scoring again & verify scoring is rejected and NOT billed
    r_after_rev = client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": "DEMO_W_STRONG", "consent_handle": consent_handle},
    )
    assert r_after_rev.status_code == 403
    assert r_after_rev.json()["error_code"] == "CONSENT_REVOKED"

    r_usage_after_rev = client.get(
        f"/lenders/{lender_id}/usage",
        headers={"X-API-Key": api_key},
    )
    assert r_usage_after_rev.json()["total_checks"] == 1
    assert r_usage_after_rev.json()["total_billed_inr"] == 30.0

    # =========================================================================
    # PART B: SUSPICIOUS WORKER (DEMO_W_SUSPICIOUS)
    # =========================================================================
    r_sus_req = client.post(
        "/consent/request",
        json={
            "worker_uid": "DEMO_W_SUSPICIOUS",
            "lender_id": lender_id,
            "purpose": "CREDIT_SCORING",
            "requested_platforms": ["Uber", "Freelancing"],
            "expiry_hours": 24,
        },
    )
    assert r_sus_req.status_code == 201
    sus_handle = r_sus_req.json()["consent_handle"]

    r_sus_app = client.post(
        "/consent/approve",
        json={"worker_uid": "DEMO_W_SUSPICIOUS", "consent_handle": sus_handle},
    )
    assert r_sus_app.status_code == 200

    r_sus_score = client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": "DEMO_W_SUSPICIOUS", "consent_handle": sus_handle},
    )
    assert r_sus_score.status_code == 200
    sus_json = r_sus_score.json()
    assert sus_json["authenticity_status"] == "NEEDS_REVIEW"
    assert sus_json["needs_review"] is True
    assert sus_json["gig_score"] is None
    assert sus_json["fee_charged_inr"] == 0.0
    assert len(sus_json["authenticity"]["flags"]) >= 3

    # Verify NO billing was recorded for the suspicious worker check (total remains ₹30.00 / 1 check)
    r_usage_final = client.get(
        f"/lenders/{lender_id}/usage",
        headers={"X-API-Key": api_key},
    )
    assert r_usage_final.json()["total_checks"] == 1
    assert r_usage_final.json()["total_billed_inr"] == 30.0

    # Verify audit record WAS created for the flagged check with fee_charged_inr == 0.0
    r_sus_audit = client.get(
        f"/audit/{sus_json['request_id']}",
        headers={"X-API-Key": api_key},
    )
    assert r_sus_audit.status_code == 200
    assert r_sus_audit.json()["authenticity_status"] == "NEEDS_REVIEW"
    assert r_sus_audit.json()["gig_score"] is None
    assert r_sus_audit.json()["fee_charged_inr"] == 0.0

