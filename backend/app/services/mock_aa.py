"""Deterministic Mock Account Aggregator (AA) Provider Service.

Simulates bank-verified and platform earnings retrieval for the 5 demonstration workers
as well as arbitrary synthetic workers without ever persisting raw financial transactions.

Prototype - synthetic data only. Not for real lending decisions.
"""
from typing import Any, Dict, List, Tuple

from app.ml.generate_data import generate_worker_monthly_history

DEMO_WORKERS_CATALOG: Dict[str, Dict[str, Any]] = {
    "DEMO_W_STRONG": {
        "worker_uid": "DEMO_W_STRONG",
        "name": "Aarav Sharma",
        "phone": "+91-9810010001",
        "e_shram_id": "ESHRAM-KA-900101",
        "persona": "multi_platform_hustler",
        "profile_label": "1. Strong earnings profile",
        "primary_city": "Bengaluru (Tier-1)",
        "tenure_months": 24,
        "platforms": ["Swiggy", "Zomato", "Uber"],
        "summary_badge": "High Consistency • 3 Platforms • 24m Tenure",
    },
    "DEMO_W_AVERAGE": {
        "worker_uid": "DEMO_W_AVERAGE",
        "name": "Priya Verma",
        "phone": "+91-9810010002",
        "e_shram_id": "ESHRAM-MH-900102",
        "persona": "stable_full_time",
        "profile_label": "2. Average earnings profile",
        "primary_city": "Pune (Tier-1)",
        "tenure_months": 14,
        "platforms": ["Zomato", "Ola"],
        "summary_badge": "Steady Earnings • 2 Platforms • 14m Tenure",
    },
    "DEMO_W_VOLATILE": {
        "worker_uid": "DEMO_W_VOLATILE",
        "name": "Rohan Das",
        "phone": "+91-9810010003",
        "e_shram_id": "ESHRAM-WB-900103",
        "persona": "volatile_part_time",
        "profile_label": "3. Volatile earnings profile",
        "primary_city": "Kolkata (Tier-1)",
        "tenure_months": 15,
        "platforms": ["Swiggy"],
        "summary_badge": "High Volatility • 3 Income Gap Months • 1 Platform",
    },
    "DEMO_W_NEW": {
        "worker_uid": "DEMO_W_NEW",
        "name": "Neha Nair",
        "phone": "+91-9810010004",
        "e_shram_id": "ESHRAM-KL-900104",
        "persona": "new_joiner",
        "profile_label": "4. New joiner",
        "primary_city": "Kochi (Tier-2)",
        "tenure_months": 6,
        "platforms": ["Urban Company"],
        "summary_badge": "Short History (6m) • High Rating (4.75) • 1 Platform",
    },
    "DEMO_W_SUSPICIOUS": {
        "worker_uid": "DEMO_W_SUSPICIOUS",
        "name": "Vikram Singh (Tampered Demo)",
        "phone": "+91-9810010005",
        "e_shram_id": "ESHRAM-DL-900105",
        "persona": "declining_earner",
        "profile_label": "5. Suspicious earnings profile",
        "primary_city": "Delhi NCR (Tier-1)",
        "tenure_months": 36,
        "platforms": ["Uber", "Freelancing"],
        "summary_badge": "Round Numbers • Claimed > Bank Credits • Duplicate Tx • 5x Spike",
    },
}

DEMO_LENDERS_CATALOG: List[Dict[str, Any]] = [
    {
        "lender_id": "LENDER_SAMUNNATI_NBFC",
        "name": "Samunnati Micro-Mobility NBFC (Demo)",
        "demo_api_key": "gsk_demo_samunnati_2026_secret_key",
        "api_key_prefix": "gsk_demo_samu",
        "rate_limit_per_minute": 60,
        "fee_per_check_inr": 30.0,
    },
    {
        "lender_id": "LENDER_PRAGATI_FINTECH",
        "name": "Pragati EV Fleet Finance (Demo)",
        "demo_api_key": "gsk_demo_pragati_2026_secret_key",
        "api_key_prefix": "gsk_demo_prag",
        "rate_limit_per_minute": 60,
        "fee_per_check_inr": 30.0,
    },
]


def _build_curated_demo_history(worker_uid: str) -> Tuple[List[Dict[str, Any]], int, List[str], str]:
    """Generate deterministic, realistic monthly records for the 5 showcase workers."""
    months_24 = [
        f"{2025 + (9 + i) // 12:04d}-{(9 + i) % 12 + 1:02d}" for i in range(24)
    ]

    if worker_uid == "DEMO_W_STRONG":
        records: List[Dict[str, Any]] = []
        platforms = ["Swiggy", "Zomato", "Uber"]
        shares = [0.42, 0.33, 0.25]
        for idx, ym in enumerate(months_24):
            # Steadily growing ₹39,000 -> ₹45,500 across 3 platforms
            month_total = 39200.0 + idx * 275.0 + ((idx % 3) - 1) * 420.0
            for p_i, plat in enumerate(platforms):
                verified = round(month_total * shares[p_i], 2)
                claimed = round(verified * 1.01, 2)
                records.append(
                    {
                        "month": ym,
                        "platform": plat,
                        "claimed_earnings_inr": claimed,
                        "bank_verified_credit_inr": verified,
                        "trips_or_orders_completed": int(round(verified / 82.0)),
                        "active_days": 26,
                        "platform_rating": 4.88,
                    }
                )
        return records, 24, platforms, "multi_platform_hustler"

    if worker_uid == "DEMO_W_AVERAGE":
        records = []
        platforms = ["Zomato", "Ola"]
        shares = [0.60, 0.40]
        for idx, ym in enumerate(months_24[-14:]):
            if idx == 5:
                # 1 minor gap month
                month_total = 800.0
            else:
                month_total = 21500.0 + ((idx % 4) - 1.5) * 1450.0
            for p_i, plat in enumerate(platforms):
                verified = round(month_total * shares[p_i], 2)
                claimed = round(verified * 1.02, 2)
                records.append(
                    {
                        "month": ym,
                        "platform": plat,
                        "claimed_earnings_inr": claimed,
                        "bank_verified_credit_inr": verified,
                        "trips_or_orders_completed": int(round(verified / 88.0)),
                        "active_days": 22 if month_total > 1000 else 2,
                        "platform_rating": 4.52,
                    }
                )
        return records, 14, platforms, "stable_full_time"

    if worker_uid == "DEMO_W_VOLATILE":
        records = []
        platforms = ["Swiggy"]
        volatile_Pattern = [
            19500.0,
            11200.0,
            450.0,  # gap
            22400.0,
            9800.0,
            18100.0,
            300.0,  # gap
            16200.0,
            8400.0,
            15900.0,
            500.0,  # gap
            13200.0,
            7900.0,
            11400.0,
            9600.0,
        ]
        for idx, ym in enumerate(months_24[-15:]):
            verified = volatile_Pattern[idx]
            claimed = round(verified * 1.03, 2)
            records.append(
                {
                    "month": ym,
                    "platform": "Swiggy",
                    "claimed_earnings_inr": claimed,
                    "bank_verified_credit_inr": verified,
                    "trips_or_orders_completed": int(round(verified / 80.0)),
                    "active_days": 18 if verified > 1000 else 1,
                    "platform_rating": 4.16,
                }
            )
        return records, 15, platforms, "volatile_part_time"

    if worker_uid == "DEMO_W_NEW":
        records = []
        platforms = ["Urban Company"]
        for idx, ym in enumerate(months_24[-6:]):
            verified = round(17400.0 + idx * 480.0 + ((idx % 2) * 310.0), 2)
            claimed = round(verified * 1.01, 2)
            records.append(
                {
                    "month": ym,
                    "platform": "Urban Company",
                    "claimed_earnings_inr": claimed,
                    "bank_verified_credit_inr": verified,
                    "trips_or_orders_completed": int(round(verified / 450.0)),
                    "active_days": 21,
                    "platform_rating": 4.74,
                }
            )
        return records, 6, platforms, "new_joiner"

    if worker_uid == "DEMO_W_SUSPICIOUS":
        records = []
        platforms = ["Uber", "Freelancing"]
        # Only 7 observed months despite claiming 36 months tenure, exact ₹1,000 multiples,
        # claimed earnings 1.9x bank verified credits, duplicate payout row, and a 5.5x final jump!
        base_amounts = [12000.0, 14000.0, 13000.0, 15000.0, 12000.0, 14000.0, 78000.0]
        for idx, ym in enumerate(months_24[-7:]):
            verified = base_amounts[idx]
            claimed = round(verified * 1.90, 2)
            row = {
                "month": ym,
                "platform": "Uber",
                "claimed_earnings_inr": claimed,
                "bank_verified_credit_inr": verified,
                "trips_or_orders_completed": 150,
                "active_days": 20,
                "platform_rating": 4.10,
            }
            records.append(row)
            if idx == 4:
                # Exact duplicate transaction entry
                records.append(dict(row))
        return records, 36, platforms, "declining_earner"

    # Generic deterministic synthetic history for any other worker_uid
    recs, tenure, plats = generate_worker_monthly_history(worker_uid=worker_uid)
    return recs, tenure, plats, "stable_full_time"


def fetch_ephemeral_aa_earnings(
    worker_uid: str,
    declared_tenure_override: int | None = None,
) -> Dict[str, Any]:
    """Fetch bank-verified and platform monthly earnings in memory (never persisted to DB)."""
    records, default_tenure, platforms, persona = _build_curated_demo_history(
        worker_uid
    )
    tenure_months = (
        declared_tenure_override
        if declared_tenure_override is not None
        else default_tenure
    )

    total_verified = sum(float(r["bank_verified_credit_inr"]) for r in records)
    total_claimed = sum(float(r["claimed_earnings_inr"]) for r in records)
    distinct_months = max(1, len({r["month"] for r in records}))

    summary = {
        "total_bank_verified_inr": round(total_verified, 2),
        "total_claimed_inr": round(total_claimed, 2),
        "avg_monthly_verified_inr": round(total_verified / distinct_months, 2),
        "observed_months": float(distinct_months),
        "platform_count": float(len(platforms)),
    }

    return {
        "worker_uid": worker_uid,
        "persona": persona,
        "tenure_months": tenure_months,
        "platforms_connected": platforms,
        "monthly_earnings": records,
        "aggregated_summary": summary,
        "raw_data_persisted": False,
    }

