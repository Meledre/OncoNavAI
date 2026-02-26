from __future__ import annotations

from pathlib import Path


def test_onco_cli_includes_demo_local_and_api_smoke_commands() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()

    assert "demo-local-smoke       Run demo smoke with .env.demo.local profile (local LLM stack)" in text
    assert "demo-api-smoke         Run demo smoke with .env.demo.api profile (API stack)" in text
    assert "demo-local-smoke) cmd_demo_local_smoke ;;" in text
    assert "demo-api-smoke) cmd_demo_api_smoke ;;" in text
    assert ".env.demo.local" in text
    assert ".env.demo.api" in text
    assert "apply_demo_profile_stack local" in text
    assert "apply_demo_profile_stack api" in text
    assert "configure_demo_data_scope" in text
