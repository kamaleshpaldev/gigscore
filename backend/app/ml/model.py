"""Model Loader and Inference Engine for GigScore.

Uses calibrated XGBoost as primary scorer and transparently falls back to the
rule-based scorecard if the artifact is missing or fallback is explicitly requested.

Prototype - synthetic data only. Not for real lending decisions.
"""
from pathlib import Path
from typing import Any, Dict, Optional
import json
import logging
import joblib
import numpy as np

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT, settings
from app.ml.explain import ShapExplanationEngine, generate_improvement_tips
from app.ml.features import FEATURE_COLUMNS, sanitize_feature_dict
from app.ml.scorecard import (
    map_score_to_band_and_tier,
    score_with_rule_scorecard,
)
from app.ml.train import probability_to_gig_score
from app.schemas.score import ScoringEngineEnum

logger = logging.getLogger(__name__)


class GigScoreModelService:
    """Manages calibrated XGBoost inference, SHAP explanations, and transparent scorecard fallback."""

    def __init__(self, artifact_path: Optional[Path] = None) -> None:
        self.backend_root = Path(__file__).resolve().parents[2]
        self.artifact_path = artifact_path or (
            self.backend_root / settings.MODEL_ARTIFACT_PATH
        )
        self.bundle: Optional[Dict[str, Any]] = None
        self.shap_engine: Optional[ShapExplanationEngine] = None
        self.load_artifact()

    def load_artifact(self) -> bool:
        """Load the persisted Joblib model bundle if available."""
        if not self.artifact_path.exists():
            logger.warning(
                "Calibrated XGBoost artifact not found at %s; using %s fallback.",
                self.artifact_path,
                settings.FALLBACK_MODEL_VERSION,
            )
            self.bundle = None
            self.shap_engine = None
            return False

        try:
            loaded = joblib.load(self.artifact_path)
            self.bundle = loaded
            self.shap_engine = ShapExplanationEngine(loaded["xgb_classifier"])
            return True
        except Exception as exc:
            logger.error("Failed to load model artifact %s: %s", self.artifact_path, exc)
            self.bundle = None
            self.shap_engine = None
            return False

    @property
    def is_xgboost_loaded(self) -> bool:
        return self.bundle is not None and self.shap_engine is not None

    @property
    def active_model_version(self) -> str:
        if self.is_xgboost_loaded and self.bundle:
            return str(self.bundle.get("model_version", settings.PRIMARY_MODEL_VERSION))
        return settings.FALLBACK_MODEL_VERSION

    def predict_score(
        self,
        raw_features: Dict[str, Any],
        force_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Compute GigScore (300-900), calibrated probability, bands, and plain-English factors."""
        f = sanitize_feature_dict(raw_features)

        if force_fallback or not self.is_xgboost_loaded or self.bundle is None:
            fallback_res = score_with_rule_scorecard(f)
            fallback_res["improvement_tips"] = generate_improvement_tips(f)
            fallback_res["features_used"] = f
            return fallback_res

        xgb_clf = self.bundle["xgb_classifier"]
        calibrator = self.bundle["isotonic_calibrator"]
        base_rate_ratio = float(self.bundle.get("base_rate_ratio", 1.0))

        x_arr = np.array([[f[col] for col in FEATURE_COLUMNS]], dtype=float)
        raw_prob_default = float(xgb_clf.predict_proba(x_arr)[0, 1])
        iso_prob = float(calibrator.predict([raw_prob_default])[0])
        smooth_prob = float(np.clip(raw_prob_default * base_rate_ratio, 0.005, 0.985))
        calibrated_default_prob = float(
            np.clip(0.85 * iso_prob + 0.15 * smooth_prob, 0.005, 0.985)
        )

        gig_score = int(probability_to_gig_score(calibrated_default_prob))
        score_band, risk_tier = map_score_to_band_and_tier(gig_score)

        explanation = (
            self.shap_engine.explain_features(f)
            if self.shap_engine is not None
            else {
                "top_factors": [],
                "reason_codes": [],
                "improvement_tips": generate_improvement_tips(f),
            }
        )

        return {
            "gig_score": gig_score,
            "calibrated_default_probability": round(calibrated_default_prob, 4),
            "calibrated_probability": round(1.0 - calibrated_default_prob, 4),
            "score_band": score_band,
            "risk_tier": risk_tier,
            "top_factors": explanation["top_factors"],
            "top_positive_factors": explanation.get("top_positive_factors", []),
            "top_negative_factors": explanation.get("top_negative_factors", []),
            "reason_codes": explanation["reason_codes"],
            "improvement_tips": explanation["improvement_tips"],
            "features_used": f,
            "model_version": str(
                self.bundle.get("model_version", settings.PRIMARY_MODEL_VERSION)
            ),
            "scoring_engine": ScoringEngineEnum.XGBOOST.value,
        }

    def get_transparency_metadata(self) -> Dict[str, Any]:
        """Return model metrics, fairness report, feature metadata, and model card for transparency UI."""
        artifacts_dir = self.backend_root / "app" / "ml" / "artifacts"
        metrics: Dict[str, Any] = {}
        fairness: Dict[str, Any] = {}

        if self.bundle:
            metrics = self.bundle.get("metrics", {})
            fairness = self.bundle.get("fairness_report", {})
        else:
            metrics_path = artifacts_dir / "metrics.json"
            fairness_path = artifacts_dir / "fairness_report.json"
            if metrics_path.exists():
                metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            if fairness_path.exists():
                fairness = json.loads(fairness_path.read_text(encoding="utf-8"))

        model_card_path = self.backend_root / "app" / "ml" / "MODEL_CARD.md"
        model_card_md = (
            model_card_path.read_text(encoding="utf-8")
            if model_card_path.exists()
            else "Model card not generated yet. Run `make train`."
        )

        return {
            "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            "active_model_version": self.active_model_version,
            "xgboost_loaded": self.is_xgboost_loaded,
            "primary_model_version": settings.PRIMARY_MODEL_VERSION,
            "fallback_model_version": settings.FALLBACK_MODEL_VERSION,
            "score_formula": "gig_score = clamp(round(900 - 600 * calibrated_default_probability), 300, 900)",
            "feature_columns": FEATURE_COLUMNS,
            "metrics": metrics,
            "fairness_report": fairness,
            "model_card_markdown": model_card_md,
        }


model_service = GigScoreModelService()

