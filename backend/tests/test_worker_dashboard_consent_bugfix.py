"""Automated regression test suite for Worker Dashboard infinite consent creation & revocation display bugfix.

Verifies all 9 required safeguards:
1. Opening the dashboard does not create consent.
2. Refreshing the dashboard does not create consent.
3. Switching worker profiles does not create consent.
4. Clicking Grant New Consent once creates exactly one request.
5. Rapidly clicking the button / sending rapid requests does not create duplicates.
6. Revoking consent prevents further scoring.
7. Refreshing after revocation does not restore authorization.
8. Pending and revoked consent never display a valid score.
9. Existing consent history is preserved.

Prototype - synthetic data only. Not for real lending decisions.
"""
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import sessionmaker

from app.core.database import create_db_engine, get_db, init_db
from app.core.security import reset_rate_limits
from app.main import app
from app.models.db_models import ConsentRecord, ScoreAudit
from scripts.seed import seed_database


@pytest.fixture()
def dashboard_client(tmp_path: Path):
    """Provide an isolated SQLite test database and seeded TestClient."""
    reset_rate_limits()
    db_file = tmp_path / "test_dashboard_bugfix.db"
    sqlite_engine = create_db_engine(f"sqlite:///{db_file}")
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
    sqlite_engine.dispose()
    reset_rate_limits()


def test_1_opening_dashboard_does_not_create_consent(dashboard_client) -> None:
    """1. Opening the Worker Dashboard HTML and overview endpoint must never create new consent rows."""
    client, SessionLocalOverride = dashboard_client
    with SessionLocalOverride() as db:
        before_count = db.query(ConsentRecord).count()

    r_html = client.get("/worker")
    assert r_html.status_code == 200

    r_overview = client.get("/api/workers/DEMO_W_STRONG/overview")
    assert r_overview.status_code == 200

    with SessionLocalOverride() as db:
        after_count = db.query(ConsentRecord).count()

    assert after_count == before_count

    # Also verify static/app.js loadWorkerDashboard does not call workerComputeFreshScore or workerGrantNewConsent
    app_js = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    load_fn_block = app_js.split("window.loadWorkerDashboard")[1].split(
        "function renderWorkerScorePanel"
    )[0]
    assert "workerComputeFreshScore" not in load_fn_block
    assert "workerGrantNewConsent" not in load_fn_block


def test_2_refreshing_dashboard_does_not_create_consent(dashboard_client) -> None:
    """2. Repeatedly refreshing the dashboard or calling Refresh Score must never create new consents."""
    client, SessionLocalOverride = dashboard_client
    with SessionLocalOverride() as db:
        before_count = db.query(ConsentRecord).count()

    for _ in range(5):
        r = client.get("/api/workers/DEMO_W_AVERAGE/overview")
        assert r.status_code == 200

    with SessionLocalOverride() as db:
        after_count = db.query(ConsentRecord).count()

    assert after_count == before_count

    # Verify workerComputeFreshScore in static/app.js never calls workerGrantNewConsent or /consent/request
    app_js = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    fresh_score_block = app_js.split("window.workerComputeFreshScore")[1].split(
        "/* ==="
    )[0]
    assert "workerGrantNewConsent" not in fresh_score_block
    assert "/consent/request" not in fresh_score_block


def test_3_switching_worker_profiles_does_not_create_consent(
    dashboard_client,
) -> None:
    """3. Switching across all 5 worker personas must not create any new consent records."""
    client, SessionLocalOverride = dashboard_client
    with SessionLocalOverride() as db:
        before_count = db.query(ConsentRecord).count()

    for worker_uid in [
        "DEMO_W_STRONG",
        "DEMO_W_AVERAGE",
        "DEMO_W_VOLATILE",
        "DEMO_W_NEW",
        "DEMO_W_SUSPICIOUS",
    ]:
        r = client.get(f"/api/workers/{worker_uid}/overview")
        assert r.status_code == 200
        assert r.json()["worker"]["worker_uid"] == worker_uid

    with SessionLocalOverride() as db:
        after_count = db.query(ConsentRecord).count()

    assert after_count == before_count


def test_4_clicking_grant_new_consent_once_creates_single_request(
    dashboard_client,
) -> None:
    """4. Explicitly granting new consent once creates exactly 1 PENDING consent record."""
    client, SessionLocalOverride = dashboard_client
    worker_uid = "DEMO_W_VOLATILE"

    # First revoke the pre-seeded consent so the worker needs a new consent
    client.post(
        "/consent/revoke",
        json={
            "worker_uid": worker_uid,
            "consent_handle": "consent_demo_demo_w_volatile",
        },
    )

    with SessionLocalOverride() as db:
        count_before = (
            db.query(ConsentRecord).filter_by(worker_uid=worker_uid).count()
        )

    res = client.post(
        "/consent/request",
        json={
            "worker_uid": worker_uid,
            "lender_id": "LENDER_SAMUNNATI_NBFC",
            "purpose": "CREDIT_SCORING",
            "requested_platforms": ["Swiggy"],
            "expiry_hours": 48,
        },
    )
    assert res.status_code == 201
    assert res.json()["status"] == "PENDING"

    with SessionLocalOverride() as db:
        count_after = (
            db.query(ConsentRecord).filter_by(worker_uid=worker_uid).count()
        )
        pending_count = (
            db.query(ConsentRecord)
            .filter_by(worker_uid=worker_uid, status="PENDING")
            .count()
        )

    assert count_after == count_before + 1
    assert pending_count == 1


def test_5_rapidly_clicking_button_does_not_create_duplicates(
    dashboard_client,
) -> None:
    """5. Rapid duplicate POST /consent/request calls return the same PENDING handle without creating duplicates."""
    client, SessionLocalOverride = dashboard_client
    worker_uid = "DEMO_W_NEW"

    payload = {
        "worker_uid": worker_uid,
        "lender_id": "LENDER_SAMUNNATI_NBFC",
        "purpose": "CREDIT_SCORING",
        "requested_platforms": ["Urban Company"],
        "expiry_hours": 48,
    }

    # First call creates 1 PENDING consent (and supersedes the seeded one)
    r1 = client.post("/consent/request", json=payload)
    assert r1.status_code == 201
    first_handle = r1.json()["consent_handle"]

    with SessionLocalOverride() as db:
        count_after_first = (
            db.query(ConsentRecord).filter_by(worker_uid=worker_uid).count()
        )

    # Simulate 6 rapid duplicate clicks / requests for the same worker, lender, purpose, and AA
    for _ in range(6):
        r_dup = client.post("/consent/request", json=payload)
        assert r_dup.status_code == 201
        assert r_dup.json()["consent_handle"] == first_handle
        assert r_dup.json()["status"] == "PENDING"

    with SessionLocalOverride() as db:
        count_after_rapid = (
            db.query(ConsentRecord).filter_by(worker_uid=worker_uid).count()
        )
        active_or_pending = (
            db.query(ConsentRecord)
            .filter(
                ConsentRecord.worker_uid == worker_uid,
                ConsentRecord.status.in_(["PENDING", "APPROVED"]),
            )
            .count()
        )

    # Zero duplicate rows created across all 6 rapid requests, and only 1 active/pending row exists
    assert count_after_rapid == count_after_first
    assert active_or_pending == 1


def test_6_revoking_consent_prevents_further_scoring(dashboard_client) -> None:
    """6. Revoking consent immediately stops authorization for scoring."""
    client, _ = dashboard_client
    api_key = "gsk_demo_samunnati_2026_secret_key"
    worker_uid = "DEMO_W_STRONG"
    handle = "consent_demo_demo_w_strong"

    # Score succeeds while APPROVED
    r_ok = client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": worker_uid, "consent_handle": handle},
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["gig_score"] is not None

    # Revoke consent
    r_rev = client.post(
        "/consent/revoke",
        json={"worker_uid": worker_uid, "consent_handle": handle},
    )
    assert r_rev.status_code == 200
    assert r_rev.json()["status"] == "REVOKED"

    # Subsequent scoring is immediately blocked with 403 CONSENT_REVOKED
    r_blocked = client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": worker_uid, "consent_handle": handle},
    )
    assert r_blocked.status_code == 403
    assert r_blocked.json()["error_code"] == "CONSENT_REVOKED"


def test_7_refreshing_after_revocation_does_not_restore_authorization(
    dashboard_client,
) -> None:
    """7. Refreshing the dashboard or re-running seed_database after revocation must never restore authorization."""
    client, SessionLocalOverride = dashboard_client
    worker_uid = "DEMO_W_AVERAGE"
    handle = "consent_demo_demo_w_average"

    client.post(
        "/consent/revoke",
        json={"worker_uid": worker_uid, "consent_handle": handle},
    )

    # Refresh overview multiple times
    for _ in range(3):
        ov = client.get(f"/api/workers/{worker_uid}/overview").json()
        assert ov["consent_status"] == "REVOKED"
        assert ov["active_consent_handle"] is None
        assert ov["latest_score"] is None

    # Even re-running seed_database() must NOT un-revoke an existing revoked consent
    with SessionLocalOverride() as db:
        seed_database(db=db)

    ov_after_seed = client.get(f"/api/workers/{worker_uid}/overview").json()
    assert ov_after_seed["consent_status"] == "REVOKED"
    assert ov_after_seed["active_consent_handle"] is None
    assert ov_after_seed["latest_score"] is None


def test_8_pending_and_revoked_consent_never_display_valid_score(
    dashboard_client,
) -> None:
    """8. Pending and revoked consents must never return a stale score or fallback 650."""
    client, _ = dashboard_client
    api_key = "gsk_demo_samunnati_2026_secret_key"
    worker_uid = "DEMO_W_STRONG"
    seeded_handle = "consent_demo_demo_w_strong"

    # Compute a valid score first
    r_score = client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": worker_uid, "consent_handle": seeded_handle},
    )
    assert r_score.status_code == 200
    assert r_score.json()["gig_score"] >= 750

    # Revoke consent and trigger a rejected score attempt (which writes REJECTED_CONSENT_REVOKED to ScoreAudit)
    client.post(
        "/consent/revoke",
        json={"worker_uid": worker_uid, "consent_handle": seeded_handle},
    )
    client.post(
        "/score",
        headers={"X-API-Key": api_key},
        json={"worker_uid": worker_uid, "consent_handle": seeded_handle},
    )

    # Overview while REVOKED must return latest_score == None (never stale score, never REJECTED_CONSENT_REVOKED)
    ov_revoked = client.get(f"/api/workers/{worker_uid}/overview").json()
    assert ov_revoked["consent_status"] == "REVOKED"
    assert ov_revoked["latest_score"] is None

    # Create a new PENDING consent request
    r_new = client.post(
        "/consent/request",
        json={
            "worker_uid": worker_uid,
            "lender_id": "LENDER_SAMUNNATI_NBFC",
            "purpose": "CREDIT_SCORING",
        },
    )
    assert r_new.json()["status"] == "PENDING"

    # Overview while PENDING must also return latest_score == None
    ov_pending = client.get(f"/api/workers/{worker_uid}/overview").json()
    assert ov_pending["consent_status"] == "PENDING"
    assert ov_pending["latest_score"] is None

    # Also verify that `scoreObj.gig_score || 650` is completely removed from static/app.js
    app_js = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    assert "scoreObj.gig_score || 650" not in app_js


def test_9_existing_consent_history_is_preserved(dashboard_client) -> None:
    """9. Creating, superseding, approving, and revoking consents must preserve all historical rows."""
    client, SessionLocalOverride = dashboard_client
    worker_uid = "DEMO_W_STRONG"

    with SessionLocalOverride() as db:
        initial_ids = {
            c.id
            for c in db.query(ConsentRecord)
            .filter_by(worker_uid=worker_uid)
            .all()
        }
    assert len(initial_ids) >= 1

    # Request new consent (supersedes initial), approve it, then revoke it
    r_req = client.post(
        "/consent/request",
        json={
            "worker_uid": worker_uid,
            "lender_id": "LENDER_SAMUNNATI_NBFC",
            "purpose": "CREDIT_SCORING",
        },
    )
    new_handle = r_req.json()["consent_handle"]
    client.post(
        "/consent/approve",
        json={"worker_uid": worker_uid, "consent_handle": new_handle},
    )
    client.post(
        "/consent/revoke",
        json={"worker_uid": worker_uid, "consent_handle": new_handle},
    )

    with SessionLocalOverride() as db:
        final_rows = (
            db.query(ConsentRecord).filter_by(worker_uid=worker_uid).all()
        )
        final_ids = {c.id for c in final_rows}

    # All initial historical rows still exist plus the new row
    assert initial_ids.issubset(final_ids)
    assert len(final_ids) == len(initial_ids) + 1

