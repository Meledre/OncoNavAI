from __future__ import annotations

from pathlib import Path


def _frontend_root() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend"


def test_doctor_page_renders_release_v1_2_blocks_without_legacy_debug_sections() -> None:
    doctor_page = (_frontend_root() / "app" / "doctor" / "page.tsx").read_text()
    assert "consilium_md" in doctor_page
    assert "contextView.upcoming_actions" in doctor_page
    assert "doctor_report.citations" in doctor_page
    assert "doctor_report.drug_safety" in doctor_page
    assert 'data-testid="doctor-layout"' in doctor_page
    assert 'testId="doctor-section-nav"' in doctor_page
    assert 'testId="doctor-progress-steps"' in doctor_page
    assert 'data-testid="doctor-section-loaded-data"' in doctor_page
    assert 'id="plan"' in doctor_page
    assert "Ключевые клинические данные" not in doctor_page
    assert "Проверки согласованности" not in doctor_page
    assert "Загруженные данные" in doctor_page
    assert "missing_data" not in doctor_page
    assert "questions_to_ask_doctor" not in doctor_page


def test_patient_page_is_ru_only_and_uses_patient_safe_v1_2_fields() -> None:
    patient_page = (_frontend_root() / "app" / "patient" / "page.tsx").read_text()
    assert 'language: "ru"' in patient_page
    assert 'value="en"' not in patient_page
    assert "summary_plain" in patient_page
    assert "questions_for_doctor" in patient_page
    assert "safety_notes" in patient_page
    assert "drug_safety" in patient_page
    assert "doctor_report" in patient_page
    assert "patient_context" in patient_page
    assert 'data-testid="patient-layout"' in patient_page
    assert 'testId="patient-card-summary"' in patient_page
    assert 'testId="patient-card-questions"' in patient_page
    assert 'testId="patient-card-safety"' in patient_page
