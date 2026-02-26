from __future__ import annotations

from backend.app.reporting.guided_report_builder import build_guided_report


def test_guided_report_contains_required_sections() -> None:
    payload = build_guided_report(
        query_type="NEXT_STEPS",
        disease_context={"icd10": "C16", "stage_group": "III"},
        case_facts={
            "current_stage": {"tnm": "pT3N2M0"},
            "biomarkers": {"her2": "1+", "msi_status": "MSS", "pd_l1_cps_values": [8.0]},
            "case_facts_v2": {"labs": [{"name": "creatinine", "value": 132.0}], "current_medications": []},
        },
        timeline=[{"date": "2026-02-20", "label": "Прогрессирование"}],
        plan_sections=[{"section": "treatment", "steps": [{"text": "Рассмотреть иринотекан"}]}],
        issues=[{"severity": "warning", "summary": "Нужно уточнить eGFR", "details": "Нет данных eGFR"}],
        citations=[
            {"source_id": "minzdrav", "doc_id": "minzdrav_237_6", "page_start": 12},
            {"source_id": "russco", "doc_id": "russco_2025_1_1_13", "page_start": 45},
        ],
        insufficient_data={"status": False, "reason": ""},
    )

    md = payload["doctor_summary_md"]
    assert "## Входные данные" in md
    assert "## Проверка по Минздраву" in md
    assert "## Проверка по RUSSCO" in md
    assert "## Дозировки и безопасность" in md
    assert "## Взаимодействия и коморбидности" in md
    assert "## Резюме для врача" in md
    assert "## Резюме для пациента" in md
    assert "## Источники" in md

    assert "doctor_summary_plain" in payload
    assert "patient_summary_plain" in payload
