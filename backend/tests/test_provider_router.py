from __future__ import annotations

import json

from backend.app.llm.provider_router import LLMEndpoint, LLMProviderRouter


def test_provider_router_returns_deterministic_when_endpoints_missing():
    router = LLMProviderRouter(primary=None, fallback=None)
    payload, path = router.generate_json("hello")
    assert payload is None
    assert path == "deterministic"


class _StubHttpResponse:
    def __init__(self, body: dict) -> None:
        self._raw = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_provider_router_parses_openai_content_array(monkeypatch):
    primary = LLMEndpoint(url="http://primary.local", model="test-model", api_key="")
    router = LLMProviderRouter(primary=primary, fallback=None)

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        assert request.full_url == "http://primary.local/v1/chat/completions"
        return _StubHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "{\"from\":\"primary\"}"}
                            ]
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json("hello")
    assert payload == {"from": "primary"}
    assert path == "primary"


def test_provider_router_falls_back_when_primary_content_array_invalid(monkeypatch):
    primary = LLMEndpoint(url="http://primary.local", model="test-model", api_key="")
    fallback = LLMEndpoint(url="http://fallback.local", model="fallback-model", api_key="")
    router = LLMProviderRouter(primary=primary, fallback=fallback)

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        if request.full_url == "http://primary.local/v1/chat/completions":
            return _StubHttpResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "not-json"}
                                ]
                            }
                        }
                    ]
                }
            )
        assert request.full_url == "http://fallback.local/v1/chat/completions"
        return _StubHttpResponse({"choices": [{"message": {"content": "{\"from\":\"fallback\"}"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json("hello")
    assert payload == {"from": "fallback"}
    assert path == "fallback"


def test_provider_router_parses_fenced_json_content(monkeypatch):
    primary = LLMEndpoint(url="http://primary.local", model="test-model", api_key="")
    router = LLMProviderRouter(primary=primary, fallback=None)

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        assert request.full_url == "http://primary.local/v1/chat/completions"
        return _StubHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "```json\n{\"from\":\"primary\"}\n```"
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json("hello")
    assert payload == {"from": "primary"}
    assert path == "primary"


def test_provider_router_sends_json_schema_response_format(monkeypatch):
    primary = LLMEndpoint(url="http://primary.local", model="test-model", api_key="")
    router = LLMProviderRouter(primary=primary, fallback=None)
    captured_payload = {}

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        body = json.loads(request.data.decode("utf-8"))
        captured_payload.update(body)
        return _StubHttpResponse({"choices": [{"message": {"content": "{\"from\":\"primary\"}"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json(
        "hello",
        output_schema={
            "type": "object",
            "properties": {"from": {"type": "string"}},
            "required": ["from"],
            "additionalProperties": False,
        },
        schema_name="sample_schema",
    )
    assert payload == {"from": "primary"}
    assert path == "primary"
    assert captured_payload["response_format"]["type"] == "json_schema"
    assert captured_payload["response_format"]["json_schema"]["name"] == "sample_schema"


def test_provider_router_omits_response_format_for_ollama_structured_calls(monkeypatch):
    fallback = LLMEndpoint(url="http://ollama:11434", model="qwen2.5:0.5b", api_key="")
    router = LLMProviderRouter(primary=None, fallback=fallback)
    captured_payload = {}

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        body = json.loads(request.data.decode("utf-8"))
        captured_payload.update(body)
        return _StubHttpResponse({"choices": [{"message": {"content": "{\"from\":\"fallback\"}"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json(
        "hello",
        output_schema={
            "type": "object",
            "properties": {"from": {"type": "string"}},
            "required": ["from"],
            "additionalProperties": False,
        },
        schema_name="sample_schema",
    )
    assert payload == {"from": "fallback"}
    assert path == "fallback"
    assert "response_format" not in captured_payload
    assert isinstance(captured_payload.get("max_tokens"), int)
    assert captured_payload.get("max_tokens") == 128


def test_provider_router_parses_single_quoted_python_like_payload(monkeypatch):
    primary = LLMEndpoint(url="http://primary.local", model="test-model", api_key="")
    router = LLMProviderRouter(primary=primary, fallback=None)

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        assert request.full_url == "http://primary.local/v1/chat/completions"
        return _StubHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "{'summary':'ok','issues':[],'missing_data':[],'notes':'n'}"
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json("hello")
    assert payload == {"summary": "ok", "issues": [], "missing_data": [], "notes": "n"}
    assert path == "primary"


def test_provider_router_uses_env_timeouts_for_primary_and_fallback(monkeypatch):
    primary = LLMEndpoint(url="http://primary.local", model="test-model", api_key="")
    fallback = LLMEndpoint(url="http://ollama:11434", model="qwen2.5:3b", api_key="")
    router = LLMProviderRouter(primary=primary, fallback=fallback)
    seen: list[tuple[str, int]] = []

    monkeypatch.setenv("LLM_PRIMARY_TIMEOUT_SEC", "7")
    monkeypatch.setenv("LLM_FALLBACK_TIMEOUT_SEC", "55")

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        seen.append((request.full_url, timeout))
        if request.full_url == "http://primary.local/v1/chat/completions":
            return _StubHttpResponse({"choices": [{"message": {"content": "not-json"}}]})
        return _StubHttpResponse({"choices": [{"message": {"content": "{\"from\":\"fallback\"}"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json("hello")
    assert payload == {"from": "fallback"}
    assert path == "fallback"
    assert seen == [
        ("http://primary.local/v1/chat/completions", 7),
        ("http://ollama:11434/v1/chat/completions", 55),
    ]


def test_provider_router_retries_primary_on_transient_timeout(monkeypatch):
    primary = LLMEndpoint(url="http://primary.local", model="test-model", api_key="")
    router = LLMProviderRouter(primary=primary, fallback=None)
    seen_calls = {"count": 0}

    monkeypatch.setenv("LLM_PRIMARY_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("LLM_PRIMARY_RETRY_DELAY_MS", "0")

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        seen_calls["count"] += 1
        if seen_calls["count"] == 1:
            raise TimeoutError("timed out")
        return _StubHttpResponse({"choices": [{"message": {"content": "{\"from\":\"primary\"}"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json("hello")
    assert payload == {"from": "primary"}
    assert path == "primary"
    assert seen_calls["count"] == 2


def test_provider_router_retries_ollama_with_rescue_model(monkeypatch):
    fallback = LLMEndpoint(url="http://ollama:11434", model="qwen2.5:3b", api_key="")
    router = LLMProviderRouter(primary=None, fallback=fallback)
    seen_models: list[str] = []

    monkeypatch.setenv("LLM_FALLBACK_RESCUE_MODEL", "qwen2.5:0.5b")

    def fake_urlopen(request, timeout=12):  # noqa: ARG001
        body = json.loads(request.data.decode("utf-8"))
        model = str(body.get("model") or "")
        seen_models.append(model)
        if model == "qwen2.5:3b":
            raise TimeoutError("timed out")
        return _StubHttpResponse({"choices": [{"message": {"content": "{\"from\":\"rescue\"}"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload, path = router.generate_json("hello")
    assert payload == {"from": "rescue"}
    assert path == "fallback"
    assert seen_models == ["qwen2.5:3b", "qwen2.5:0.5b"]
