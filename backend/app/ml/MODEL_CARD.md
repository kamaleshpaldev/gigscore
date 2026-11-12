# GigScore Model Card — `xgboost-calibrated-v1.0`

> **Disclaimer:** *Prototype - synthetic data only. Not for real lending decisions.*

## 1. Model Overview
- **Model Version:** `xgboost-calibrated-v1.0`
- **Fallback Baseline Version:** `rule-scorecard-v1.0`
- **Model Type:** Monotonic Gradient Boosted Decision Trees (`XGBClassifier`) + Isotonic Probability Calibrator
- **Trained At (UTC):** `2026-11-12T09:00:39.567846+00:00`
- **Target Variable:** Simulated 12-month repayment default (`default_12m`, ~12% synthetic base rate)
- **Score Mapping Formula:**
  $$\text{GigScore} = \text{clamp}\left(\text{round}(900 - 600 \times p_{\text{calibrated}}),\; 300,\; 900\right)$$

## 2. Dataset & Split (Synthetic Only)
- **Total Synthetic Workers:** 20,000 across 5 gig personas and 6 platforms
- **Train Split (70%):** 14,000 rows (used to fit base `XGBClassifier` with `scale_pos_weight`)
- **Validation Split (15%):** 3,000 rows (used exclusively for probability calibration & threshold tuning)
- **Test Split (15%):** 3,000 rows (held-out evaluation & fairness diagnostics)

## 3. Held-Out Test Set Performance Metrics
*(Note: Synthetic educational benchmark — does not represent real-world lending accuracy.)*

| Metric | Value |
| :--- | :--- |
| **ROC-AUC** | `0.9100` |
| **KS Statistic** | `0.6813` |
| **Brier Score (Calibrated)** | `0.0719` |
| **Precision (at decision threshold 0.22)** | `0.4306` |
| **Recall (at decision threshold 0.22)** | `0.7772` |

### Confusion Matrix (Held-Out Test Set)
- **True Negatives (Repaid correctly predicted):** `2272`
- **False Positives (Repaid flagged as high risk):** `369`
- **False Negatives (Default missed):** `80`
- **True Positives (Default caught):** `279`

## 4. Feature Importance & Monotonicity Constraints

| Feature | Relative Importance |
| :--- | :--- |
| `earnings_to_peak_ratio` | 0.4746 |
| `earnings_cv` | 0.2296 |
| `income_gap_months` | 0.1130 |
| `avg_monthly_earnings` | 0.0706 |
| `avg_rating` | 0.0553 |
| `earnings_trend_6m` | 0.0282 |
| `platform_count` | 0.0173 |
| `tenure_months` | 0.0114 |

## 5. Synthetic Fairness Diagnostics (Threshold: GigScore >= 650)
- **Gender Used as Model Input:** `False` (strictly excluded from features; evaluated post-hoc only)
- **Overall Test Approval Rate:** `92.4%`
- **City Tier Min Disparate Impact Ratio:** `0.9735`
- **Platform Type Min Disparate Impact Ratio:** `0.9660`
- **Audit Gender Min Disparate Impact Ratio:** `0.9015`

## 6. Ethical Considerations & Limitations
1. Trained strictly on simulated multi-platform Indian gig-worker profiles.
2. Raw Account Aggregator bank transactions are never persisted to the database.
3. Workers flagged by the Data Authenticity Engine receive `NEEDS_REVIEW` rather than an automated rejection or score.
