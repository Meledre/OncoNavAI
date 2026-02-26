from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.exceptions import AuthorizationError
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
        reasoning_mode="compat",
    )


def test_analyze_deid_auto_redacts_pii_and_continues(tmp_path):
    service = OncoService(make_settings(tmp_path))
    payload = {
        "schema_version": "0.1",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "notes": "Пациент Иван Иванов, email a@b.com, телефон +7 (999) 123-45-67",
            "data_mode": "DEID",
        },
        "treatment_plan": {"plan_text": "osimertinib"},
    }
    response = service.analyze(payload=payload, role="clinician", client_id="c1")
    assert response["doctor_report"]["schema_version"] == "0.1"
    assert isinstance(response["doctor_report"]["issues"], list)


def test_admin_docs_forbidden_for_clinician(tmp_path):
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(AuthorizationError):
        service.admin_docs(role="clinician")


def test_admin_reindex_status_forbidden_for_clinician(tmp_path):
    service = OncoService(make_settings(tmp_path))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"synthetic guideline",
        metadata={
            "doc_id": "g1",
            "doc_version": "v1",
            "source_set": "s1",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
        },
    )
    result = service.admin_reindex(role="admin")
    with pytest.raises(AuthorizationError):
        service.admin_reindex_status(role="clinician", job_id=result["job_id"])
