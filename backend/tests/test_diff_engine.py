from __future__ import annotations

from backend.app.rules.diff_engine import compute_diff


def test_compute_diff_for_next_steps_requires_diagnostics_and_staging() -> None:
    issues = compute_diff(
        "gastric_cancer",
        [{"step_type": "systemic_therapy", "name": "trastuzumab + chemotherapy"}],
        query_type="NEXT_STEPS",
    )
    titles = [item.title for item in issues]
    assert any("diagnostic_confirmation" in title for title in titles)
    assert any("staging" in title for title in titles)


def test_compute_diff_for_check_last_treatment_does_not_require_diagnostics() -> None:
    issues = compute_diff(
        "gastric_cancer",
        [{"step_type": "systemic_therapy", "name": "trastuzumab + chemotherapy"}],
        query_type="CHECK_LAST_TREATMENT",
    )
    titles = [item.title for item in issues]
    assert all("diagnostic_confirmation" not in title for title in titles)
