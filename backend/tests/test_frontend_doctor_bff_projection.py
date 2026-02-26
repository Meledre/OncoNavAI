from __future__ import annotations

from pathlib import Path


def _frontend_root() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend"


def test_doctor_bff_route_merges_analyze_and_case_context() -> None:
    route = (_frontend_root() / "app" / "api" / "doctor" / "analyze" / "route.ts").read_text()
    assert "resolveSessionFromRequest" in route
    assert "rotateSessionFromRefresh" in route
    assert "session.role === \"admin\" || session.role === \"clinician\"" in route
    assert "path: \"/analyze\"" in route
    assert "path: `/case/${encodeURIComponent(caseId)}`" in route
    assert "doctor_context_view" in route
    assert "context_meta" in route
    assert "case_lookup_ok" in route


def test_doctor_projection_viewmodel_contains_release_blocks() -> None:
    viewmodel = (_frontend_root() / "lib" / "viewmodels" / "doctor.ts").read_text()
    types = (_frontend_root() / "lib" / "viewmodels" / "types.ts").read_text()
    assert "projectDoctorContextView" in viewmodel
    assert "therapy_timeline" in viewmodel
    assert "diagnostics_timeline" in viewmodel
    assert "current_therapy" in viewmodel
    assert "upcoming_actions" in viewmodel
    assert "counters" in viewmodel
    assert "DoctorContextView" in types
    assert "DoctorAnalyzeBffResponse" in types


def test_doctor_page_uses_new_doctor_bff_endpoint() -> None:
    page = (_frontend_root() / "app" / "doctor" / "page.tsx").read_text()
    assert "/api/doctor/analyze" in page
    assert "doctor_context_view" in page
    assert "context_meta" in page
    assert "normalizeDoctorContext" in page
