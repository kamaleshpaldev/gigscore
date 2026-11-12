"""Common Pydantic base schemas, enums, and mandatory prototype disclaimer."""
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT


class DisclaimerMixin(BaseModel):
    """Base schema ensuring the mandatory prototype disclaimer is visible on responses."""

    disclaimer: str = Field(
        default=PROTOTYPE_DISCLAIMER_TEXT,
        description="Mandatory prototype disclaimer notice.",
    )

    model_config = ConfigDict(from_attributes=True)


class HealthResponse(DisclaimerMixin):
    """Response contract for GET /health."""

    status: str = Field(default="ok", description="Service health status.")
    app_name: str
    environment: str
    database_connected: bool
    primary_model_version: str
    fallback_model_version: str
    timestamp: datetime


class ErrorResponse(DisclaimerMixin):
    """Standardized error response schema."""

    error_code: str
    message: str
    request_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

