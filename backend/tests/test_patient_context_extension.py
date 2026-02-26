from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_backend_patient_analyze_response_supports_optional_patient_context() -> None:
    service_text = (_repo_root() / "backend" / "app" / "service.py").read_text()
    builder_text = (_repo_root() / "backend" / "app" / "reporting" / "patient_context_builder.py").read_text()
    assert "build_patient_context_from_analyze_response" in service_text
    assert 'response["patient_context"] = patient_context' in service_text
    assert "def build_patient_context_from_analyze_response" in builder_text
    assert '"diagnosis"' in builder_text
    assert '"comorbidities"' in builder_text
    assert '"therapy_timeline"' in builder_text
    assert '"diagnostics_timeline"' in builder_text
    assert '"current_therapy"' in builder_text
    assert '"upcoming_actions"' in builder_text


def test_frontend_contracts_and_patient_page_use_patient_context_extension() -> None:
    frontend_root = _repo_root() / "frontend"
    types_text = (frontend_root / "lib" / "contracts" / "types.ts").read_text()
    validate_text = (frontend_root / "lib" / "contracts" / "validate.ts").read_text()
    patient_page = (frontend_root / "app" / "patient" / "page.tsx").read_text()
    assert "export type PatientContext" in types_text
    assert "normalizePatientContext" in validate_text
    assert "patient_context" in patient_page
    assert "normalizePatientContext" in patient_page
