from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.exceptions import ValidationError
from backend.app.service import OncoService


def _make_settings(
    root: Path,
    *,
    vector_backend: str = "local",
    qdrant_url: str = "",
) -> Settings:
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
        vector_backend=vector_backend,
        qdrant_url=qdrant_url,
        qdrant_collection="oncoai_chunks",
    )


def _upload(service: OncoService, doc_id: str, doc_version: str = "2025") -> None:
    service.admin_upload(
        role="admin",
        filename=f"{doc_id}.pdf",
        content=b"%PDF-1.4 verify index test",
        metadata={
            "doc_id": doc_id,
            "doc_version": doc_version,
            "source_set": "russco",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "source_url": f"https://rosoncoweb.ru/standarts/RUSSCO/2025/{doc_id}.pdf",
            "doc_kind": "guideline",
        },
    )


def test_admin_doc_verify_index_returns_chunk_and_vector_counts(tmp_path: Path) -> None:
    service = OncoService(_make_settings(tmp_path, vector_backend="local"))
    _upload(service, "russco_2025_1_1_13")
    service.admin_doc_rechunk(role="admin", doc_id="russco_2025_1_1_13", doc_version="2025")
    service.admin_doc_approve(role="admin", doc_id="russco_2025_1_1_13", doc_version="2025")
    indexed = service.admin_doc_index(role="admin", doc_id="russco_2025_1_1_13", doc_version="2025")
    assert indexed["status"] == "INDEXED"

    verify = service.admin_doc_verify_index(role="admin", doc_id="russco_2025_1_1_13", doc_version="2025")
    assert verify["status"] == "ok"
    assert int(verify["sqlite_chunk_count"]) > 0
    assert int(verify["qdrant_point_count"]) > 0
    assert verify["vector_backend"] == "local"


def test_admin_doc_index_fails_when_qdrant_unavailable_for_verify(tmp_path: Path) -> None:
    service = OncoService(_make_settings(tmp_path, vector_backend="qdrant", qdrant_url="http://127.0.0.1:65534"))
    _upload(service, "russco_2025_1_1_12")
    service.admin_doc_rechunk(role="admin", doc_id="russco_2025_1_1_12", doc_version="2025")
    service.admin_doc_approve(role="admin", doc_id="russco_2025_1_1_12", doc_version="2025")

    with pytest.raises(ValidationError, match="INDEX_VERIFY_FAILED"):
        service.admin_doc_index(role="admin", doc_id="russco_2025_1_1_12", doc_version="2025")
