from __future__ import annotations

import ast
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

_RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMEndpoint:
    url: str
    model: str
    api_key: str = ""


class LLMProviderRouter:
    def __init__(self, primary: LLMEndpoint | None, fallback: LLMEndpoint | None) -> None:
        self.primary = primary
        self.fallback = fallback

    @staticmethod
    def _timeout_from_env(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            parsed = int(raw.strip())
        except ValueError:
            return default
        return max(3, min(parsed, 900))

    @staticmethod
    def _int_from_env(name: str, default: int, *, min_value: int, max_value: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            parsed = int(raw.strip())
        except ValueError:
            return default
        return max(min_value, min(parsed, max_value))

    @staticmethod
    def _is_ollama_endpoint(endpoint: LLMEndpoint) -> bool:
        url = endpoint.url.lower()
        return "ollama" in url or ":11434" in url

    @staticmethod
    def _fallback_rescue_model() -> str:
        value = str(os.getenv("LLM_FALLBACK_RESCUE_MODEL") or "").strip()
        return value or "qwen2.5:0.5b"

    def _endpoint_timeout_sec(
        self,
        endpoint: LLMEndpoint,
        *,
        is_fallback: bool,
        has_output_schema: bool,
    ) -> int:
        env_name = "LLM_FALLBACK_TIMEOUT_SEC" if is_fallback else "LLM_PRIMARY_TIMEOUT_SEC"
        if is_fallback:
            default = 180 if has_output_schema else 20
        else:
            default = 45 if has_output_schema else 12
        timeout = self._timeout_from_env(env_name, default)
        if is_fallback and "ollama" in endpoint.url.lower() and timeout < 45:
            # Local Ollama models are frequently slower than API providers.
            return 45
        return timeout

    def _endpoint_retry_attempts(self, *, is_fallback: bool) -> int:
        env_name = "LLM_FALLBACK_RETRY_ATTEMPTS" if is_fallback else "LLM_PRIMARY_RETRY_ATTEMPTS"
        default = 1 if is_fallback else 3
        return self._int_from_env(env_name, default, min_value=1, max_value=8)

    def _endpoint_retry_delay_sec(self, *, is_fallback: bool) -> float:
        env_name = "LLM_FALLBACK_RETRY_DELAY_MS" if is_fallback else "LLM_PRIMARY_RETRY_DELAY_MS"
        default_ms = 150 if is_fallback else 300
        delay_ms = self._int_from_env(env_name, default_ms, min_value=0, max_value=30000)
        return float(delay_ms) / 1000.0

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError)):
            return True
        if isinstance(exc, urllib.error.HTTPError):
            return int(getattr(exc, "code", 0)) in _RETRYABLE_HTTP_STATUSES
        if isinstance(exc, urllib.error.URLError):
            reason = getattr(exc, "reason", None)
            if isinstance(reason, Exception):
                return LLMProviderRouter._is_retryable_error(reason)
        text = str(exc).lower()
        return any(marker in text for marker in ("timed out", "handshake", "connection reset", "temporarily unavailable"))

    @staticmethod
    def _extract_text_content(raw_content: object) -> str | None:
        if isinstance(raw_content, str):
            return raw_content
        if isinstance(raw_content, list):
            parts: list[str] = []
            for item in raw_content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "\n".join(parts).strip()
        return None

    @staticmethod
    def _parse_python_literal_dict(content: str) -> dict | None:
        try:
            parsed = ast.literal_eval(content)
        except (ValueError, SyntaxError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _parse_json_payload(content: str) -> dict | None:
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        literal_dict = LLMProviderRouter._parse_python_literal_dict(content)
        if literal_dict is not None:
            return literal_dict

        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content, flags=re.IGNORECASE)
        if fenced:
            try:
                parsed = json.loads(fenced.group(1))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                literal_dict = LLMProviderRouter._parse_python_literal_dict(fenced.group(1))
                if literal_dict is not None:
                    return literal_dict

        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            snippet = content[first_brace : last_brace + 1]
            try:
                parsed = json.loads(snippet)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                literal_dict = LLMProviderRouter._parse_python_literal_dict(snippet)
                if literal_dict is not None:
                    return literal_dict
                return None
        return None

    def _call_openai_compatible(
        self,
        endpoint: LLMEndpoint,
        prompt: str,
        timeout_sec: int = 12,
        max_attempts: int = 1,
        retry_delay_sec: float = 0.0,
        output_schema: dict | None = None,
        schema_name: str = "response",
        system_prompt: str | None = None,
    ) -> dict | None:
        normalized_system = str(system_prompt or "").strip()
        if normalized_system:
            system_content = f"{normalized_system}\n\nReturn valid JSON only."
        else:
            system_content = "Return valid JSON only."
        payload = {
            "model": endpoint.model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        if output_schema is not None:
            if self._is_ollama_endpoint(endpoint):
                # Ollama structured response_format can be unstable in some local CPU setups.
                # Keep plain completion and validate/coerce JSON downstream.
                payload["max_tokens"] = self._int_from_env(
                    "LLM_FALLBACK_MAX_TOKENS",
                    default=128,
                    min_value=32,
                    max_value=4096,
                )
            else:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": output_schema,
                    },
                }

        req = urllib.request.Request(
            endpoint.url.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}),
            },
            method="POST",
        )

        for attempt in range(max(1, int(max_attempts))):
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    raw_content = body["choices"][0]["message"]["content"]
                    content = self._extract_text_content(raw_content)
                    if not content:
                        return None
                    parsed = self._parse_json_payload(content)
                    if parsed is not None:
                        return parsed
                    if output_schema is not None and self._is_ollama_endpoint(endpoint):
                        # Preserve non-JSON text so higher layers can still mark
                        # the generation path as LLM fallback with deterministic report fallback.
                        return {"_raw_text": content.strip()}
                    return None
            except (
                urllib.error.URLError,
                TimeoutError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                if attempt >= max_attempts - 1 or not self._is_retryable_error(exc):
                    return None
                if retry_delay_sec > 0:
                    time.sleep(retry_delay_sec * (2**attempt))
        return None

    def generate_json(
        self,
        prompt: str,
        output_schema: dict | None = None,
        schema_name: str = "response",
        system_prompt: str | None = None,
    ) -> tuple[dict | None, str]:
        has_output_schema = output_schema is not None
        if self.primary:
            result = self._call_openai_compatible(
                self.primary,
                prompt,
                timeout_sec=self._endpoint_timeout_sec(
                    self.primary,
                    is_fallback=False,
                    has_output_schema=has_output_schema,
                ),
                max_attempts=self._endpoint_retry_attempts(is_fallback=False),
                retry_delay_sec=self._endpoint_retry_delay_sec(is_fallback=False),
                output_schema=output_schema,
                schema_name=schema_name,
                system_prompt=system_prompt,
            )
            if result is not None:
                return result, "primary"

        if self.fallback:
            result = self._call_openai_compatible(
                self.fallback,
                prompt,
                timeout_sec=self._endpoint_timeout_sec(
                    self.fallback,
                    is_fallback=True,
                    has_output_schema=has_output_schema,
                ),
                max_attempts=self._endpoint_retry_attempts(is_fallback=True),
                retry_delay_sec=self._endpoint_retry_delay_sec(is_fallback=True),
                output_schema=output_schema,
                schema_name=schema_name,
                system_prompt=system_prompt,
            )
            if result is None and self._is_ollama_endpoint(self.fallback):
                rescue_model = self._fallback_rescue_model()
                current_model = str(self.fallback.model or "").strip()
                if rescue_model and rescue_model != current_model:
                    rescue_endpoint = LLMEndpoint(
                        url=self.fallback.url,
                        model=rescue_model,
                        api_key=self.fallback.api_key,
                    )
                    result = self._call_openai_compatible(
                        rescue_endpoint,
                        prompt,
                        timeout_sec=self._endpoint_timeout_sec(
                            self.fallback,
                            is_fallback=True,
                            has_output_schema=has_output_schema,
                        ),
                        max_attempts=self._endpoint_retry_attempts(is_fallback=True),
                        retry_delay_sec=self._endpoint_retry_delay_sec(is_fallback=True),
                        output_schema=output_schema,
                        schema_name=schema_name,
                        system_prompt=system_prompt,
                    )
            if result is not None:
                return result, "fallback"

        return None, "deterministic"
