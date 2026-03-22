"""
Centralized logging configuration.

Log files (all under  BASE/backend/logs/):
  auth.log   – authentication events only (API key checks, admin login/logout)
               logger name prefix: "app.auth"
  system.log – all INFO+ events (requests, orders, startup, health, general)
  error.log  – WARNING+ events (errors, warnings from any logger)

Rotation: 10 MB max, 5 backups (system/error);  5 MB / 3 backups (auth).
"""
import logging
import logging.handlers
import os


FMT = logging.Formatter(
    fmt="%(asctime)s [%(levelname)-8s] %(name)-22s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class _PrefixFilter(logging.Filter):
    """Pass only records whose logger name starts with `prefix`."""
    def __init__(self, prefix: str):
        super().__init__()
        self._prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self._prefix)


def setup_logging(log_dir: str = "logs") -> None:
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid adding duplicate file handlers on uvicorn hot-reload.
    already_setup = any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        for h in root.handlers
    )
    if already_setup:
        return

    # ── Console ───────────────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setFormatter(FMT)
    console.setLevel(logging.INFO)
    root.addHandler(console)

    # ── system.log  (INFO+ from ALL loggers) ──────────────────────────────────
    sys_h = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "system.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    sys_h.setFormatter(FMT)
    sys_h.setLevel(logging.INFO)
    root.addHandler(sys_h)

    # ── error.log  (WARNING+ from ALL loggers) ────────────────────────────────
    err_h = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "error.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    err_h.setFormatter(FMT)
    err_h.setLevel(logging.WARNING)
    root.addHandler(err_h)

    # ── auth.log  (ALL levels, app.auth logger only) ───────────────────────────
    auth_h = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "auth.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    auth_h.setFormatter(FMT)
    auth_h.setLevel(logging.DEBUG)
    auth_h.addFilter(_PrefixFilter("app.auth"))
    root.addHandler(auth_h)

    # ── health.log  (dedicated health-check logger, kept for compatibility) ───
    health_h = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "health.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    health_h.setFormatter(FMT)
    health_h.setLevel(logging.DEBUG)

    health_logger = logging.getLogger("health")
    health_logger.addHandler(health_h)
    health_logger.propagate = True          # also flows into system.log

    # Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
