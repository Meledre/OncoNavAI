from __future__ import annotations

from typing import Any


def normalize_plan(plan_text: str, existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if existing:
        return existing

    plan_text = plan_text.strip()
    if not plan_text:
        return []

    steps = []
    for line in plan_text.splitlines():
        line = line.strip(" -")
        if not line:
            continue
        low = line.lower()
        if any(token in low for token in ("диаг", "diagn", "кт", "mri", "биопс")):
            step_type = "diagnostic"
        elif any(token in low for token in ("терап", "therapy", "хими", "осимертиниб", "immuno")):
            step_type = "systemic_therapy"
        elif "операц" in low or "surgery" in low:
            step_type = "surgery"
        elif "radi" in low or "луч" in low:
            step_type = "radiation"
        else:
            step_type = "other"
        steps.append({"step_type": step_type, "name": line})

    if not steps:
        steps.append({"step_type": "other", "name": plan_text[:120]})
    return steps
