from __future__ import annotations

from backend.app.rules.min_case_requirements import evaluate_min_case_requirements


def test_min_case_requirements_pass_for_complete_breast_case() -> None:
    result = evaluate_min_case_requirements(
        case_json={
            "patient": {"ecog": 1},
            "diagnoses": [
                {
                    "icd10": "C50.9",
                    "histology": "invasive ductal carcinoma",
                    "stage": {"stage_group": "IV"},
                    "timeline": [{"date": "2026-01-01", "type": "therapy"}],
                    "last_plan": {"line": 2},
                    "biomarkers": [
                        {"name": "ER", "value": "positive"},
                        {"name": "PR", "value": "positive"},
                        {"name": "HER2", "value": "negative"},
                        {"name": "Ki-67", "value": "high"},
                    ],
                }
            ],
        },
        case_facts={
            "biomarkers": {"er": "positive", "pr": "positive", "her2": "negative", "ki67": "high"},
            "case_facts_v2": {
                "patient": {"ecog": 1},
                "labs": [
                    {"name": "hemoglobin", "value": "124"},
                    {"name": "neutrophils", "value": "3.1"},
                    {"name": "platelets", "value": "232"},
                    {"name": "creatinine", "value": "73"},
                    {"name": "bilirubin", "value": "9"},
                ],
            },
            "current_stage": {"stage_group": "IV"},
            "treatment_history": [{"line": 1}],
        },
        disease_context={"icd10": "C50", "line": 2},
        case_payload={"cancer_type": "breast"},
        routing_meta={"resolved_cancer_type": "breast"},
    )
    assert result["status"] is False
    assert result["completeness"] == 1.0
    assert result["missing_critical_fields"] == []


def test_min_case_requirements_flags_missing_when_key_fields_absent() -> None:
    result = evaluate_min_case_requirements(
        case_json={
            "patient": {"ecog": None},
            "diagnoses": [{"icd10": "C64", "stage": {}, "biomarkers": []}],
        },
        case_facts={"case_facts_v2": {"patient": {}, "labs": []}},
        disease_context={"icd10": "C64"},
        case_payload={"cancer_type": "rcc"},
        routing_meta={"resolved_cancer_type": "rcc"},
    )
    assert result["status"] is True
    assert result["completeness"] < 1.0
    assert any(str(item).startswith("biomarker:") for item in result["missing_critical_fields"])


def test_min_case_requirements_marks_ambiguous_brain_scope() -> None:
    result = evaluate_min_case_requirements(
        case_json={},
        case_facts={},
        disease_context={},
        case_payload={"cancer_type": "brain"},
        routing_meta={"match_strategy": "ambiguous_brain_scope"},
    )
    assert result["status"] is True
    assert "brain_scope_icd10" in result["missing_critical_fields"]
