from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiffIssue:
    severity: str
    category: str
    title: str
    description: str


EXPECTED_STEPS_BY_CANCER_TYPE: dict[str, list[str]] = {
    "nsclc_egfr": ["diagnostic_confirmation", "staging", "systemic_therapy"],
    "breast_hr+/her2-": ["diagnostic_confirmation", "staging", "systemic_therapy"],
    "gastric_cancer": ["diagnostic_confirmation", "staging", "systemic_therapy"],
    "colorectal_cancer": ["diagnostic_confirmation", "staging", "systemic_therapy"],
    "ovarian_cancer": ["diagnostic_confirmation", "staging", "systemic_therapy"],
    "prostate_cancer": ["diagnostic_confirmation", "staging", "systemic_therapy"],
    "unknown": ["diagnostic_confirmation", "systemic_therapy"],
}


def _step_to_key(step: dict[str, Any]) -> str:
    step_type = str(step.get("step_type", "")).strip().lower()
    name = str(step.get("name", "")).strip().lower()
    if "diagn" in step_type or "diagn" in name:
        return "diagnostic_confirmation"
    if step_type in {"staging", "stage"} or "стад" in name or "stage" in name:
        return "staging"
    if step_type in {"systemic_therapy", "treatment"} or "therapy" in name or "терап" in name:
        return "systemic_therapy"
    return "other"


def compute_diff(
    cancer_type: str,
    plan_structured: list[dict[str, Any]],
    *,
    query_type: str = "NEXT_STEPS",
) -> list[DiffIssue]:
    expected = EXPECTED_STEPS_BY_CANCER_TYPE.get(cancer_type, EXPECTED_STEPS_BY_CANCER_TYPE["unknown"])
    if str(query_type or "").strip().upper() == "CHECK_LAST_TREATMENT":
        expected = [item for item in expected if item == "systemic_therapy"]
    got = {_step_to_key(step) for step in plan_structured}

    issues: list[DiffIssue] = []
    for expected_step in expected:
        if expected_step not in got:
            severity = "important" if expected_step in {"diagnostic_confirmation", "staging"} else "note"
            issues.append(
                DiffIssue(
                    severity=severity,
                    category="data_quality" if expected_step in {"diagnostic_confirmation", "staging"} else "other",
                    title=f"Missing expected step: {expected_step}",
                    description=(
                        "Treatment plan does not explicitly include a step required for confident protocol validation."
                    ),
                )
            )

    if not plan_structured:
        issues.append(
            DiffIssue(
                severity="critical",
                category="data_quality",
                title="Empty treatment plan",
                description="No structured treatment steps were extracted from plan_text.",
            )
        )

    return issues
