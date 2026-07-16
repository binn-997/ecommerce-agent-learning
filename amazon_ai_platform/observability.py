"""PII-safe structured event helpers shared by API, workers and agents."""

from __future__ import annotations

import hashlib
import json
from typing import Any


ALLOWED_LOG_FIELDS = {
    "trace_id",
    "seller_id_hash",
    "operation",
    "request_id",
    "date_window",
    "row_count",
    "latency_ms",
    "provider",
    "fallback_count",
    "status",
    "node",
}


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def safe_event(**fields: Any) -> str:
    """Serialize only explicitly approved fields; prompt, auth and buyer PII are dropped."""
    return json.dumps(
        {key: value for key, value in fields.items() if key in ALLOWED_LOG_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
