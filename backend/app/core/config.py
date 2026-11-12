from pathlib import Path
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROTOTYPE_DISCLAIMER_TEXT = (
    "Prototype - synthetic data only. Not for real lending decisions."
)


class Settings(BaseSettings):
    """Application Settings managed by Pydantic Settings."""

    APP_NAME: str = "GigScore Backend"
    APP_ENV: str = "development"
    DATABASE_URL: str = "sqlite:///./gigscore.db"
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # Billing & Lender Infrastructure
    SCORE_CHECK_FEE_INR: float = 30.0
    CURRENCY: str = "INR"
    API_KEY_HASH_SALT: str = "gigscore-prototype-salt-change-in-prod"
    RATE_LIMIT_PER_MINUTE: int = 60

    # Consent & Mock Account Aggregator
    DEFAULT_CONSENT_EXPIRY_HOURS: int = 24
    ALLOWED_CONSENT_PURPOSES: Union[List[str], str] = [
        "CREDIT_SCORING",
        "LOAN_UNDERWRITING",
        "GIG_SCORE_VERIFICATION",
    ]
    DEFAULT_AA_PROVIDER: str = "Setu_AA_Mock"

    # Machine Learning & Scoring Engine
    PRIMARY_MODEL_VERSION: str = "xgboost-calibrated-v1.0"
    FALLBACK_MODEL_VERSION: str = "rule-scorecard-v1.0"
    MODEL_ARTIFACT_PATH: str = "app/ml/artifacts/gigscore_xgb_calibrated.joblib"
    SCORE_MIN: int = 300
    SCORE_MAX: int = 900
    PROTOTYPE_DISCLAIMER: str = PROTOTYPE_DISCLAIMER_TEXT

    @field_validator("CORS_ORIGINS", "ALLOWED_CONSENT_PURPOSES", mode="before")
    @classmethod
    def assemble_csv_or_list(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.strip().startswith("[") and v.strip().endswith("]"):
                import json

                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        elif isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Backward-compatible helper alias for assemble_csv_or_list."""
        return cls.assemble_csv_or_list(v)

    model_config = SettingsConfigDict(
        env_file=(
            str(Path(__file__).resolve().parents[2] / ".env"),
            str(Path(__file__).resolve().parents[3] / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
