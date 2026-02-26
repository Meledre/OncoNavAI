from __future__ import annotations

import hmac

from backend.app.exceptions import AuthorizationError


def ensure_demo_token(received: str | None, expected: str) -> None:
    if expected and not hmac.compare_digest(received or "", expected):
        raise AuthorizationError("Invalid X-Demo-Token")
