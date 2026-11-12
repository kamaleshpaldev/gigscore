"""FastAPI Application Entrypoint for GigScore Backend & Integrated Fintech Web UI.

Prototype - synthetic data only. Not for real lending decisions.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import logging
import time
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import PROTOTYPE_DISCLAIMER_TEXT, settings
from app.core.database import get_db, init_db
from app.ml.model import model_service
from app.routes.consent import router as consent_router
from app.routes.lender import router as lender_router
from app.routes.score import router as score_router
from app.schemas.common import HealthResponse
from scripts.seed import seed_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("gigscore")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database schema, seed demo workers/lenders, and load ML model on startup."""
    logger.info("Starting %s (%s)...", settings.APP_NAME, settings.APP_ENV)
    if get_db not in app.dependency_overrides:
        init_db()
        seed_database()
    model_service.load_artifact()
    yield
    logger.info("Shutting down %s...", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Alternative Credit-Scoring Infrastructure Prototype for Indian Gig Workers. "
        f"{PROTOTYPE_DISCLAIMER_TEXT}"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
cors_origins = (
    settings.CORS_ORIGINS
    if isinstance(settings.CORS_ORIGINS, list)
    else [str(settings.CORS_ORIGINS)]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_and_disclaimer_header(
    request: Request, call_next
) -> Response:
    """Log every HTTP request and attach mandatory prototype disclaimer header."""
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    response.headers["X-Prototype-Disclaimer"] = PROTOTYPE_DISCLAIMER_TEXT
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    logger.info(
        "%s %s -> %d (%.2f ms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Ensure all HTTPException responses include structured fields and the prototype disclaimer."""
    if isinstance(exc.detail, dict):
        payload = dict(exc.detail)
        payload.setdefault("disclaimer", PROTOTYPE_DISCLAIMER_TEXT)
    else:
        payload = {
            "error_code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
        }
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Ensure Pydantic request validation errors return a structured response with disclaimer."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "details": {"errors": exc.errors()},
            "disclaimer": PROTOTYPE_DISCLAIMER_TEXT,
        },
    )


# Mount static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register API routers
app.include_router(consent_router)
app.include_router(score_router)
app.include_router(lender_router)


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """System health check verifying database connectivity and active ML model state."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.error("Health check DB probe failed: %s", exc)

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        database_connected=db_ok,
        primary_model_version=model_service.active_model_version,
        fallback_model_version=settings.FALLBACK_MODEL_VERSION,
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/api/model/calibration.svg", tags=["System"])
def get_calibration_plot_svg() -> Response:
    """Serve the generated SVG reliability/calibration plot."""
    svg_path = (
        Path(__file__).resolve().parent
        / "ml"
        / "artifacts"
        / "calibration_plot.svg"
    )
    if svg_path.exists():
        return Response(
            content=svg_path.read_text(encoding="utf-8"),
            media_type="image/svg+xml",
        )
    fallback_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100"><text x="20" y="50">Calibration plot not generated yet.</text></svg>'
    return Response(content=fallback_svg, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
@app.get("/worker", response_class=HTMLResponse, include_in_schema=False)
@app.get("/lender", response_class=HTMLResponse, include_in_schema=False)
@app.get("/transparency", response_class=HTMLResponse, include_in_schema=False)
def serve_frontend_app() -> FileResponse:
    """Serve the integrated responsive GigScore Fintech Web Application."""
    return FileResponse(STATIC_DIR / "index.html")

