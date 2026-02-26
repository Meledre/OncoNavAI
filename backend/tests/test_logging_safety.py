from __future__ import annotations

import logging

from backend.app.security.logging import safe_log
from backend.app.security.rate_limit import RateLimiter
from backend.app.exceptions import RateLimitError


def test_safe_log_redacts_sensitive_keys_in_snake_case_and_camel_case(caplog) -> None:
    logger = logging.getLogger("oncoai-test-log")
    payload = {
        "plan_text": "osimertinib 80 mg",
        "planText": "should not leak",
        "plan_structured": [{"step_type": "therapy"}],
        "notes": "patient note",
        "patient": {"name": "John Doe"},
        "diagnosis": "private diagnosis",
        "biomarkers": [{"name": "EGFR", "value": "L858R"}],
        "comorbidities": ["hypertension"],
        "contraindications": ["none"],
    }

    with caplog.at_level(logging.INFO, logger=logger.name):
        safe_log(logger, "security.test", payload)

    logged = "\n".join(record.message for record in caplog.records)
    assert "[REDACTED]" in logged
    assert "osimertinib 80 mg" not in logged
    assert "should not leak" not in logged
    assert "patient note" not in logged
    assert "John Doe" not in logged
    assert "private diagnosis" not in logged
    assert "L858R" not in logged
    assert "hypertension" not in logged


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter(max_requests_per_minute=1)
    limiter.check("client-1")

    try:
        limiter.check("client-1")
        assert False, "Expected RateLimitError"
    except RateLimitError:
        pass
