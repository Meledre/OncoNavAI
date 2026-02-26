from __future__ import annotations

from pathlib import Path


def test_admin_page_contains_release_workflow_controls() -> None:
    page = (Path(__file__).resolve().parents[2] / "frontend" / "app" / "admin" / "page.tsx").read_text()

    # Sync actions
    assert "Sync RUSSCO" in page
    assert "Sync Минздрав" in page
    # Workflow actions
    assert "Re-chunk" in page
    assert "Approve" in page
    assert "Reject" in page
    assert "Index" in page
    assert "Verify" in page
    # Index gate
    assert 'disabled={loading || String(doc.status || "").toUpperCase() !== "APPROVED"}' in page
    # Release filters
    assert "Источник" in page
    assert "Год" in page
    assert "Статус" in page
    assert "Нозология" in page
    # Tab IA markers
    assert "tab=docs" in page
    assert "tab=references" in page
    assert "tab=sync" in page
    assert "tab=import" in page
    assert "tab=security" in page


def test_doctor_page_uses_release_sections_without_debug_headers() -> None:
    page = (Path(__file__).resolve().parents[2] / "frontend" / "app" / "doctor" / "page.tsx").read_text()
    assert "Загруженные данные" in page
    assert "Ключевые клинические данные" not in page
    assert "Проверки согласованности" not in page
    assert "Таймлайн по кейсу не извлечён." not in page
    assert 'id="timeline"' in page
    assert 'id="consilium"' in page
    assert 'id="plan"' in page
    assert 'id="issues"' in page
    assert 'id="citations"' in page
    assert "Patient explanation preview" not in page
    assert "report_id:" not in page
    assert "schema=" not in page


def test_patient_page_hides_technical_routing_details() -> None:
    page = (Path(__file__).resolve().parents[2] / "frontend" / "app" / "patient" / "page.tsx").read_text()
    assert "Получить объяснение" in page
    assert "auto-routing:" not in page
    assert "patient-card-summary" in page
    assert "patient-card-questions" in page
    assert "patient-card-safety" in page


def test_login_page_is_release_split_without_demo_tech_text() -> None:
    page = (Path(__file__).resolve().parents[2] / "frontend" / "app" / "page.tsx").read_text()
    assert "Выберите роль для входа в демо-контур" not in page
    assert "Next route after login" not in page
    assert "login-split-layout" in page
    assert "login-geometry" in page
