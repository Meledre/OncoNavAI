from __future__ import annotations

from pathlib import Path


def _patient_page() -> str:
    return (Path(__file__).resolve().parents[2] / "frontend" / "app" / "patient" / "page.tsx").read_text()


def test_patient_page_uses_compact_release_cards() -> None:
    page = _patient_page()
    assert "PatientSummaryCard" in page
    assert "PatientQuestionsCard" in page
    assert "PatientSafetyCard" in page
    assert 'testId="patient-card-summary"' in page
    assert 'testId="patient-card-questions"' in page
    assert 'testId="patient-card-safety"' in page


def test_patient_page_remains_patient_safe_and_ru_only() -> None:
    page = _patient_page()
    assert "doctor_report" in page
    assert "Техническая ошибка: в пациентском ответе обнаружен doctor_report." in page
    assert "Режим пациента" in page
    assert "Получить объяснение" in page
