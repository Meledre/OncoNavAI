from __future__ import annotations

from backend.app.reporting.patient_context_builder import build_patient_context_from_analyze_response


def test_patient_context_builder_extracts_safe_structured_fields() -> None:
    analyze_response = {
        "doctor_report": {
            "disease_context": {
                "diagnosis_name": "Рак молочной железы",
                "icd10": "C50.1",
                "stage": "I-B",
                "biomarkers": {"ER": "positive", "PR": "positive", "HER2": "negative"},
            },
            "case_facts": {
                "comorbidities": [
                    {"name": "Гипертония", "code": "I10", "status": "контролируемая"},
                    {"name": "Сахарный диабет 2 типа", "code": "E11.9"},
                ],
                "current_therapy": [
                    {"name": "Летрозол", "dose": "2.5 мг", "schedule": "ежедневно", "status": "active"},
                ],
            },
            "timeline": [
                {"date": "2024-10-22", "event": "КТ брюшной полости", "type": "diagnostics"},
                {"date": "2024-10-23", "event": "Летрозол 2.5 мг/сут", "type": "therapy"},
            ],
            "plan": [
                {
                    "section": "follow_up",
                    "steps": [
                        {"text": "Повторить КТ через 3 месяца", "priority": "high"},
                    ],
                }
            ],
        }
    }

    patient_context = build_patient_context_from_analyze_response(analyze_response)
    assert patient_context["diagnosis"]["name"] == "Рак молочной железы"
    assert patient_context["diagnosis"]["icd10"] == "C50.1"
    assert patient_context["diagnosis"]["stage"] == "I-B"
    assert len(patient_context["diagnosis"]["biomarkers"]) == 3
    assert len(patient_context["comorbidities"]) == 2
    assert len(patient_context["therapy_timeline"]) == 1
    assert len(patient_context["diagnostics_timeline"]) == 1
    assert patient_context["current_therapy"][0]["name"] == "Летрозол"
    assert patient_context["upcoming_actions"][0]["text"] == "Повторить КТ через 3 месяца"


def test_patient_context_builder_returns_empty_when_insufficient_source_data() -> None:
    assert build_patient_context_from_analyze_response({"doctor_report": {}}) == {}

