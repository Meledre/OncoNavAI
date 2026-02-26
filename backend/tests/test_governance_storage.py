from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
from backend.app.service import OncoService
from backend.app.storage import SQLiteStore


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


def test_storage_exposes_governance_lists(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "governance.sqlite3")
    assert store.list_guideline_sources() == []
    assert store.list_guideline_documents() == []
    assert store.list_guideline_versions() == []


def test_service_bootstraps_seeded_governance_registry(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    docs_payload = service.admin_docs(role="admin")

    governance = docs_payload.get("governance")
    assert isinstance(governance, dict)
    assert governance.get("sources_total", 0) >= 1
    assert governance.get("disease_registry_total", 0) >= 1
    assert isinstance(governance.get("sources"), list)
    assert isinstance(governance.get("disease_registry"), list)

