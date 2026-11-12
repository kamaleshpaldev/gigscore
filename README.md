# GigScore — Portable Credit-Scoring Infrastructure for Indian Gig Workers

> **Disclaimer:** *Prototype - synthetic data only. Not for real lending decisions.*

**Founder:** Kamalesh Pal

GigScore is a full-stack alternative credit-scoring infrastructure prototype for Indian gig workers. It computes a portable **300–900 credit score** from consent-verified multi-platform earnings (Swiggy, Zomato, Uber, Ola, Urban Company, Freelancing) via a deterministic Mock Account Aggregator (AA) workflow, 5-point Data Authenticity Engine, Isotonic-Calibrated Monotonic XGBoost model (with transparent Rule-Based Scorecard fallback), and SHAP plain-English explanations.

---

## 1. Quick Start (Local Development)

From the project root (`gigscore/`) or `gigscore/backend/`:

```bash
make setup   # Install dependencies into backend/.venv
make data    # Generate 20,000 synthetic gig worker profiles (~12% default rate)
make train   # Train & calibrate XGBoost model, run fairness audit & generate MODEL_CARD.md
make seed    # Seed 5 demonstration workers, 2 lenders & active consents
make test    # Run full Pytest suite (Phase 1 + Complete System + 16-Step E2E Acceptance)
make run     # Start FastAPI server + integrated Web UI on http://localhost:8000
```

* **Web Application (Landing, Demo Console, Worker Passport, Lender Portal, Model Transparency):** `http://localhost:8000`
* **Interactive OpenAPI / Swagger Docs:** `http://localhost:8000/docs`
* **Health Check:** `http://localhost:8000/health`

---

## 2. Demo Credentials (Local Development / Presentation Sandbox Only)

### Demonstration Workers
| Worker UID | Name | Persona / Profile | Expected Outcome |
| :--- | :--- | :--- | :--- |
| `DEMO_W_STRONG` | Aarav Sharma | 1. Strong earnings profile (`multi_platform_hustler`, 24m, 3 apps) | `VERIFIED` • Score ~818 (`750-900 Excellent`) • ₹30 billed |
| `DEMO_W_AVERAGE` | Priya Verma | 2. Average earnings profile (`stable_full_time`, 14m, 2 apps) | `VERIFIED` • Score ~700 (`650-749 Good`) • ₹30 billed |
| `DEMO_W_VOLATILE` | Rohan Das | 3. Volatile earnings profile (`volatile_part_time`, 15m, 3 gap months) | `VERIFIED` • Score ~540–610 (`High/Very High Risk`) • ₹30 billed |
| `DEMO_W_NEW` | Neha Nair | 4. New joiner (`new_joiner`, 6m tenure, rating 4.74) | `VERIFIED` • Score ~690 (`650-749 Good`) • ₹30 billed |
| `DEMO_W_SUSPICIOUS` | Vikram Singh | 5. Suspicious earnings profile (round numbers, claimed > bank, duplicate tx, 5.5x spike) | `NEEDS_REVIEW` • **No score generated (`null`)** • **₹0 billed** |

### Demonstration Lenders (HMAC-SHA256 Hashed in DB)
| Lender ID | Organization | Demo `X-API-Key` Header | Fee / Check |
| :--- | :--- | :--- | :--- |
| `LENDER_SAMUNNATI_NBFC` | Samunnati Micro-Mobility NBFC (Demo) | `gsk_demo_samunnati_2026_secret_key` | ₹30.00 |
| `LENDER_PRAGATI_FINTECH` | Pragati EV Fleet Finance (Demo) | `gsk_demo_pragati_2026_secret_key` | ₹30.00 |

---

## 3. Fixed API Endpoints

| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/consent/request` | Public / Worker | Create a `PENDING` consent handle with purpose validation & TTL |
| `POST` | `/consent/approve` | Public / Worker | Approve a `PENDING` consent handle (`status="APPROVED"`) |
| `POST` | `/consent/revoke` | Public / Worker | One-tap consent revocation (`status="REVOKED"`) |
| `GET` | `/mock-aa/fetch/{consent_id}` | Consent-Gated | Fetch ephemeral bank-verified & platform monthly earnings (`raw_data_persisted=False`) |
| `POST` | `/score` | `X-API-Key` | Verify consent, run 5-point authenticity check, compute 300–900 score + SHAP explanations, bill ₹30 on verified checks |
| `GET` | `/lenders/{id}/usage` | `X-API-Key` | Retrieve lender check count and ₹30 billing ledger (enforces lender isolation) |
| `GET` | `/audit/{request_id}` | Optional `X-API-Key` | Retrieve immutable score audit record by `request_id` |
| `GET` | `/health` | Public | Database & active model health probe |

---

## 4. Docker & Free-Tier Deployment Guide

### Run with Docker Compose
```bash
docker compose up --build
```

### Free-Tier Cloud Deployment Notes (Render + Neon/Supabase PostgreSQL)
1. **Single-Service Architecture:** FastAPI serves both the REST API and the Tailwind/JS frontend from `backend/app/main.py`, eliminating cross-origin deployment overhead.
2. **Ephemeral Disk & Sleep Behavior on Free Hosting:** Free web service tiers (such as Render Free) spin down after inactivity (~15 minutes) and use an **ephemeral filesystem** that resets on redeploy/restart.
   * For persistent production/demo storage across restarts, set `DATABASE_URL` to a hosted PostgreSQL database (such as Neon or Supabase free tier).
   * For local development or single-session container demos, the default `sqlite:///./gigscore.db` works with zero external setup.
3. **Deployment Checklist:**
   - [ ] Never commit `.env` or production API keys.
   - [ ] Set `DATABASE_URL`, `API_KEY_HASH_SALT`, and `CORS_ORIGINS` in the hosting provider's environment variables.
   - [ ] Configure health check path to `/health`.
   - [ ] Verify `"Prototype - synthetic data only. Not for real lending decisions."` banner is visible.

