from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
from backend.app.service import OncoService


def make_settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=100,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
    )


def test_health_includes_vector_preflight_snapshot_for_local_backend(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = service.health()

    assert payload["status"] == "ok"
    assert payload["vector_preflight"]["backend"] == "local"
    assert payload["vector_preflight"]["status"] == "not_applicable"
