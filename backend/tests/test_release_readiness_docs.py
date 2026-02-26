from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_release_readiness_runbook_exists_with_required_sections() -> None:
    runbook = _repo_root() / "docs" / "deploy" / "release_readiness_runbook.md"
    text = runbook.read_text()

    assert "# OncoAI Release Readiness Runbook" in text
    assert "## Rollback Plan" in text
    assert "## SLO and Alert Checklist" in text
    assert "./onco preflight" in text
    assert "./onco incident-check" in text
    assert "./onco security-check" in text
    assert "./onco release-readiness" in text
    assert "NEXT_PUBLIC_ONCOAI_DOCTOR_REPORT_1_0_COMPAT_ENABLED" in text


def test_freeze_and_regression_docs_reference_release_readiness() -> None:
    freeze = (_repo_root() / "docs" / "cap" / "v0_4_bridge_freeze_summary.md").read_text()
    checklist = (_repo_root() / "docs" / "qa" / "regression_checklist.md").read_text()

    assert "release readiness" in freeze.lower() or "release-readiness" in freeze
    assert "security-check" in checklist
    assert "release-readiness" in checklist
