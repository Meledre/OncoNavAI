from __future__ import annotations

import time
from collections import defaultdict, deque

from backend.app.exceptions import RateLimitError, ValidationError


class RateLimiter:
    def __init__(self, max_requests_per_minute: int) -> None:
        if max_requests_per_minute < 1:
            raise ValidationError("rate_limit_per_minute must be >= 1")
        self.max_requests_per_minute = max_requests_per_minute
        self._events: dict[str, deque[float]] = defaultdict(deque)

    @staticmethod
    def _normalize_client_id(client_id: str | None) -> str:
        if client_id is None:
            return "anonymous"
        normalized = str(client_id).strip()
        return normalized or "anonymous"

    def check(self, client_id: str, route: str = "/analyze") -> None:
        now = time.time()
        window_start = now - 60.0
        normalized_client_id = self._normalize_client_id(client_id)
        bucket = self._events[normalized_client_id]

        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= self.max_requests_per_minute:
            retry_after = max(0.0, 60.0 - (now - bucket[0])) if bucket else 60.0
            raise RateLimitError(f"Rate limit exceeded for {route}; retry in {retry_after:.1f}s")

        bucket.append(now)
