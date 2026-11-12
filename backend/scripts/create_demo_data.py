"""End-to-End Demo Data & Artifact Initializer for GigScore.

Generates the 20,000 synthetic worker dataset, trains the calibrated XGBoost model
if not already present, and seeds the 5 demonstration workers and 2 demo lenders.

Prototype - synthetic data only. Not for real lending decisions.
"""
from pathlib import Path
from app.core.config import settings
from app.ml.generate_data import generate_synthetic_dataset
from app.ml.model import model_service
from app.ml.train import train_and_persist_model
from scripts.seed import seed_database


def create_all_demo_data(force_retrain: bool = False) -> dict:
    """Ensure synthetic dataset, trained XGBoost artifact, and demo DB rows exist."""
    backend_root = Path(__file__).resolve().parents[1]
    csv_path = backend_root / "data" / "synthetic_workers_20k.csv"
    if not csv_path.exists():
        generate_synthetic_dataset(n_workers=20000, output_dir=backend_root / "data")

    artifact_path = backend_root / settings.MODEL_ARTIFACT_PATH
    if force_retrain or not artifact_path.exists():
        metrics = train_and_persist_model()
    else:
        metrics = model_service.get_transparency_metadata().get("metrics", {})

    model_service.load_artifact()
    seed_summary = seed_database()
    return {
        "seed_summary": seed_summary,
        "active_model_version": model_service.active_model_version,
        "roc_auc": metrics.get("roc_auc"),
    }


if __name__ == "__main__":
    res = create_all_demo_data()
    print("Created all demo data and verified model:", res)

