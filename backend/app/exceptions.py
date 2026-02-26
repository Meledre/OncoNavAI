from __future__ import annotations


class OncoAIError(Exception):
    """Base application error."""


class ValidationError(OncoAIError):
    """Raised when incoming payload is invalid."""


class AuthorizationError(OncoAIError):
    """Raised when the caller has no permissions."""


class RateLimitError(OncoAIError):
    """Raised when caller exceeded allowed request rate."""


class NotFoundError(OncoAIError):
    """Raised when requested entity does not exist."""
