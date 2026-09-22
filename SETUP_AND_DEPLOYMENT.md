# GigScore: Free Setup, Build & Deployment Guide

## 1. Project Overview
GigScore is an alternative credit-scoring platform for gig workers, computing a portable score from multi-platform earnings via Account Aggregator workflows.

## 2. Recommended Zero-Cost Architecture
- **IDE & Development**: Google Antigravity (Local Multi-Agent Orchestration)
- **Frontend**: React (Vite) + Tailwind CSS → **Vercel**
- **Backend API & ML Engine**: FastAPI + XGBoost + Scikit-Learn → **Render Web Service**
- **Database**: PostgreSQL → **Neon.tech** or **Supabase** (Free Tier)
- **Account Aggregator**: Setu AA Sandbox / Local Mock Consent API

---

## 3. Project Structure
```text
gigscore/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application entrypoint
│   │   ├── config.py            # Environment variables & DB settings
│   │   ├── database.py          # SQLAlchemy engine & session
│   │   ├── models.py            # Postgres DB tables
│   │   ├── schemas.py           # Pydantic input/output schemas
│   │   ├── ml/
│   │   │   ├── model.py         # XGBoost model loader & inference
│   │   │   └── explain.py       # Plain-language factor generator
│   │   └── routes/
│   │       ├── consent.py       # Consent initiation / callback
│   │       └── score.py         # Score computation & lender API
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/          # Reusable UI components
│   │   ├── pages/               # Worker consent & Lender dashboard
│   │   └── App.jsx
│   ├── package.json
│   └── vite.config.js
└── README.md
