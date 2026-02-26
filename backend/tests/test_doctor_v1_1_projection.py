from __future__ import annotations

from backend.app.reporting.compat_doctor_v1_1 import project_doctor_report_v1_1, validate_doctor_projection_v1_1


def test_doctor_v1_1_projection_from_canonical_v1_2_payload() -> None:
    doctor_v1_2 = {
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
        "timeline": [
            {
                "date": "2025-01-15",
                "type": "systemic_therapy",
                "label": "1-я линия XELOX",
                "details": "Прогрессирование",
            }
        ],
        "consilium_md": "## Ключевые клинические факты\n- TNM/стадия: pT3N2M0",
        "plan": [
            {
                "section": "treatment",
                "title": "Тактика",
                "steps": [
                    {
                        "step_id": "a6e1cb0b-9e8a-4578-8308-82b25b73f381",
                        "text": "Рассмотреть 3-ю линию с учётом переносимости.",
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
                "summary": "Требуется уточнить ECOG.",
                "details": "Нет функционального статуса в кейсе.",
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
    }
    run_meta = {"kb_version": "kb_2026_02_22", "routing_meta": {"resolved_cancer_type": "gastric_cancer"}}
    insufficient_data = {"status": True, "reason": "Нужно уточнить ECOG."}

    projection = project_doctor_report_v1_1(
        doctor_report_v1_2=doctor_v1_2,
        run_meta=run_meta,
        insufficient_data=insufficient_data,
    )

    errors = validate_doctor_projection_v1_1(projection)
    assert errors == []
    assert projection["schema_version"] == "1.1"
    assert projection["disease_context"]["cancer_type"] == "gastric_cancer"
    assert projection["current_plan"]["description"] != ""
    assert isinstance(projection["issues"], list)
    assert isinstance(projection["missing_data"], list)
