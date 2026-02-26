from __future__ import annotations

from pathlib import Path


def _doctor_page() -> str:
    return (Path(__file__).resolve().parents[2] / "frontend" / "app" / "doctor" / "page.tsx").read_text()


def _doctor_progress_component() -> str:
    return (
        Path(__file__).resolve().parents[2] / "frontend" / "components" / "doctor" / "DoctorProgressSteps.tsx"
    ).read_text()


def _doctor_nav_component() -> str:
    return (Path(__file__).resolve().parents[2] / "frontend" / "components" / "doctor" / "DoctorSectionNav.tsx").read_text()


def _doctor_consilium_component() -> str:
    return (
        Path(__file__).resolve().parents[2] / "frontend" / "components" / "doctor" / "DoctorConsiliumCard.tsx"
    ).read_text()


def test_doctor_page_has_release_navigation_and_section_anchors() -> None:
    page = _doctor_page()
    nav_component = _doctor_nav_component()
    assert "DoctorSectionNav" in page
    assert "doctor-sections" in nav_component
    assert 'href={`#${section.id}`}' in nav_component
    assert '{ id: "loaded-data"' in page
    assert '{ id: "diagnosis"' in page
    assert '{ id: "summary"' in page
    assert '{ id: "drug-timeline"' in page
    assert '{ id: "diag-timeline"' in page
    assert '{ id: "therapy"' in page
    assert '{ id: "plan"' in page
    assert '{ id: "issues"' in page
    assert '{ id: "drug-safety"' in page
    assert '{ id: "citations"' in page
    assert 'label: "Загруженные данные"' in page


def test_doctor_page_has_progress_steps_and_data_testids() -> None:
    page = _doctor_page()
    progress = _doctor_progress_component()
    consilium_component = _doctor_consilium_component()
    assert "DoctorProgressSteps" in page
    assert "Импорт" in progress
    assert "Анализ" in progress
    assert "Формирование отчёта" in progress
    assert 'data-testid="doctor-section-timeline"' in page
    assert 'data-testid="doctor-section-issues"' in page
    assert 'data-testid="doctor-section-drug-safety"' in page
    assert 'data-testid="doctor-section-citations"' in page
    assert "setDrugTimelineMode" in page
    assert "setDiagTimelineMode" in page
    assert "doctor-collapsible" in consilium_component
