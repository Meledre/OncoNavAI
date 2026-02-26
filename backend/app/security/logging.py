from __future__ import annotations

import json
import logging
import re
from typing import Any

SENSITIVE_KEYS = {
    "plan_text",
    "plan_structured",
    "notes",
    "patient",
    "diagnosis",
    "biomarkers",
    "comorbidities",
    "contraindications",
}
_CANONICAL_SENSITIVE_KEYS = {re.sub(r"[^a-z0-9]+", "", key.lower()) for key in SENSITIVE_KEYS}


def _is_sensitive_key(key: str) -> bool:
    canonical = re.sub(r"[^a-z0-9]+", "", key.lower())
    return canonical in _CANONICAL_SENSITIVE_KEYS


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, subvalue in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _sanitize(subvalue)
        return redacted
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def get_logger(name: str = "oncoai") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def safe_log(logger: logging.Logger, message: str, payload: dict[str, Any] | None = None) -> None:
    if payload is None:
        logger.info(message)
        return
    logger.info("%s %s", message, json.dumps(_sanitize(payload), ensure_ascii=False))
