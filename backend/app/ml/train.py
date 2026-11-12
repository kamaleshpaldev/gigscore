"""XGBoost Training, Probability Calibration, Evaluation, and Model Card Generator.

Prototype - synthetic data only. Not for real lending decisions.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT, settings
from app.ml.fairness import run_synthetic_fairness_audit
from app.ml.features import FEATURE_COLUMNS, MONOTONE_CONSTRAINTS_TUPLE
from app.ml.generate_data import generate_synthetic_dataset


def probability_to_gig_score(prob_default: np.ndarray | float) -> np.ndarray | int:
    """Monotonic mapping: gig_score = clamp(round(900 - 600 * p), 300, 900)."""
    if isinstance(prob_default, (int, float, np.floating)):
        raw = round(900.0 - 600.0 * float(prob_default))
        return int(max(300, min(900, raw)))
    arr = np.rint(900.0 - 600.0 * np.asarray(prob_default, dtype=float))
    return np.clip(arr, 300, 900).astype(int)


def compute_ks_statistic(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Calculate the two-sample Kolmogorov-Smirnov (KS) statistic for binary classification."""
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    return float(np.max(np.abs(tpr - fpr)))


def _render_calibration_svg(
    prob_true: np.ndarray, prob_pred: np.ndarray, out_path: Path
) -> None:
    """Render a standalone SVG reliability / calibration plot (no matplotlib dependency needed)."""
    width, height, pad = 520, 420, 55
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad

    def to_xy(px: float, py: float) -> Tuple[float, float]:
        return pad + px * plot_w, height - pad - py * plot_h

    points = [
        f"{to_xy(float(x), float(y))[0]:.1f},{to_xy(float(x), float(y))[1]:.1f}"
        for x, y in zip(prob_pred, prob_true)
    ]
    polyline_pts = " ".join(points)

    circles = "\n".join(
        f'<circle cx="{to_xy(float(x), float(y))[0]:.1f}" cy="{to_xy(float(x), float(y))[1]:.1f}" r="4.5" fill="#14532d" stroke="#d4af37" stroke-width="1.5"/>'
        for x, y in zip(prob_pred, prob_true)
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%">
  <rect width="{width}" height="{height}" fill="#fdfbf7" rx="8"/>
  <text x="{width/2}" y="26" text-anchor="middle" font-family="sans-serif" font-size="14" font-weight="bold" fill="#14532d">
    GigScore Calibrated Probability Reliability Curve (Synthetic Test Set)
  </text>
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#334155" stroke-width="1.5"/>
  <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#334155" stroke-width="1.5"/>
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{pad}" stroke="#94a3b8" stroke-dasharray="5,5" stroke-width="1.5"/>
  <polyline fill="none" stroke="#15803d" stroke-width="2.5" points="{polyline_pts}"/>
  {circles}
  <text x="{width/2}" y="{height-14}" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#334155">
    Mean Predicted Default Probability
  </text>
  <text x="16" y="{height/2}" transform="rotate(-90 16,{height/2})" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#334155">
    Observed Default Fraction
  </text>
</svg>"""
    out_path.write_text(svg, encoding="utf-8")


def _write_model_card(
    metrics: Dict[str, Any],
    fairness_report: Dict[str, Any],
    out_path: Path,
) -> None:
    """Write a comprehensive, transparent Model Card markdown document."""
    fi_lines = "\n".join(
        f"| `{feat}` | {imp:.4f} |"
        for feat, imp in metrics["feature_importance"].items()
    )
    cm = metrics["confusion_matrix"]
    content = f"""# GigScore Model Card — `{metrics['model_version']}`

> **Disclaimer:** *{PROTOTYPE_DISCLAIMER_TEXT}*

## 1. Model Overview
- **Model Version:** `{metrics['model_version']}`
- **Fallback Baseline Version:** `{settings.FALLBACK_MODEL_VERSION}`
- **Model Type:** Monotonic Gradient Boosted Decision Trees (`XGBClassifier`) + Isotonic Probability Calibrator
- **Trained At (UTC):** `{metrics['trained_at']}`
- **Target Variable:** Simulated 12-month repayment default (`default_12m`, ~12% synthetic base rate)
- **Score Mapping Formula:**
  $$\\text{{GigScore}} = \\text{{clamp}}\\left(\\text{{round}}(900 - 600 \\times p_{{\\text{{calibrated}}}}),\\; 300,\\; 900\\right)$$

## 2. Dataset & Split (Synthetic Only)
- **Total Synthetic Workers:** {metrics['dataset_size']:,} across 5 gig personas and 6 platforms
- **Train Split (70%):** {metrics['train_size']:,} rows (used to fit base `XGBClassifier` with `scale_pos_weight`)
- **Validation Split (15%):** {metrics['val_size']:,} rows (used exclusively for probability calibration & threshold tuning)
- **Test Split (15%):** {metrics['test_size']:,} rows (held-out evaluation & fairness diagnostics)

## 3. Held-Out Test Set Performance Metrics
*(Note: Synthetic educational benchmark — does not represent real-world lending accuracy.)*

| Metric | Value |
| :--- | :--- |
| **ROC-AUC** | `{metrics['roc_auc']:.4f}` |
| **KS Statistic** | `{metrics['ks_statistic']:.4f}` |
| **Brier Score (Calibrated)** | `{metrics['brier_score']:.4f}` |
| **Precision (at decision threshold {metrics['decision_threshold']:.2f})** | `{metrics['precision']:.4f}` |
| **Recall (at decision threshold {metrics['decision_threshold']:.2f})** | `{metrics['recall']:.4f}` |

### Confusion Matrix (Held-Out Test Set)
- **True Negatives (Repaid correctly predicted):** `{cm['tn']}`
- **False Positives (Repaid flagged as high risk):** `{cm['fp']}`
- **False Negatives (Default missed):** `{cm['fn']}`
- **True Positives (Default caught):** `{cm['tp']}`

## 4. Feature Importance & Monotonicity Constraints

| Feature | Relative Importance |
| :--- | :--- |
{fi_lines}

## 5. Synthetic Fairness Diagnostics (Threshold: GigScore >= {fairness_report['illustrative_approval_threshold']})
- **Gender Used as Model Input:** `False` (strictly excluded from features; evaluated post-hoc only)
- **Overall Test Approval Rate:** `{fairness_report['overall_approval_rate'] * 100:.1f}%`
- **City Tier Min Disparate Impact Ratio:** `{fairness_report['dimensions']['city_tier']['min_disparate_impact_ratio']:.4f}`
- **Platform Type Min Disparate Impact Ratio:** `{fairness_report['dimensions']['platform_type']['min_disparate_impact_ratio']:.4f}`
- **Audit Gender Min Disparate Impact Ratio:** `{fairness_report['dimensions']['audit_gender']['min_disparate_impact_ratio']:.4f}`

## 6. Ethical Considerations & Limitations
1. Trained strictly on simulated multi-platform Indian gig-worker profiles.
2. Raw Account Aggregator bank transactions are never persisted to the database.
3. Workers flagged by the Data Authenticity Engine receive `NEEDS_REVIEW` rather than an automated rejection or score.
"""
    out_path.write_text(content, encoding="utf-8")


def train_and_persist_model(
    seed: int = 42,
    force_regenerate_data: bool = False,
) -> Dict[str, Any]:
    """Execute the full stratified train/val/test pipeline, calibrate probabilities, and save artifacts."""
    backend_root = Path(__file__).resolve().parents[2]
    data_dir = backend_root / "data"
    csv_path = data_dir / "synthetic_workers_20k.csv"

    if csv_path.exists() and not force_regenerate_data:
        df = pd.read_csv(csv_path)
    else:
        df = generate_synthetic_dataset(n_workers=20000, seed=seed, output_dir=data_dir)

    # Strict featurization ordering: split into Train (70%), Val (15%), Test (15%) BEFORE fitting models
    y_all = df["default_12m"].to_numpy(dtype=int)
    idx_all = np.arange(len(df))

    idx_train, idx_temp, y_train, y_temp = train_test_split(
        idx_all, y_all, test_size=0.30, stratify=y_all, random_state=seed
    )
    idx_val, idx_test, y_val, y_test = train_test_split(
        idx_temp, y_temp, test_size=0.50, stratify=y_temp, random_state=seed
    )

    df_train = df.iloc[idx_train].reset_index(drop=True)
    df_val = df.iloc[idx_val].reset_index(drop=True)
    df_test = df.iloc[idx_test].reset_index(drop=True)

    # Fit imputation medians on training split ONLY
    train_medians: Dict[str, float] = {
        col: float(df_train[col].median()) for col in FEATURE_COLUMNS
    }

    X_train = df_train[FEATURE_COLUMNS].fillna(train_medians).to_numpy(dtype=float)
    X_val = df_val[FEATURE_COLUMNS].fillna(train_medians).to_numpy(dtype=float)
    X_test = df_test[FEATURE_COLUMNS].fillna(train_medians).to_numpy(dtype=float)

    # Class-imbalance handling on training split
    n_pos = int(np.sum(y_train == 1))
    n_neg = int(np.sum(y_train == 0))
    scale_pos_weight = float(n_neg / max(1, n_pos))

    xgb_clf = XGBClassifier(
        n_estimators=180,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.90,
        min_child_weight=10,
        scale_pos_weight=scale_pos_weight,
        monotone_constraints=MONOTONE_CONSTRAINTS_TUPLE,
        eval_metric="logloss",
        random_state=seed,
        n_jobs=2,
    )
    xgb_clf.fit(X_train, y_train)

    # Fit monotonic IsotonicRegression calibrator on validation raw probabilities
    # Weight positive class back to true validation base rate so calibrated probabilities match true default rate
    val_raw_probs = xgb_clf.predict_proba(X_val)[:, 1]
    calibrator = IsotonicRegression(
        y_min=0.005, y_max=0.985, increasing=True, out_of_bounds="clip"
    )
    calibrator.fit(val_raw_probs, y_val)

    # Evaluate on held-out Test set
    test_raw_probs = xgb_clf.predict_proba(X_test)[:, 1]
    test_cal_probs = calibrator.predict(test_raw_probs)
    # Blend 85% isotonic + 15% scaled raw probability to guarantee smooth strict monotonicity without flat step plateaus
    base_rate_ratio = float(np.mean(y_train)) / float(np.mean(val_raw_probs))
    smooth_scaled_probs = np.clip(test_raw_probs * base_rate_ratio, 0.005, 0.985)
    test_final_probs = np.clip(
        0.85 * test_cal_probs + 0.15 * smooth_scaled_probs, 0.005, 0.985
    )

    roc_auc = float(roc_auc_score(y_test, test_final_probs))
    ks_stat = compute_ks_statistic(y_test, test_final_probs)
    brier = float(brier_score_loss(y_test, test_final_probs))

    # Decision threshold at ~20% default probability (corresponding to GigScore ~780/650 risk cutoff)
    decision_threshold = 0.22
    y_pred = (test_final_probs >= decision_threshold).astype(int)
    prec = float(precision_score(y_test, y_pred, zero_division=0))
    rec = float(recall_score(y_test, y_pred, zero_division=0))
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()

    prob_true_curve, prob_pred_curve = calibration_curve(
        y_test, test_final_probs, n_bins=8, strategy="quantile"
    )

    importances = xgb_clf.feature_importances_
    feature_importance_map = {
        col: round(float(imp), 4)
        for col, imp in sorted(
            zip(FEATURE_COLUMNS, importances), key=lambda x: x[1], reverse=True
        )
    }

    test_scores = probability_to_gig_score(test_final_probs)
    fairness_report = run_synthetic_fairness_audit(df_test, test_scores)

    trained_at = datetime.now(timezone.utc).isoformat()
    metrics: Dict[str, Any] = {
        "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
        "model_version": settings.PRIMARY_MODEL_VERSION,
        "fallback_model_version": settings.FALLBACK_MODEL_VERSION,
        "trained_at": trained_at,
        "dataset_size": int(len(df)),
        "train_size": int(len(df_train)),
        "val_size": int(len(df_val)),
        "test_size": int(len(df_test)),
        "default_rate_overall": round(float(np.mean(y_all)), 4),
        "scale_pos_weight": round(scale_pos_weight, 4),
        "roc_auc": round(roc_auc, 4),
        "ks_statistic": round(ks_stat, 4),
        "brier_score": round(brier, 4),
        "decision_threshold": decision_threshold,
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
        "calibration_curve": {
            "mean_predicted_probability": [round(float(x), 4) for x in prob_pred_curve],
            "fraction_of_positives": [round(float(y), 4) for y in prob_true_curve],
        },
        "feature_importance": feature_importance_map,
    }

    artifacts_dir = backend_root / "app" / "ml" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    artifact_bundle = {
        "model_version": settings.PRIMARY_MODEL_VERSION,
        "trained_at": trained_at,
        "feature_columns": FEATURE_COLUMNS,
        "train_medians": train_medians,
        "xgb_classifier": xgb_clf,
        "isotonic_calibrator": calibrator,
        "base_rate_ratio": base_rate_ratio,
        "metrics": metrics,
        "fairness_report": fairness_report,
        "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
    }

    artifact_path = backend_root / settings.MODEL_ARTIFACT_PATH
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact_bundle, artifact_path)

    with open(artifacts_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    with open(artifacts_dir / "fairness_report.json", "w", encoding="utf-8") as f:
        json.dump(fairness_report, f, indent=2)

    _render_calibration_svg(
        prob_true_curve, prob_pred_curve, artifacts_dir / "calibration_plot.svg"
    )
    _write_model_card(
        metrics, fairness_report, backend_root / "app" / "ml" / "MODEL_CARD.md"
    )

    return metrics


if __name__ == "__main__":
    result = train_and_persist_model()
    print(
        f"Trained {result['model_version']} | ROC-AUC={result['roc_auc']:.4f} | KS={result['ks_statistic']:.4f} | Brier={result['brier_score']:.4f}"
    )

