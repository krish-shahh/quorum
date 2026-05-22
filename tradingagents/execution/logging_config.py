"""Structured logging configuration for TradingAgents execution layer."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Merge any extra fields passed via the `extra` kwarg
        for key in ("ticker", "order_id", "action", "broker", "component"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        return json.dumps(log_entry, default=str)


_HUMAN_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"


def setup_logging(
    json_format: bool | None = None,
    level: str | None = None,
) -> None:
    """Configure root logging for the TradingAgents process.

    Parameters
    ----------
    json_format:
        If *True*, emit JSON-lines output.  If *None* (default), read from
        the ``TRADINGAGENTS_LOG_FORMAT`` env var (``"json"`` or ``"text"``).
        Falls back to human-readable text.
    level:
        Logging level name (e.g. ``"DEBUG"``).  If *None*, read from
        ``TRADINGAGENTS_LOG_LEVEL`` env var, defaulting to ``"INFO"``.
    """
    if json_format is None:
        json_format = os.getenv("TRADINGAGENTS_LOG_FORMAT", "text").lower() == "json"

    if level is None:
        level = os.getenv("TRADINGAGENTS_LOG_LEVEL", "INFO").upper()

    numeric_level = getattr(logging, level, logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicate output
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(_HUMAN_FORMAT))

    root.addHandler(handler)
