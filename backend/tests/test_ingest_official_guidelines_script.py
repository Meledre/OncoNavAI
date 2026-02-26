from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_ingest_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "ingest_official_guidelines.py"
    spec = importlib.util.spec_from_file_location("onco_ingest_official_guidelines_test_module", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/ingest_official_guidelines.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, *, status: int = 200, body: str = "{}") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        _ = exc_type, exc, tb
        return False


def test_request_json_handles_timeout_error(monkeypatch: Any) -> None:
    module = _load_ingest_module()

    def _raise_timeout(*_args: Any, **_kwargs: Any) -> _FakeResponse:
        raise TimeoutError("timed out")

    monkeypatch.setattr(module.urllib.request, "urlopen", _raise_timeout)

    status, body = module._request_json(
        base_url="http://localhost:8000",
        endpoint="/admin/docs",
        method="GET",
        token="demo-token",
        role="admin",
        payload=None,
    )

    assert status == 0
    assert "timed out" in str(body.get("error") or "").lower()


def test_request_json_uses_configurable_timeout(monkeypatch: Any) -> None:
    module = _load_ingest_module()
    captured: dict[str, Any] = {}

    def _fake_urlopen(_request: Any, timeout: float = 0.0) -> _FakeResponse:
        captured["timeout"] = float(timeout)
        return _FakeResponse(status=200, body="{}")

    monkeypatch.setenv("ONCO_INGEST_HTTP_TIMEOUT_SEC", "123")
    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)

    status, body = module._request_json(
        base_url="http://localhost:8000",
        endpoint="/admin/docs",
        method="GET",
        token="demo-token",
        role="admin",
        payload=None,
    )

    assert status == 200
    assert isinstance(body, dict)
    assert captured["timeout"] == 123.0
