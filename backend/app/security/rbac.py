from __future__ import annotations

from collections.abc import Iterable

from backend.app.exceptions import AuthorizationError


def normalize_role(role: str | None) -> str:
    if role is None:
        return ""
    return str(role).strip().lower()


def ensure_role(role: str, allowed: Iterable[str]) -> None:
    normalized_role = normalize_role(role)
    allowed_set = {normalize_role(item) for item in allowed}
    if normalized_role not in allowed_set:
        allowed_str = ", ".join(sorted(allowed_set))
        shown = normalized_role or "unknown"
        raise AuthorizationError(f"Access denied for role={shown}. Allowed roles: {allowed_str}")
