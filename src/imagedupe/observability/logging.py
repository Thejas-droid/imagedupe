from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "component": record.name,
            "event": record.getMessage(),
        }
        for key in (
            "request_id",
            "job_id",
            "collection_id",
            "generation",
            "backend",
            "elapsed_ms",
            "error_code",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("imagedupe")
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    if not any(getattr(handler, "_imagedupe_json", False) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._imagedupe_json = True
        root.addHandler(handler)
    root.propagate = False
