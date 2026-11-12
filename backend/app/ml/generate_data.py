"""Synthetic Gig-Worker Data Generator (20,000 Workers across 5 Personas & 6 Platforms).

Prototype - synthetic data only. Not for real lending decisions.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import math
import numpy as np
import pandas as pd

from app.ml.features import FEATURE_COLUMNS, compute_worker_features

PLATFORMS: List[str] = [
    "Swiggy",
    "Zomato",
    "Uber",
    "Ola",
    "Urban Company",
    "Freelancing",
]

PLATFORM_TYPE_MAP: Dict[str, str] = {
    "Swiggy": "Food Delivery",
    "Zomato": "Food Delivery",
    "Uber": "Ride Hailing",
    "Ola": "Ride Hailing",
    "Urban Company": "Home Services",
    "Freelancing": "Freelancing",
}

PERSONAS: Dict[str, Dict[str, Any]] = {
    "stable_full_time": {
        "label": "Stable full-time worker",
        "weight": 0.32,
        "tenure_range": (14, 36),
        "base_income_range": (24000.0, 48000.0),
        "volatility_range": (0.06, 0.18),
        "gap_prob": 0.02,
        "platform_count_choices": [1, 2],
        "rating_range": (4.55, 4.95),
        "trend_range": (-0.04, 0.18),
    },
    "volatile_part_time": {
        "label": "Volatile part-time worker",
        "weight": 0.24,
        "tenure_range": (8, 28),
        "base_income_range": (9500.0, 22000.0),
        "volatility_range": (0.32, 0.68),
        "gap_prob": 0.18,
        "platform_count_choices": [1, 2],
        "rating_range": (4.05, 4.65),
        "trend_range": (-0.20, 0.15),
    },
    "multi_platform_hustler": {
        "label": "Multi-platform hustler",
        "weight": 0.20,
        "tenure_range": (10, 36),
        "base_income_range": (28000.0, 62000.0),
        "volatility_range": (0.12, 0.28),
        "gap_prob": 0.03,
        "platform_count_choices": [3, 4],
        "rating_range": (4.45, 4.92),
        "trend_range": (0.02, 0.28),
    },
    "new_joiner": {
        "label": "New joiner",
        "weight": 0.14,
        "tenure_range": (6, 9),
        "base_income_range": (12000.0, 26000.0),
        "volatility_range": (0.20, 0.42),
        "gap_prob": 0.08,
        "platform_count_choices": [1, 2],
        "rating_range": (4.20, 4.75),
        "trend_range": (-0.05, 0.25),
    },
    "declining_earner": {
        "label": "Declining earner",
        "weight": 0.10,
        "tenure_range": (12, 34),
        "base_income_range": (11000.0, 28000.0),
        "volatility_range": (0.28, 0.62),
        "gap_prob": 0.22,
        "platform_count_choices": [1, 2],
        "rating_range": (3.75, 4.40),
        "trend_range": (-0.55, -0.18),
    },
}

CITY_TIERS = ["Tier-1", "Tier-2", "Tier-3"]
CITY_TIER_WEIGHTS = [0.48, 0.34, 0.18]

# Audit-only demographic attribute (NEVER used as a model input)
AUDIT_GENDERS = ["Male", "Female", "Non-Binary"]
AUDIT_GENDER_WEIGHTS = [0.78, 0.20, 0.02]


def _hidden_default_log_odds(features: Dict[str, float]) -> float:
    """INTERNAL ONLY: Compute latent log-odds of default from behavioral features.

    IMPORTANT: This function is used strictly during synthetic dataset generation
    to simulate ~12% repayment defaults. It must NEVER be passed as a model feature.
    """
    tenure = features["tenure_months"]
    earnings = features["avg_monthly_earnings"]
    cv = features["earnings_cv"]
    trend = features["earnings_trend_6m"]
    gaps = features["income_gap_months"]
    platforms = features["platform_count"]
    rating = features["avg_rating"]
    peak_ratio = features["earnings_to_peak_ratio"]

    # Calibrated intercept + behavioral risk drivers targeting ~12% overall default rate
    z = (
        -3.56
        - 0.048 * (tenure - 16.0)
        - 0.000055 * (earnings - 24000.0)
        + 2.65 * (cv - 0.28)
        - 1.85 * trend
        + 0.38 * gaps
        - 0.34 * (platforms - 1.8)
        - 1.15 * (rating - 4.45)
        - 1.55 * (peak_ratio - 0.72)
    )
    return float(z)


def generate_worker_monthly_history(
    worker_uid: str,
    persona_key: str = "stable_full_time",
    seed: Optional[int] = None,
    tamper_suspicious: bool = False,
) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    """Generate 6-36 months of realistic multi-platform monthly earnings for a single worker."""
    if seed is None:
        seed = abs(hash(worker_uid)) % (2**31 - 1)
    rng = np.random.default_rng(seed)

    p_cfg = PERSONAS.get(persona_key, PERSONAS["stable_full_time"])
    tenure_months = int(
        rng.integers(p_cfg["tenure_range"][0], p_cfg["tenure_range"][1] + 1)
    )
    n_platforms = int(rng.choice(p_cfg["platform_count_choices"]))
    chosen_platforms = list(
        rng.choice(PLATFORMS, size=min(n_platforms, len(PLATFORMS)), replace=False)
    )

    base_monthly_total = float(
        rng.uniform(p_cfg["base_income_range"][0], p_cfg["base_income_range"][1])
    )
    volatility = float(
        rng.uniform(p_cfg["volatility_range"][0], p_cfg["volatility_range"][1])
    )
    trend_rate = float(
        rng.uniform(p_cfg["trend_range"][0], p_cfg["trend_range"][1])
    )
    base_rating = float(
        rng.uniform(p_cfg["rating_range"][0], p_cfg["rating_range"][1])
    )

    # Platform share weights
    raw_weights = rng.dirichlet(np.ones(len(chosen_platforms)))

    # Generate chronological YYYY-MM labels ending at 2026-10
    end_year, end_month = 2026, 10
    months_list: List[str] = []
    y, m = end_year, end_month
    for _ in range(tenure_months):
        months_list.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months_list.reverse()

    records: List[Dict[str, Any]] = []
    for idx, ym in enumerate(months_list):
        month_num = int(ym.split("-")[1])
        # Seasonal multiplier: festive peak in Oct-Dec (+12%), monsoon dip Jul-Aug (-7%)
        if month_num in (10, 11, 12):
            seasonal = 1.12
        elif month_num in (7, 8):
            seasonal = 0.93
        else:
            seasonal = 1.00

        # Apply progressive trend especially over recent 6-12 months
        progress = idx / max(1, tenure_months - 1)
        trend_mult = max(0.35, 1.0 + trend_rate * (progress - 0.5))

        # Check if this month is an income gap month
        is_gap = bool(rng.random() < p_cfg["gap_prob"])
        if is_gap:
            month_total = float(rng.uniform(0.0, 600.0))
        else:
            noise = float(rng.normal(1.0, volatility))
            month_total = max(1200.0, base_monthly_total * seasonal * trend_mult * noise)

        for p_idx, plat in enumerate(chosen_platforms):
            plat_share = float(raw_weights[p_idx]) * float(rng.uniform(0.90, 1.10))
            verified_amt = round(max(0.0, month_total * plat_share), 2)
            # Claimed earnings normally within 0-4% of verified bank credits
            claimed_amt = round(verified_amt * float(rng.uniform(0.98, 1.03)), 2)

            if tamper_suspicious:
                # Inject synthetic fraud signals: exact ₹1,000 multiples, inflated claimed income, and an impossible jump
                verified_amt = float(round(verified_amt / 1000.0) * 1000.0)
                if verified_amt < 5000.0:
                    verified_amt = 15000.0
                if idx == len(months_list) - 1:
                    verified_amt = verified_amt * 5.0
                claimed_amt = round(verified_amt * 1.85, 2)

            orders = int(max(0, round(verified_amt / 85.0)))
            active_days = (
                0 if verified_amt < 500 else int(min(30, max(3, round(orders / 14))))
            )
            rating = round(
                float(np.clip(rng.normal(base_rating, 0.08), 1.0, 5.0)), 2
            )

            rec = {
                "month": ym,
                "platform": plat,
                "claimed_earnings_inr": claimed_amt,
                "bank_verified_credit_inr": verified_amt,
                "trips_or_orders_completed": orders,
                "active_days": active_days,
                "platform_rating": rating,
            }
            records.append(rec)
            if tamper_suspicious and idx == len(months_list) - 2 and p_idx == 0:
                # Inject duplicate transaction record
                records.append(dict(rec))

    declared_tenure = 36 if tamper_suspicious else tenure_months
    return records, declared_tenure, chosen_platforms


def generate_synthetic_dataset(
    n_workers: int = 20000,
    seed: int = 42,
    output_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Generate 20,000 synthetic gig workers with 8 features, audit metadata, and ~12% default rate.

    Uses vectorized simulation calibrated to the exact feature definitions so 20,000 workers
    can be generated reproducibly in <2 seconds.
    """
    rng = np.random.default_rng(seed)

    persona_keys = list(PERSONAS.keys())
    persona_weights = [PERSONAS[k]["weight"] for k in persona_keys]
    chosen_personas = rng.choice(persona_keys, size=n_workers, p=persona_weights)

    city_tiers = rng.choice(CITY_TIERS, size=n_workers, p=CITY_TIER_WEIGHTS)
    audit_genders = rng.choice(AUDIT_GENDERS, size=n_workers, p=AUDIT_GENDER_WEIGHTS)

    rows: List[Dict[str, Any]] = []

    for i in range(n_workers):
        p_key = str(chosen_personas[i])
        p_cfg = PERSONAS[p_key]

        tenure_months = float(
            rng.integers(p_cfg["tenure_range"][0], p_cfg["tenure_range"][1] + 1)
        )
        platform_count = float(rng.choice(p_cfg["platform_count_choices"]))
        primary_platform = str(rng.choice(PLATFORMS))
        platform_type = PLATFORM_TYPE_MAP[primary_platform]

        # City-tier slight income adjustment (realistic regional cost-of-living factor)
        city_tier = str(city_tiers[i])
        city_mult = (
            1.10 if city_tier == "Tier-1" else (0.96 if city_tier == "Tier-2" else 0.85)
        )

        base_earn = float(
            rng.uniform(p_cfg["base_income_range"][0], p_cfg["base_income_range"][1])
        )
        avg_monthly_earnings = round(base_earn * city_mult, 2)

        earnings_cv = round(
            float(
                np.clip(
                    rng.uniform(
                        p_cfg["volatility_range"][0], p_cfg["volatility_range"][1]
                    )
                    + rng.normal(0.0, 0.03),
                    0.03,
                    1.80,
                )
            ),
            4,
        )

        earnings_trend_6m = round(
            float(
                np.clip(
                    rng.uniform(p_cfg["trend_range"][0], p_cfg["trend_range"][1])
                    + rng.normal(0.0, 0.04),
                    -0.85,
                    0.85,
                )
            ),
            4,
        )

        income_gap_months = float(
            rng.binomial(int(tenure_months), p_cfg["gap_prob"])
        )

        avg_rating = round(
            float(
                np.clip(
                    rng.uniform(p_cfg["rating_range"][0], p_cfg["rating_range"][1])
                    + rng.normal(0.0, 0.05),
                    2.5,
                    5.0,
                )
            ),
            3,
        )

        # Peak ratio correlates inversely with volatility and positively with trend
        raw_peak_ratio = (
            1.0 / (1.0 + 0.65 * earnings_cv)
            + 0.18 * earnings_trend_6m
            + float(rng.normal(0.0, 0.04))
        )
        earnings_to_peak_ratio = round(float(np.clip(raw_peak_ratio, 0.18, 0.99)), 4)

        feat_dict = {
            "tenure_months": tenure_months,
            "avg_monthly_earnings": avg_monthly_earnings,
            "earnings_cv": earnings_cv,
            "earnings_trend_6m": earnings_trend_6m,
            "income_gap_months": income_gap_months,
            "platform_count": platform_count,
            "avg_rating": avg_rating,
            "earnings_to_peak_ratio": earnings_to_peak_ratio,
        }

        log_odds = _hidden_default_log_odds(feat_dict)
        prob_default = 1.0 / (1.0 + math.exp(-log_odds))
        default_12m = int(rng.random() < prob_default)

        rows.append(
            {
                "worker_uid": f"SYN_W_{i + 1:05d}",
                "persona": p_key,
                "city_tier": city_tier,
                "primary_platform": primary_platform,
                "platform_type": platform_type,
                "audit_gender": str(audit_genders[i]),  # Audit-only, never a feature
                **feat_dict,
                "default_12m": default_12m,
            }
        )

    df = pd.DataFrame(rows)

    if output_dir is None:
        output_dir = Path(__file__).resolve().parents[2] / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "synthetic_workers_20k.csv"
    df.to_csv(csv_path, index=False)

    summary = {
        "disclaimer": "Prototype - synthetic data only. Not for real lending decisions.",
        "n_workers": len(df),
        "default_rate": round(float(df["default_12m"].mean()), 4),
        "persona_counts": df["persona"].value_counts().to_dict(),
        "city_tier_counts": df["city_tier"].value_counts().to_dict(),
        "platform_type_counts": df["platform_type"].value_counts().to_dict(),
        "feature_columns": FEATURE_COLUMNS,
    }
    with open(output_dir / "synthetic_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return df


if __name__ == "__main__":
    dataset = generate_synthetic_dataset()
    print(
        f"Generated {len(dataset)} synthetic workers. Default rate: {dataset['default_12m'].mean():.2%}"
    )

