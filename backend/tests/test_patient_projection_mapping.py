from __future__ import annotations

from backend.app.reporting.compat_patient_projection import (
    project_patient_explain_alt_profile,
    validate_patient_projection_alt,
)


def test_patient_projection_mapping_from_canonical_v1_2_payload() -> None:
    patient_v1_2 = {
        "schema_version": "1.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "summary_plain": "Проверка выполнена. Есть пункты для обсуждения с лечащим врачом.",
        "key_points": ["Нужно уточнить биомаркеры.", "Текущая тактика требует обсуждения на консилиуме."],
        "questions_for_doctor": ["Какие анализы сдать в первую очередь?"],
        "what_was_checked": ["План лечения сопоставлен с клиническими рекомендациями."],
        "safety_notes": ["Этот текст носит информационный характер и не заменяет консультацию врача."],
        "sources_used": ["minzdrav", "russco"],
        "generated_at": "2026-02-22T12:00:00Z",
    }
    doctor_v1_2 = {
        "report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
        "disease_context": {"stage_group": "IV", "setting": "metastatic"},
        "consilium_md": "## Клинический контекст\n- рак желудка",
    }

    projection = project_patient_explain_alt_profile(
        patient_v1_2=patient_v1_2,
        doctor_report_v1_2=doctor_v1_2,
    )
    errors = validate_patient_projection_alt(projection)

    assert errors == []
    assert projection["schema_version"] == "1.2"
    assert projection["request_id"] == patient_v1_2["request_id"]
    assert projection["based_on_report_id"] == doctor_v1_2["report_id"]
    assert projection["overall_interpretation"] == patient_v1_2["summary_plain"]
    assert projection["safety_note"] == patient_v1_2["safety_notes"][0]
