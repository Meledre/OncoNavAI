from __future__ import annotations

import pytest

from backend.app.exceptions import AuthorizationError, RateLimitError, ValidationError
from backend.app.security.demo_token import ensure_demo_token
from backend.app.security.rate_limit import RateLimiter
from backend.app.security.rbac import ensure_role


def test_ensure_role_accepts_trimmed_case_insensitive_role():
    ensure_role(" Admin ", {"admin", "clinician"})
    ensure_role("CLINICIAN", {"admin", "clinician"})


def test_ensure_role_rejects_empty_role():
    with pytest.raises(AuthorizationError):
        ensure_role("   ", {"admin", "clinician"})


def test_rate_limiter_requires_positive_limit():
    with pytest.raises(ValidationError):
        RateLimiter(max_requests_per_minute=0)


def test_rate_limiter_normalizes_blank_client_id_and_route_in_error():
    limiter = RateLimiter(max_requests_per_minute=1)
    limiter.check("   ", route="/analyze")
    with pytest.raises(RateLimitError) as exc:
        limiter.check("", route="/admin/reindex")
    assert "/admin/reindex" in str(exc.value)
    assert "retry in" in str(exc.value).lower()


def test_demo_token_validation_uses_expected_value():
    ensure_demo_token(received="demo-token", expected="demo-token")
    with pytest.raises(AuthorizationError):
        ensure_demo_token(received="wrong", expected="demo-token")
