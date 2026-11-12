"""SHAP TreeExplainer and plain-English explanation generator for GigScore.

Prototype - synthetic data only. Not for real lending decisions.
"""
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import shap

from app.ml.features import FEATURE_COLUMNS, sanitize_feature_dict
from app.schemas.score import ExplainabilityFactor


def _feature_to_plain_english(
    feature_name: str,
    feature_value: float,
    credit_impact: float,
) -> Tuple[str, str]:
    """Translate a feature value and its creditworthiness impact into a reason code and sentence.

    Note: credit_impact > 0 means the feature improved the GigScore (lowered default probability).
    """
    is_pos = credit_impact >= 0

    if feature_name == "tenure_months":
        months = int(round(feature_value))
        if is_pos:
            return (
                "STRONG_PLATFORM_TENURE",
                f"Your active platform tenure of {months} months shows established work stability.",
            )
        return (
            "LIMITED_PLATFORM_TENURE",
            f"Your platform history ({months} months) is relatively short.",
        )

    if feature_name == "avg_monthly_earnings":
        if is_pos:
            return (
                "STRONG_VERIFIED_INCOME",
                f"Your average bank-verified monthly income of ₹{feature_value:,.0f} supports strong repayment capacity.",
            )
        return (
            "MODEST_VERIFIED_INCOME",
            f"Your average monthly bank-verified earnings (₹{feature_value:,.0f}) limit current credit capacity.",
        )

    if feature_name == "earnings_cv":
        if is_pos:
            return (
                "CONSISTENT_MONTHLY_EARNINGS",
                "Your earnings have remained consistent over the last 12 months.",
            )
        return (
            "VOLATILE_MONTHLY_EARNINGS",
            "Your month-to-month earnings show high variability.",
        )

    if feature_name == "earnings_trend_6m":
        if is_pos:
            return (
                "POSITIVE_EARNINGS_TRAJECTORY",
                "Your recent 6-month earnings show a stable or upward growth trend.",
            )
        return (
            "DECLINING_EARNINGS_TRAJECTORY",
            "Your recent earnings show a declining trend.",
        )

    if feature_name == "income_gap_months":
        gaps = int(round(feature_value))
        if is_pos:
            return (
                "CONTINUOUS_EARNING_MONTHS",
                "You have maintained continuous active earning months with minimal gaps.",
            )
        return (
            "INCOME_GAP_MONTHS_DETECTED",
            f"You had {gaps} month(s) with low or paused platform payouts.",
        )

    if feature_name == "platform_count":
        count = int(round(feature_value))
        if is_pos and count >= 2:
            return (
                "MULTI_PLATFORM_INCOME",
                "You have multiple active income sources.",
            )
        if is_pos:
            return (
                "ACTIVE_PLATFORM_SOURCE",
                "You have an active verified gig platform income stream.",
            )
        return (
            "SINGLE_PLATFORM_CONCENTRATION",
            "Relying on a single gig platform increases income concentration risk.",
        )

    if feature_name == "avg_rating":
        if is_pos:
            return (
                "HIGH_SERVICE_RATING",
                f"Your strong platform rating ({feature_value:.2f}/5.0) reflects consistent service quality.",
            )
        return (
            "BELOW_BENCHMARK_RATING",
            f"Improving your platform rating ({feature_value:.2f}/5.0) above 4.5 can boost your score.",
        )

    if feature_name == "earnings_to_peak_ratio":
        if is_pos:
            return (
                "STRONG_PEAK_RETENTION",
                "Your recent earnings remain close to your historical peak monthly income.",
            )
        return (
            "DROP_FROM_PEAK_EARNINGS",
            "Your recent monthly income is significantly lower than your historical peak.",
        )

    return (
        "BEHAVIORAL_FACTOR",
        f"Behavioral metric {feature_name} contributed to your credit assessment.",
    )


def generate_improvement_tips(raw_features: Dict[str, Any]) -> List[str]:
    """Generate personalized, actionable score improvement recommendations for the worker dashboard."""
    f = sanitize_feature_dict(raw_features)
    tips: List[str] = []

    if f["platform_count"] < 2:
        tips.append(
            "Connect a secondary gig platform (e.g., pairing Swiggy with Zomato or Uber) to diversify your income sources."
        )
    if f["earnings_cv"] > 0.30:
        tips.append(
            "Aim for steadier weekly working hours to reduce month-to-month income volatility."
        )
    if f["income_gap_months"] >= 1:
        tips.append(
            "Maintain at least minimal active payouts every calendar month to avoid income gap deductions."
        )
    if f["earnings_trend_6m"] < 0:
        tips.append(
            "Stabilize or grow your monthly payouts over the next 3 months to reverse the recent declining trend."
        )
    if f["avg_rating"] < 4.5:
        tips.append(
            "Sustaining a customer rating of 4.6+ across platforms positively impacts your GigScore."
        )
    if f["tenure_months"] < 12:
        tips.append(
            "Continue building verified platform history—crossing 12 months of active tenure unlocks a higher stability tier."
        )

    if not tips:
        tips.append(
            "Keep maintaining your consistent multi-platform earnings and zero gap months to preserve your top-tier score."
        )

    return tips[:4]


class ShapExplanationEngine:
    """Wraps SHAP TreeExplainer to produce structured, human-readable explanations without raw SHAP arrays."""

    def __init__(self, xgb_estimator: Any) -> None:
        self.xgb_estimator = xgb_estimator
        self.explainer = shap.TreeExplainer(xgb_estimator)

    def explain_features(
        self, raw_features: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute SHAP contributions and return top 3 positive, top 3 negative, and combined top factors."""
        f = sanitize_feature_dict(raw_features)
        x_arr = np.array([[f[col] for col in FEATURE_COLUMNS]], dtype=float)
        shap_vals = self.explainer.shap_values(x_arr)

        if isinstance(shap_vals, list):
            row_shap = np.asarray(shap_vals[-1])[0]
        else:
            arr = np.asarray(shap_vals)
            row_shap = arr[0] if arr.ndim == 2 else arr

        # Note: XGBoost predicts default (y=1). A negative SHAP value on default means
        # the feature REDUCED default probability -> POSITIVE impact on GigScore!
        factors: List[ExplainabilityFactor] = []
        for idx, col in enumerate(FEATURE_COLUMNS):
            default_shap = float(row_shap[idx])
            credit_impact = round(-default_shap, 4)
            direction = "POSITIVE" if credit_impact >= 0 else "NEGATIVE"
            code, sentence = _feature_to_plain_english(
                col, f[col], credit_impact
            )
            factors.append(
                ExplainabilityFactor(
                    feature_name=col,
                    feature_value=round(float(f[col]), 4),
                    shap_impact=credit_impact,
                    direction=direction,
                    reason_code=code,
                    plain_english=sentence,
                )
            )

        positive_factors = sorted(
            [fac for fac in factors if fac.shap_impact > 0],
            key=lambda item: item.shap_impact,
            reverse=True,
        )[:3]

        negative_factors = sorted(
            [fac for fac in factors if fac.shap_impact < 0],
            key=lambda item: abs(item.shap_impact),
            reverse=True,
        )[:3]

        # Interleave or rank by absolute magnitude while preserving up to 3 positive + 3 negative
        combined = sorted(
            positive_factors + negative_factors,
            key=lambda item: abs(item.shap_impact),
            reverse=True,
        )
        reason_codes = [fac.reason_code for fac in combined[:4]]

        return {
            "top_positive_factors": positive_factors,
            "top_negative_factors": negative_factors,
            "top_factors": combined,
            "reason_codes": reason_codes,
            "improvement_tips": generate_improvement_tips(f),
        }

