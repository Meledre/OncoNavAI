from __future__ import annotations

from pathlib import Path


def _frontend_root() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend"


def test_layout_uses_editorial_fonts_and_shell() -> None:
    layout = (_frontend_root() / "app" / "layout.tsx").read_text()
    assert "Cormorant_Garamond" in layout
    assert "Space_Mono" in layout
    assert "Manrope" in layout
    assert "app-shell" in layout
    assert "OncoShell" in layout


def test_globals_define_premium_editorial_tokens() -> None:
    css = (_frontend_root() / "app" / "globals.css").read_text()
    assert "--bg-deep" in css
    assert "--accent-bronze" in css
    assert "--accent-glow" in css
    assert "page-enter" in css
    assert ".app-container" in css
    assert ".sidebar" in css
    assert ".theme-toggle" in css
    assert ".section-nav" in css
    assert ".progress-steps" in css
    assert ".tabs-list" in css


def test_shell_avoids_ssr_nondeterminism_sources() -> None:
    ambient = (_frontend_root() / "components" / "shell" / "AmbientLayers.tsx").read_text()
    doctor_page = (_frontend_root() / "app" / "doctor" / "page.tsx").read_text()
    patient_page = (_frontend_root() / "app" / "patient" / "page.tsx").read_text()

    assert "Math.random" not in ambient
    assert "useState<string>(`doctor-${Date.now()}`)" not in doctor_page
    assert "useState<string>(`patient-${Date.now()}`)" not in patient_page
