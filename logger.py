"""
Centralized logging configuration for the Financial Document Analyzer.
"""

import os
import logging
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

os.makedirs(LOG_DIR, exist_ok=True)

# ─── Shared formatter ───────────────────────────────────────────────
_FORMATTER = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ─── File handler (rotating) ────────────────────────────────────────
_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_file_handler.setFormatter(_FORMATTER)
_file_handler.setLevel(LOG_LEVEL)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_FORMATTER)
_console_handler.setLevel(LOG_LEVEL)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger that writes to both console and the log file.

    Usage:
        from logger import get_logger
        logger = get_logger(__name__)
        logger.info("Server started")
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(LOG_LEVEL)
        logger.addHandler(_file_handler)
        logger.addHandler(_console_handler)
        logger.propagate = False

    return logger
