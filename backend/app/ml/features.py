"""Feature engineering module for GigScore credit-scoring pipeline.

Prototype - synthetic data only. Not for real lending decisions.
"""
from typing import Any, Dict, Iterable, List, Optional
import math
import numpy as np
import pandas as pd

FEATURE_COLUMNS: List[str] = [
    "tenure_months",
    "avg_monthly_earnings",
    "earnings_cv",
    "earnings_trend_6m",
    "income_gap_months",
    "platform_count",
    "avg_rating",
    "earnings_to_peak_ratio",
]

# Monotonic constraints with respect to default probability (1 = default):
# -1 means increasing the feature decreases default risk (increases GigScore)
# +1 means increasing the feature increases default risk (decreases GigScore)
MONOTONE_CONSTRAINTS_TUPLE = (-1, -1, 1, -1, 1, -1, -1, -1)

DEFAULT_FEATURE_IMPUTATION: Dict[str, float] = {
    "tenure_months": 1.0,
    "avg_monthly_earnings": 0.0,
    "earnings_cv": 1.0,
    "earnings_trend_6m": 0.0,
    "income_gap_months": 0.0,
    "platform_count": 1.0,
    "avg_rating": 4.2,
    "earnings_to_peak_ratio": 0.5,
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert value to a finite float or return default."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def compute_worker_features(
    monthly_records: Optional[Iterable[Dict[str, Any]]],
    declared_tenure_months: Optional[int] = None,
) -> Dict[str, float]:
    """Compute the 8 canonical GigScore features from monthly platform earnings records.

    Handles missing values, empty lists, zero-earning months, and short histories safely.
    """
    records = list(monthly_records or [])
    if not records:
        base = dict(DEFAULT_FEATURE_IMPUTATION)
        if declared_tenure_months is not None and declared_tenure_months > 0:
            base["tenure_months"] = float(declared_tenure_months)
        return base

    # Group by month (YYYY-MM) to aggregate across multiple platforms per month
    monthly_totals: Dict[str, float] = {}
    platforms_seen: set[str] = set()
    ratings: List[float] = []

    for rec in records:
        if not isinstance(rec, dict):
            # Support Pydantic model instances as well
            rec = rec.model_dump() if hasattr(rec, "model_dump") else dict(rec)

        month_key = str(rec.get("month") or "0000-00").strip()
        platform = str(rec.get("platform") or "").strip()

        # Prefer bank_verified_credit_inr; fallback to claimed_earnings_inr or earnings
        verified = rec.get("bank_verified_credit_inr")
        if verified is None:
            verified = rec.get("claimed_earnings_inr", rec.get("earnings_inr", 0.0))
        amount = max(0.0, _safe_float(verified, 0.0))

        monthly_totals[month_key] = monthly_totals.get(month_key, 0.0) + amount

        if platform and amount > 0:
            platforms_seen.add(platform)

        rating_val = rec.get("platform_rating")
        if rating_val is not None:
            r = _safe_float(rating_val, -1.0)
            if 1.0 <= r <= 5.0:
                ratings.append(r)

    sorted_months = sorted(monthly_totals.keys())
    chronological_earnings = [monthly_totals[m] for m in sorted_months]
    n_observed_months = len(chronological_earnings)

    # 1. tenure_months
    if declared_tenure_months is not None and declared_tenure_months > 0:
        tenure_months = float(max(declared_tenure_months, n_observed_months))
    else:
        tenure_months = float(max(1, n_observed_months))

    # 2. avg_monthly_earnings
    earnings_arr = np.array(chronological_earnings, dtype=float)
    avg_monthly_earnings = float(np.mean(earnings_arr)) if len(earnings_arr) > 0 else 0.0

    # 3. earnings_cv (Coefficient of variation = std / mean, bounded [0.0, 2.5])
    if len(earnings_arr) >= 2 and avg_monthly_earnings > 1e-6:
        std_earnings = float(np.std(earnings_arr, ddof=0))
        earnings_cv = min(2.5, max(0.0, std_earnings / avg_monthly_earnings))
    elif avg_monthly_earnings <= 1e-6:
        earnings_cv = 1.5
    else:
        earnings_cv = 0.35  # Default moderate uncertainty for 1 month of history

    # 4. earnings_trend_6m (Normalized slope over up to the last 6 months, bounded [-1.0, 1.0])
    recent_window = earnings_arr[-6:] if len(earnings_arr) >= 2 else earnings_arr
    if len(recent_window) >= 2 and np.mean(recent_window) > 1e-6:
        x = np.arange(len(recent_window), dtype=float)
        slope = float(np.polyfit(x, recent_window, 1)[0])
        # Relative monthly change scaled over the window
        rel_trend = (slope * len(recent_window)) / float(np.mean(recent_window))
        earnings_trend_6m = float(np.clip(rel_trend, -1.0, 1.0))
    else:
        earnings_trend_6m = 0.0

    # 5. income_gap_months (Months with < ₹1,000 verified income or missing calendar months)
    low_income_months = int(np.sum(earnings_arr < 1000.0))
    # Also check calendar gaps if YYYY-MM format is valid
    calendar_span_gaps = 0
    try:
        valid_ym = [
            (int(m.split("-")[0]), int(m.split("-")[1]))
            for m in sorted_months
            if len(m.split("-")) == 2 and m.split("-")[0].isdigit() and m.split("-")[1].isdigit()
        ]
        if len(valid_ym) >= 2 and valid_ym[0][0] > 1990:
            first_y, first_m = valid_ym[0]
            last_y, last_m = valid_ym[-1]
            expected_span = (last_y - first_y) * 12 + (last_m - first_m) + 1
            if expected_span > len(valid_ym):
                calendar_span_gaps = expected_span - len(valid_ym)
    except Exception:
        calendar_span_gaps = 0

    income_gap_months = float(min(36, low_income_months + calendar_span_gaps))

    # 6. platform_count
    platform_count = float(max(1, len(platforms_seen))) if avg_monthly_earnings > 0 else 0.0

    # 7. avg_rating
    if ratings:
        avg_rating = float(np.clip(np.mean(ratings), 1.0, 5.0))
    else:
        avg_rating = DEFAULT_FEATURE_IMPUTATION["avg_rating"]

    # 8. earnings_to_peak_ratio (avg_monthly_earnings / peak_monthly_earnings, in [0.0, 1.0])
    peak_earnings = float(np.max(earnings_arr)) if len(earnings_arr) > 0 else 0.0
    if peak_earnings > 1e-6:
        # Compare recent 3-month average (or overall average) to peak
        recent_avg = float(np.mean(earnings_arr[-3:]))
        earnings_to_peak_ratio = float(np.clip(recent_avg / peak_earnings, 0.0, 1.0))
    else:
        earnings_to_peak_ratio = 0.0

    return {
        "tenure_months": round(tenure_months, 2),
        "avg_monthly_earnings": round(avg_monthly_earnings, 2),
        "earnings_cv": round(earnings_cv, 4),
        "earnings_trend_6m": round(earnings_trend_6m, 4),
        "income_gap_months": round(income_gap_months, 2),
        "platform_count": round(platform_count, 2),
        "avg_rating": round(avg_rating, 3),
        "earnings_to_peak_ratio": round(earnings_to_peak_ratio, 4),
    }


def sanitize_feature_dict(raw_features: Dict[str, Any]) -> Dict[str, float]:
    """Ensure all 8 canonical features are present, finite, and within sensible bounds."""
    cleaned: Dict[str, float] = {}
    for col in FEATURE_COLUMNS:
        default_val = DEFAULT_FEATURE_IMPUTATION[col]
        val = _safe_float(raw_features.get(col), default_val)
        if col == "tenure_months":
            val = max(0.0, min(120.0, val))
        elif col == "avg_monthly_earnings":
            val = max(0.0, min(500000.0, val))
        elif col == "earnings_cv":
            val = max(0.0, min(2.5, val))
        elif col == "earnings_trend_6m":
            val = max(-1.0, min(1.0, val))
        elif col == "income_gap_months":
            val = max(0.0, min(36.0, val))
        elif col == "platform_count":
            val = max(0.0, min(10.0, val))
        elif col == "avg_rating":
            val = max(1.0, min(5.0, val))
        elif col == "earnings_to_peak_ratio":
            val = max(0.0, min(1.0, val))
        cleaned[col] = val
    return cleaned


def features_to_dataframe(
    feature_dicts: List[Dict[str, Any]],
) -> pd.DataFrame:
    """Convert a list of feature dictionaries into a clean pandas DataFrame with exact column order."""
    rows = [sanitize_feature_dict(d) for d in feature_dicts]
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)

