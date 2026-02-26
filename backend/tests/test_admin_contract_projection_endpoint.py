from __future__ import annotations

from datetime import datetime, timezone
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
        rate_limit_per_minute=30,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
    )


def _sample_response() -> dict[str, object]:
    return {
        "schema_version": "0.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "doctor_report": {
            "schema_version": "1.2",
            "report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "query_type": "NEXT_STEPS",
            "disease_context": {
                "disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e",
                "icd10": "C16",
                "stage_group": "IV",
                "setting": "metastatic",
                "line": 2,
                "biomarkers": [{"name": "HER2", "value": "1+"}],
            },
            "case_facts": {"current_stage": {"tnm": "pT3N2M0", "stage_group": "IV"}},
            "timeline": [{"date": "2026-01-01", "type": "systemic_therapy", "label": "1-я линия"}],
            "consilium_md": "## Ключевые клинические факты\n- TNM/стадия: pT3N2M0",
            "plan": [
                {
                    "section": "treatment",
                    "steps": [
                        {
                            "step_id": "a6e1cb0b-9e8a-4578-8308-82b25b73f381",
                            "text": "Продолжить лечение после дообследования.",
                            "priority": "high",
                            "citation_ids": ["83b5c681-3a75-5a79-8186-9d3b7496f5cb"],
                        }
                    ],
                }
            ],
            "issues": [
                {
                    "issue_id": "c8c20cf0-a459-4411-b2bf-c17370512f3b",
                    "severity": "warning",
                    "kind": "missing_data",
                    "summary": "Требуется ECOG.",
                    "details": "Нет ECOG в кейсе.",
                    "field_path": "patient.ecog",
                    "citation_ids": ["83b5c681-3a75-5a79-8186-9d3b7496f5cb"],
                }
            ],
            "sanity_checks": [],
            "citations": [
                {
                    "citation_id": "83b5c681-3a75-5a79-8186-9d3b7496f5cb",
                    "source_id": "minzdrav",
                    "document_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "version_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "page_start": 1,
                    "page_end": 1,
                    "file_uri": "about:blank",
                }
            ],
            "generated_at": "2026-02-22T12:00:00Z",
        },
        "patient_explain": {
            "schema_version": "1.2",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "summary_plain": "Проверка выполнена, есть вопросы для обсуждения.",
            "key_points": ["Нужно уточнить ECOG."],
            "questions_for_doctor": ["Какие анализы нужно сдать?"],
            "what_was_checked": ["План лечения сопоставлен с рекомендациями."],
            "safety_notes": ["Этот текст носит информационный характер и не заменяет консультацию врача."],
            "sources_used": ["minzdrav"],
            "generated_at": "2026-02-22T12:00:00Z",
        },
        "run_meta": {
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "schema_version": "0.2",
            "timings_ms": {"total": 10, "retrieval": 2, "llm": 4, "postprocess": 4},
            "docs_retrieved_count": 0,
            "docs_after_filter_count": 0,
            "citations_count": 1,
            "evidence_valid_ratio": 1.0,
            "retrieval_engine": "basic",
            "llm_path": "deterministic",
            "vector_backend": "local",
            "embedding_backend": "hash",
            "reranker_backend": "lexical",
            "report_generation_path": "deterministic_only",
            "fallback_reason": "none",
            "kb_version": "kb_2026_02_22",
            "routing_meta": {"resolved_cancer_type": "gastric_cancer"},
        },
        "insufficient_data": {"status": True, "reason": "Нужно уточнить ECOG."},
    }


def test_admin_validate_contract_projections_accepts_response_payload(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    result = service.admin_validate_contract_projections(
        role="admin",
        payload={"response": _sample_response(), "include_projection": False},
    )
    assert result["status"] == "ok"
    assert result["compatibility"]["doctor_report_v1_1"]["valid"] is True
    assert result["compatibility"]["patient_explain_alt"]["valid"] is True


def test_admin_validate_contract_projections_accepts_report_id_lookup(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    response = _sample_response()
    report_id = str(response["doctor_report"]["report_id"])
    service.store.save_report(
        report_id=report_id,
        payload=response,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    result = service.admin_validate_contract_projections(
        role="admin",
        payload={"report_id": report_id, "include_projection": False},
    )
    assert result["status"] == "ok"
    assert result["report_id"] == report_id
