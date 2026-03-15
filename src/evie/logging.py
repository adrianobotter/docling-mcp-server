"""Structured logging for the EVIE MCP Server.

Provides JSON-formatted logs for audit trails, auth events, and tool calls.
Uses stdlib logging so it works everywhere without extra dependencies.
"""

import json
import logging
import sys
import time
from typing import Any


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extra fields from record.__dict__ that we set explicitly
        for key in ("event", "user_id", "tool", "query", "trial_id",
                     "evidence_object_id", "result_count", "duration_ms",
                     "error_code", "client_id", "ip"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, default=str)


def setup_logging() -> None:
    """Configure structured JSON logging for the EVIE server."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger("evie")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.propagate = False


# Pre-configured loggers
audit = logging.getLogger("evie.audit")
auth_log = logging.getLogger("evie.auth")
tool_log = logging.getLogger("evie.tools")
server_log = logging.getLogger("evie.server")
