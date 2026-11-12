"""Transparent Rule-Based Baseline Scorecard for GigScore (300-900).

Serves both as an interpretable benchmark and as the explicit fallback engine
when the calibrated XGBoost artifact is unavailable.

Prototype - synthetic data only. Not for real lending decisions.
"""
from typing import Any, Dict, List, Tuple

from app.core.config import settings
from app.ml.features import sanitize_feature_dict
from app.schemas.score import (
    ExplainabilityFactor,
    RiskTierEnum,
    ScoreBandEnum,
    ScoringEngineEnum,
)


def map_score_to_band_and_tier(score: int) -> Tuple[str, str]:
    """Map a 300-900 GigScore to its standardized Score Band and Risk Tier."""
    if score >= 750:
        return ScoreBandEnum.EXCELLENT_750_900.value, RiskTierEnum.LOW_RISK.value
    elif score >= 650:
        return ScoreBandEnum.GOOD_650_749.value, RiskTierEnum.MODERATE_RISK.value
    elif score >= 550:
        return ScoreBandEnum.FAIR_550_649.value, RiskTierEnum.HIGH_RISK.value
    else:
        return ScoreBandEnum.POOR_300_549.value, RiskTierEnum.VERY_HIGH_RISK.value


def score_with_rule_scorecard(
    raw_features: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a worker's 8 features using the monotonic rule-based scorecard.

    Base score: 540 points.
    Additive/deductive points across all 8 features map smoothly inside [300, 900].
    Monotonicity is guaranteed across every feature via continuous piecewise-linear
    or monotonic band functions.
    """
    f = sanitize_feature_dict(raw_features)
    base_score = 540.0
    contributions: List[ExplainabilityFactor] = []

    # 1. Tenure months (0 to +90 pts; <6m deducts up to -35 pts)
    tenure = f["tenure_months"]
    if tenure >= 24:
        tenure_pts = 70.0 + min(20.0, (tenure - 24.0) * 1.2)
        tenure_desc = f"Your platform tenure of {int(tenure)} months demonstrates strong work history."
        tenure_code = "STRONG_PLATFORM_TENURE"
    elif tenure >= 12:
        tenure_pts = 30.0 + (tenure - 12.0) * (40.0 / 12.0)
        tenure_desc = f"Your active gig tenure of {int(tenure)} months shows established experience."
        tenure_code = "ESTABLISHED_TENURE"
    elif tenure >= 6:
        tenure_pts = (tenure - 6.0) * (30.0 / 6.0)
        tenure_desc = f"Your gig work history covers {int(tenure)} months; longer tenure will strengthen your score."
        tenure_code = "MODERATE_TENURE"
    else:
        tenure_pts = -35.0 + tenure * (35.0 / 6.0)
        tenure_desc = f"Your platform tenure ({int(tenure)} months) is still short."
        tenure_code = "SHORT_PLATFORM_TENURE"

    contributions.append(
        ExplainabilityFactor(
            feature_name="tenure_months",
            feature_value=tenure,
            shap_impact=round(tenure_pts / 600.0, 4),
            direction="POSITIVE" if tenure_pts >= 0 else "NEGATIVE",
            reason_code=tenure_code,
            plain_english=tenure_desc,
        )
    )

    # 2. Average monthly earnings (-60 to +110 pts)
    earnings = f["avg_monthly_earnings"]
    if earnings >= 35000.0:
        earn_pts = 85.0 + min(25.0, (earnings - 35000.0) / 1500.0)
        earn_desc = f"Your average bank-verified monthly income (₹{earnings:,.0f}) is strong."
        earn_code = "HIGH_VERIFIED_EARNINGS"
    elif earnings >= 20000.0:
        earn_pts = 25.0 + (earnings - 20000.0) * (60.0 / 15000.0)
        earn_desc = f"Your average monthly earnings (₹{earnings:,.0f}) provide steady repayment capacity."
        earn_code = "HEALTHY_MONTHLY_EARNINGS"
    elif earnings >= 12000.0:
        earn_pts = -15.0 + (earnings - 12000.0) * (40.0 / 8000.0)
        earn_desc = f"Your average monthly earnings (₹{earnings:,.0f}) are modest."
        earn_code = "MODEST_MONTHLY_EARNINGS"
    else:
        earn_pts = -60.0 + earnings * (45.0 / 12000.0)
        earn_desc = f"Your verified monthly income (₹{earnings:,.0f}) is currently low."
        earn_code = "LOW_MONTHLY_EARNINGS"

    contributions.append(
        ExplainabilityFactor(
            feature_name="avg_monthly_earnings",
            feature_value=earnings,
            shap_impact=round(earn_pts / 600.0, 4),
            direction="POSITIVE" if earn_pts >= 0 else "NEGATIVE",
            reason_code=earn_code,
            plain_english=earn_desc,
        )
    )

    # 3. Earnings CV / Volatility (+65 to -85 pts; lower CV is better)
    cv = f["earnings_cv"]
    if cv <= 0.20:
        cv_pts = 65.0 - cv * (25.0 / 0.20)
        cv_desc = "Your earnings have remained consistent over the observed history."
        cv_code = "LOW_EARNINGS_VOLATILITY"
    elif cv <= 0.45:
        cv_pts = 40.0 - (cv - 0.20) * (50.0 / 0.25)
        cv_desc = "Your month-to-month earnings show moderate, manageable variation."
        cv_code = "MODERATE_EARNINGS_VOLATILITY"
    else:
        cv_pts = -10.0 - min(75.0, (cv - 0.45) * 90.0)
        cv_desc = "Your monthly income fluctuates significantly between months."
        cv_code = "HIGH_EARNINGS_VOLATILITY"

    contributions.append(
        ExplainabilityFactor(
            feature_name="earnings_cv",
            feature_value=cv,
            shap_impact=round(cv_pts / 600.0, 4),
            direction="POSITIVE" if cv_pts >= 0 else "NEGATIVE",
            reason_code=cv_code,
            plain_english=cv_desc,
        )
    )

    # 4. 6-month earnings trend (-55 to +50 pts)
    trend = f["earnings_trend_6m"]
    trend_pts = trend * 50.0 if trend >= 0 else trend * 55.0
    if trend >= 0.05:
        trend_desc = "Your recent 6-month earnings show an upward growth trend."
        trend_code = "POSITIVE_EARNINGS_TREND"
    elif trend >= -0.05:
        trend_desc = "Your recent 6-month earnings trajectory is stable."
        trend_code = "STABLE_EARNINGS_TREND"
    else:
        trend_desc = "Your recent earnings show a declining trend over the last 6 months."
        trend_code = "DECLINING_EARNINGS_TREND"

    contributions.append(
        ExplainabilityFactor(
            feature_name="earnings_trend_6m",
            feature_value=trend,
            shap_impact=round(trend_pts / 600.0, 4),
            direction="POSITIVE" if trend_pts >= 0 else "NEGATIVE",
            reason_code=trend_code,
            plain_english=trend_desc,
        )
    )

    # 5. Income gap months (+25 to -75 pts; fewer gaps is better)
    gaps = f["income_gap_months"]
    if gaps == 0:
        gap_pts = 25.0
        gap_desc = "You have zero inactive or income-gap months in your history."
        gap_code = "NO_INCOME_GAPS"
    elif gaps <= 2:
        gap_pts = 10.0 - gaps * 12.0
        gap_desc = f"You have {int(gaps)} month(s) with minimal or paused gig income."
        gap_code = "MINOR_INCOME_GAPS"
    else:
        gap_pts = -14.0 - min(61.0, (gaps - 2.0) * 15.0)
        gap_desc = f"You have {int(gaps)} months with income gaps, which lowers repayment predictability."
        gap_code = "FREQUENT_INCOME_GAPS"

    contributions.append(
        ExplainabilityFactor(
            feature_name="income_gap_months",
            feature_value=gaps,
            shap_impact=round(gap_pts / 600.0, 4),
            direction="POSITIVE" if gap_pts >= 0 else "NEGATIVE",
            reason_code=gap_code,
            plain_english=gap_desc,
        )
    )

    # 6. Platform count (-15 to +40 pts)
    platforms = f["platform_count"]
    if platforms >= 3:
        plat_pts = 30.0 + min(10.0, (platforms - 3.0) * 5.0)
        plat_desc = "You have multiple active income sources across 3+ gig platforms."
        plat_code = "MULTI_PLATFORM_DIVERSIFICATION"
    elif platforms >= 2:
        plat_pts = 18.0 + (platforms - 2.0) * 12.0
        plat_desc = "You diversify your earnings across 2 active gig platforms."
        plat_code = "DUAL_PLATFORM_INCOME"
    elif platforms >= 1:
        plat_pts = 0.0 + (platforms - 1.0) * 18.0
        plat_desc = "Your gig income currently relies on a single platform."
        plat_code = "SINGLE_PLATFORM_DEPENDENCY"
    else:
        plat_pts = -15.0
        plat_desc = "No active gig platform payouts were detected."
        plat_code = "NO_ACTIVE_PLATFORMS"

    contributions.append(
        ExplainabilityFactor(
            feature_name="platform_count",
            feature_value=platforms,
            shap_impact=round(plat_pts / 600.0, 4),
            direction="POSITIVE" if plat_pts >= 0 else "NEGATIVE",
            reason_code=plat_code,
            plain_english=plat_desc,
        )
    )

    # 7. Average platform rating (-35 to +35 pts)
    rating = f["avg_rating"]
    if rating >= 4.5:
        rat_pts = 15.0 + (rating - 4.5) * 40.0
        rat_desc = f"Your high customer rating ({rating:.2f}/5.0) indicates strong service reliability."
        rat_code = "HIGH_CUSTOMER_RATING"
    elif rating >= 4.0:
        rat_pts = -10.0 + (rating - 4.0) * 50.0
        rat_desc = f"Your platform rating ({rating:.2f}/5.0) meets standard service benchmarks."
        rat_code = "ACCEPTABLE_CUSTOMER_RATING"
    else:
        rat_pts = -10.0 - min(25.0, (4.0 - rating) * 25.0)
        rat_desc = f"Your platform rating ({rating:.2f}/5.0) is below the 4.0 benchmark."
        rat_code = "LOW_CUSTOMER_RATING"

    contributions.append(
        ExplainabilityFactor(
            feature_name="avg_rating",
            feature_value=rating,
            shap_impact=round(rat_pts / 600.0, 4),
            direction="POSITIVE" if rat_pts >= 0 else "NEGATIVE",
            reason_code=rat_code,
            plain_english=rat_desc,
        )
    )

    # 8. Earnings to peak ratio (-30 to +35 pts)
    peak_ratio = f["earnings_to_peak_ratio"]
    if peak_ratio >= 0.75:
        pk_pts = 15.0 + (peak_ratio - 0.75) * 80.0
        pk_desc = "Your recent earnings are close to your historical peak performance."
        pk_code = "NEAR_PEAK_EARNINGS"
    elif peak_ratio >= 0.50:
        pk_pts = -10.0 + (peak_ratio - 0.50) * 100.0
        pk_desc = "Your recent earnings are at a moderate level relative to your peak month."
        pk_code = "MODERATE_PEAK_RETENTION"
    else:
        pk_pts = -30.0 + peak_ratio * 40.0
        pk_desc = "Your current earnings have dropped significantly below your historical peak."
        pk_code = "BELOW_PEAK_EARNINGS"

    contributions.append(
        ExplainabilityFactor(
            feature_name="earnings_to_peak_ratio",
            feature_value=peak_ratio,
            shap_impact=round(pk_pts / 600.0, 4),
            direction="POSITIVE" if pk_pts >= 0 else "NEGATIVE",
            reason_code=pk_code,
            plain_english=pk_desc,
        )
    )

    raw_total = (
        base_score
        + tenure_pts
        + earn_pts
        + cv_pts
        + trend_pts
        + gap_pts
        + plat_pts
        + rat_pts
        + pk_pts
    )
    gig_score = int(max(300, min(900, round(raw_total))))
    # Invert gig_score = round(900 - 600 * p) -> p = (900 - gig_score) / 600
    calibrated_default_prob = round(
        max(0.001, min(0.999, (900.0 - gig_score) / 600.0)), 4
    )
    score_band, risk_tier = map_score_to_band_and_tier(gig_score)

    # Sort contributions by magnitude of impact
    sorted_factors = sorted(
        contributions, key=lambda x: abs(x.shap_impact), reverse=True
    )
    reason_codes = [c.reason_code for c in sorted_factors[:4]]

    return {
        "gig_score": gig_score,
        "calibrated_default_probability": calibrated_default_prob,
        "calibrated_probability": round(1.0 - calibrated_default_prob, 4),
        "score_band": score_band,
        "risk_tier": risk_tier,
        "top_factors": sorted_factors[:6],
        "reason_codes": reason_codes,
        "model_version": settings.FALLBACK_MODEL_VERSION,
        "scoring_engine": ScoringEngineEnum.RULE_SCORECARD.value,
    }

