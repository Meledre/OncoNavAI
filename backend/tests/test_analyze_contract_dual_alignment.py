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
        rate_limit_per_minute=50,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
        reasoning_mode="compat",
        oncoai_doctor_schema_v1_2_enabled=True,
        oncoai_casefacts_enabled=True,
        oncoai_prompt_schema_strict=False,
        oncoai_compat_v1_1_projection_enabled=True,
    )


def build_pack_request() -> dict[str, object]:
    return {
        "schema_version": "0.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "query_type": "CHECK_LAST_TREATMENT",
        "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
        "language": "ru",
        "case": {
            "case_json": {
                "schema_version": "1.0",
                "case_id": "9864b343-6a61-53b3-8e8c-3854d7e99452",
                "import_profile": "FREE_TEXT",
                "patient": {"sex": "male", "birth_year": 1973},
                "diagnoses": [
                    {
                        "diagnosis_id": "10db35a3-dd32-52a7-896b-afb323c197b7",
                        "disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e",
                        "icd10": "C16",
                        "histology": "adenocarcinoma",
                        "stage": {"system": "TNM8", "stage_group": "IV"},
                        "biomarkers": [
                            {"name": "HER2", "value": "positive"},
                            {"name": "PD-L1_CPS", "value": "10"},
                        ],
                        "timeline": [
                            {
                                "event_id": "ae0ba38a-e199-5ad1-8e01-11b77d25b423",
                                "date": "2026-01-05",
                                "precision": "day",
                                "type": "systemic_therapy",
                                "label": "Начата 1-я линия",
                                "details": "mFOLFOX6",
                            }
                        ],
                        "last_plan": {
                            "date": "2026-02-10",
                            "precision": "day",
                            "regimen": "mFOLFOX6",
                            "line": 1,
                            "cycle": 3,
                        },
                    }
                ],
                "attachments": [],
                "notes": "Кейс-демо: желудок, метастатический процесс.",
            }
        },
        "options": {"strict_evidence": True, "max_chunks": 20, "max_citations": 20, "timeout_ms": 120000},
    }


def test_analyze_response_passes_dual_contract_projection_validation(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    response = service.analyze(payload=build_pack_request(), role="clinician", client_id="dual-alignment")

    result = service.admin_validate_contract_projections(
        role="admin",
        payload={
            "response": response,
            "include_projection": False,
        },
    )

    assert result["status"] == "ok"
    assert result["compatibility"]["doctor_report_v1_1"]["valid"] is True
    assert result["compatibility"]["patient_explain_alt"]["valid"] is True
