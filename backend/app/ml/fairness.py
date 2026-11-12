"""Synthetic Fairness Audit across City Tier, Platform Type, and Audit-Only Gender.

Prototype - synthetic data only. Not for real lending decisions.
"""
from typing import Any, Dict, List
import numpy as np
import pandas as pd

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT

ILLUSTRATIVE_APPROVAL_THRESHOLD = 650


def _evaluate_group_dimension(
    df: pd.DataFrame,
    group_col: str,
    score_col: str = "gig_score",
    threshold: int = ILLUSTRATIVE_APPROVAL_THRESHOLD,
) -> Dict[str, Any]:
    """Compute group sample size, average score, approval rate, and disparate impact ratio."""
    groups_summary: List[Dict[str, Any]] = []
    approval_rates: Dict[str, float] = {}

    for group_val, sub in df.groupby(group_col):
        n = int(len(sub))
        if n == 0:
            continue
        avg_score = round(float(sub[score_col].mean()), 2)
        approved = float((sub[score_col] >= threshold).mean())
        approval_rates[str(group_val)] = approved
        groups_summary.append(
            {
                "group": str(group_val),
                "sample_size": n,
                "average_score": avg_score,
                "approval_rate_at_650": round(approved, 4),
            }
        )

    max_approval = max(approval_rates.values()) if approval_rates else 1.0
    min_dir = 1.0
    for item in groups_summary:
        rate = item["approval_rate_at_650"]
        dir_val = round(rate / max_approval, 4) if max_approval > 1e-6 else 1.0
        item["disparate_impact_ratio"] = dir_val
        if dir_val < min_dir:
            min_dir = dir_val

    return {
        "dimension": group_col,
        "reference_max_approval_rate": round(max_approval, 4),
        "min_disparate_impact_ratio": round(min_dir, 4),
        "passes_four_fifths_guideline": bool(min_dir >= 0.80),
        "groups": groups_summary,
    }


def run_synthetic_fairness_audit(
    eval_df: pd.DataFrame,
    scores: np.ndarray,
    threshold: int = ILLUSTRATIVE_APPROVAL_THRESHOLD,
) -> Dict[str, Any]:
    """Run fairness diagnostics across city_tier, platform_type, and audit_gender.

    IMPORTANT:
    - audit_gender is strictly an audit-only column and is NEVER used as a model feature.
    - All outputs are clearly labeled as synthetic fairness diagnostics.
    """
    df = eval_df.copy()
    df["gig_score"] = scores

    dimensions: Dict[str, Any] = {}
    for col in ("city_tier", "platform_type", "audit_gender"):
        if col in df.columns:
            dimensions[col] = _evaluate_group_dimension(
                df, col, score_col="gig_score", threshold=threshold
            )

    return {
        "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
        "diagnostic_notice": (
            "SYNTHETIC FAIRNESS DIAGNOSTIC ONLY: Evaluated on simulated worker profiles. "
            "Not evidence of real-world demographic fairness. Gender is strictly excluded from model features."
        ),
        "illustrative_approval_threshold": threshold,
        "total_evaluated_samples": int(len(df)),
        "overall_average_score": round(float(np.mean(scores)), 2),
        "overall_approval_rate": round(float(np.mean(scores >= threshold)), 4),
        "gender_used_as_model_feature": False,
        "dimensions": dimensions,
    }

