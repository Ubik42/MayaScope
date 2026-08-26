"""Small rotating JSONL event log shared by the Maya UI and headless Runner."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
from typing import Mapping, Optional


_LOCK = threading.Lock()
_LOGGER = None


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", "runtime"),
            "message": record.getMessage(),
            "context": getattr(record, "context", {}),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def default_log_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "MayaScope" / "logs"


def get_logger(log_dir: Optional[Path] = None) -> logging.Logger:
    global _LOGGER
    with _LOCK:
        if _LOGGER is not None and log_dir is None:
            return _LOGGER
        directory = (log_dir or default_log_directory()).expanduser().resolve()
        logger = logging.getLogger(
            "MayaScope" if log_dir is None else "MayaScope.%s" % hash(str(directory))
        )
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(
                    directory / "mayascope.jsonl",
                    maxBytes=2 * 1024 * 1024,
                    backupCount=4,
                    encoding="utf-8",
                    delay=True,
                )
                handler.setFormatter(_JsonFormatter())
                logger.addHandler(handler)
            except Exception:
                logger.addHandler(logging.NullHandler())
        if log_dir is None:
            _LOGGER = logger
        return logger


def log_event(
    event: str,
    message: str = "",
    *,
    level: int = logging.INFO,
    context: Optional[Mapping] = None,
) -> None:
    get_logger().log(
        level,
        message,
        extra={"event": str(event), "context": dict(context or {})},
    )


def close_logger(logger: Optional[logging.Logger] = None) -> None:
    """Release Windows file handles for tests and explicit host shutdown."""
    target = logger or _LOGGER
    if target is None:
        return
    for handler in tuple(target.handlers):
        try:
            handler.flush()
            handler.close()
        finally:
            target.removeHandler(handler)
