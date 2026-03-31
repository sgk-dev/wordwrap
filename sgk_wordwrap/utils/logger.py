"""Structured JSON logging for sgk-wordwrap.

Usage:
    _logger = sgk_get_logger(__name__)
    _logger.info("sgk_convert", extra={"process": "firefox", "layout_before": "en", ...})

Log record format (JSON):
    {timestamp, level, logger, event, **extra_fields}
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any


class _SgkJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Merge any extra fields passed via extra={}
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_sgk_loggers: dict[str, logging.Logger] = {}
_sgk_root_configured = False


def sgk_configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    max_bytes: int = 1_048_576,
    backup_count: int = 3,
) -> None:
    """Configure the root sgk logger. Call once at startup."""
    global _sgk_root_configured

    root = logging.getLogger("sgk_wordwrap")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    formatter = _SgkJsonFormatter()

    # Console handler (stderr)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    root.propagate = False
    _sgk_root_configured = True


def sgk_get_logger(name: str) -> logging.Logger:
    """Return a child logger under the sgk_wordwrap hierarchy."""
    if not _sgk_root_configured:
        sgk_configure_logging()
    return logging.getLogger(name)
