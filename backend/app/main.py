import os
import time
import socket
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.logging_config import setup_logging
from app.routes.api      import router as api_router
from app.routes.admin    import router as admin_router
from app.routes.webhooks import router as webhooks_router
from app.config          import settings
from app.database        import get_db

# ── Initialise logging before anything else ───────────────────────────────────
setup_logging(log_dir="logs")
logger       = logging.getLogger("app.main")
health_logger = logging.getLogger("health")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Restaurant Kiosk Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response logging middleware ─────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    client = request.client.host if request.client else "unknown"

    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logging.getLogger("app.request").error(
            "%s %s  client=%s  ERROR after %.1fms: %s",
            request.method, request.url.path, client, elapsed, exc,
            exc_info=True,
        )
        raise

    elapsed = (time.perf_counter() - start) * 1000
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logging.getLogger("app.request").log(
        level,
        "%s %s  client=%s  status=%d  %.1fms",
        request.method, request.url.path, client,
        response.status_code, elapsed,
    )
    return response


# ── Startup / shutdown events ─────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    logger.info("=" * 60)
    logger.info("Restaurant Kiosk Backend starting up")
    logger.info("Port: %d  |  DB: %s", settings.PORT, settings.DATABASE_URL.split("@")[-1])
    logger.info("=" * 60)


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Restaurant Kiosk Backend shutting down")


# ── Static files ──────────────────────────────────────────────────────────────
os.makedirs("app/static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(api_router)
app.include_router(admin_router)
app.include_router(webhooks_router)


# ── Global unhandled exception handler ───────────────────────────────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("app.error").error(
        "Unhandled exception  %s %s: %s",
        request.method, request.url.path, exc,
        exc_info=True,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"service": "Restaurant Kiosk Backend", "admin": "/admin/", "api_docs": "/docs"}


# ── Health ────────────────────────────────────────────────────────────────────
def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if the TCP port accepts a connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """
    Detailed health check.  Logs every call to health.log.
    Checks:
      • database  – executes SELECT 1
      • port_8000 – TCP connect to 127.0.0.1:8000
    """
    checks: dict = {}
    overall = "ok"
    ts = datetime.now(timezone.utc).isoformat()

    # ── Database ──────────────────────────────────────────────────────────────
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        overall = "degraded"
        health_logger.error("Health DB check failed: %s", exc, exc_info=True)

    # ── Port 8000 ─────────────────────────────────────────────────────────────
    if _check_port("127.0.0.1", settings.PORT):
        checks["port_8000"] = "listening"
    else:
        checks["port_8000"] = "not reachable"
        overall = "degraded"

    result = {"status": overall, "checks": checks, "timestamp": ts}

    if overall == "ok":
        health_logger.info("PASS  %s", checks)
    else:
        health_logger.warning("DEGRADED  %s", checks)

    status_code = 200 if overall == "ok" else 503
    return JSONResponse(content=result, status_code=status_code)
