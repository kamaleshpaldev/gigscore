"""API-Key Security, Hashing, Lender Authentication, and Per-Lender Rate Limiting.

Prototype - synthetic data only. Not for real lending decisions.
"""
from collections import defaultdict, deque
import hashlib
import hmac
import time
from typing import Deque, Dict, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT, settings
from app.core.database import get_db
from app.models.db_models import Lender

# In-memory sliding window rate-limit tracker: lender_id -> deque of request timestamps
_RATE_LIMIT_WINDOWS: Dict[str, Deque[float]] = defaultdict(deque)


def hash_api_key(raw_api_key: str) -> str:
    """Compute deterministic HMAC-SHA256 hash of a lender API key.

    Plaintext API keys are never stored in the database.
    """
    salt_bytes = settings.API_KEY_HASH_SALT.encode("utf-8")
    key_bytes = raw_api_key.strip().encode("utf-8")
    return hmac.new(salt_bytes, key_bytes, hashlib.sha256).hexdigest()


def reset_rate_limits() -> None:
    """Clear in-memory rate limit counters (used in automated test suites)."""
    _RATE_LIMIT_WINDOWS.clear()


def enforce_lender_rate_limit(lender_id: str, limit_per_minute: int) -> None:
    """Enforce a 60-second sliding-window rate limit for the given lender."""
    now = time.monotonic()
    window = _RATE_LIMIT_WINDOWS[lender_id]
    cutoff = now - 60.0
    while window and window[0] < cutoff:
        window.popleft()

    effective_limit = (
        limit_per_minute if limit_per_minute > 0 else settings.RATE_LIMIT_PER_MINUTE
    )
    if len(window) >= effective_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit of {effective_limit} requests/minute exceeded for lender '{lender_id}'.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )
    window.append(now)


def get_authenticated_lender(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Lender:
    """FastAPI dependency that authenticates a Lender via X-API-Key header and enforces rate limits."""
    if not x_api_key or not x_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "MISSING_API_KEY",
                "message": "Lender authentication required. Provide a valid 'X-API-Key' header.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    key_hash = hash_api_key(x_api_key)
    lender = db.query(Lender).filter(Lender.api_key_hash == key_hash).first()

    if lender is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_API_KEY",
                "message": "Invalid or unrecognized X-API-Key.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    if not lender.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "LENDER_INACTIVE",
                "message": f"Lender account '{lender.lender_id}' is inactive.",
                "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
            },
        )

    enforce_lender_rate_limit(lender.lender_id, lender.rate_limit_per_minute)
    return lender

