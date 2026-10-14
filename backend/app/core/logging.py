"""Structured (JSON-lines) logging with request-id propagation and secret redaction."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_REDACT = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-_\.]+|(password|token|secret)(\"?\s*[:=]\s*\"?)[^\s\",]+")


def redact(text: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        if m.group(1):
            return m.group(1) + "[REDACTED]"
        return f"{m.group(2)}{m.group(3)}[REDACTED]"

    return _REDACT.sub(_sub, text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key in ("run_id", "algorithm", "duration_ms", "status", "path", "method", "status_code"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel("WARNING")
