from __future__ import annotations

from pathlib import Path


def test_pdf_pack_shadow_nightly_workflow_is_non_blocking_full_run() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pdf-pack-shadow-nightly.yml"
    text = workflow.read_text()

    assert "name: PDF Pack Shadow Nightly" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "cron:" in text
    assert "continue-on-error: true" in text
    assert "sample-mode \"full\"" in text
    assert "python3 scripts/eval_pdf_pack.py" in text
    assert "zip not found" in text
    assert "::warning title=PDF pack missing" in text
    assert "if-no-files-found: warn" in text
