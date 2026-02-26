from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from typing import Protocol

_RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class HashEmbedder:
    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = digest[0] % self.dim
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            vector[idx] += sign

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        url: str,
        model: str,
        api_key: str = "",
        timeout_sec: int = 20,
        *,
        max_attempts: int = 4,
        retry_delay_sec: float = 0.25,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_sec = max(0.0, float(retry_delay_sec))

    def _is_retryable_http(self, exc: urllib.error.HTTPError) -> bool:
        return int(getattr(exc, "code", 0)) in _RETRYABLE_HTTP_STATUSES

    def _is_retryable_error(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError)):
            return True
        if isinstance(exc, OSError):
            return True
        if isinstance(exc, urllib.error.HTTPError):
            return self._is_retryable_http(exc)
        if isinstance(exc, urllib.error.URLError):
            reason = getattr(exc, "reason", None)
            if isinstance(reason, Exception):
                return self._is_retryable_error(reason)
        text = str(exc).lower()
        return any(
            marker in text
            for marker in (
                "timed out",
                "handshake",
                "connection reset",
                "temporarily unavailable",
                "unexpected eof",
                "unexpected_eof",
                "eof_while_reading",
                "eof occurred in violation of protocol",
                "ssl eof",
                "remote end closed connection without response",
            )
        )

    def embed(self, text: str) -> list[float]:
        request = urllib.request.Request(
            self.url + "/v1/embeddings",
            method="POST",
            data=json.dumps({"model": self.model, "input": text}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                **({"authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        last_exc: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    vector = payload["data"][0]["embedding"]
                break
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionResetError,
                ConnectionAbortedError,
                ConnectionRefusedError,
                OSError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                last_exc = exc
                is_retryable = self._is_retryable_error(exc)
                if not is_retryable or attempt >= self.max_attempts - 1:
                    raise RuntimeError(f"Embedding backend unavailable: {exc}") from exc
                if self.retry_delay_sec > 0:
                    time.sleep(self.retry_delay_sec * (2**attempt))
        else:
            raise RuntimeError(f"Embedding backend unavailable: {last_exc}")

        if not isinstance(vector, list) or not vector:
            raise RuntimeError("Embedding backend returned invalid vector")
        return [float(value) for value in vector]


class ResilientEmbedder:
    def __init__(self, primary: Embedder | None, fallback: Embedder | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    def embed(self, text: str) -> list[float]:
        if self.primary is not None:
            try:
                return self.primary.embed(text)
            except Exception:  # noqa: BLE001
                pass
        if self.fallback is not None:
            return self.fallback.embed(text)
        raise RuntimeError("No embedding backend available")


def build_embedder(
    backend: str,
    url: str,
    model: str,
    api_key: str,
    dim: int = 64,
    *,
    fail_closed: bool = False,
) -> Embedder:
    hash_backend = HashEmbedder(dim=dim)
    normalized_url = str(url or "").strip().lower()
    if backend == "openai" and url and model:
        if "api.openai.com" in normalized_url and not str(api_key or "").strip():
            if fail_closed:
                raise RuntimeError("strict_full requires EMBEDDING_API_KEY for OpenAI embeddings")
            return hash_backend
        if fail_closed:
            return OpenAICompatibleEmbedder(url=url, model=model, api_key=api_key)
        return ResilientEmbedder(
            primary=OpenAICompatibleEmbedder(url=url, model=model, api_key=api_key),
            fallback=hash_backend,
        )
    if fail_closed:
        raise RuntimeError("strict_full requires EMBEDDING_BACKEND=openai with configured URL and model")
    return hash_backend


def embed_text(text: str, dim: int = 64) -> list[float]:
    # Backward-compatible helper used by tests and legacy code paths.
    return HashEmbedder(dim=dim).embed(text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))
