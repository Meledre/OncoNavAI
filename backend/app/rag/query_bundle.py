from __future__ import annotations

from typing import Any


def _push_unique(target: list[str], value: str) -> None:
    item = str(value or "").strip()
    if item and item not in target:
        target.append(item)


def _has_step(plan_sections: list[dict[str, Any]], token: str) -> bool:
    token_lc = str(token or "").strip().lower()
    if not token_lc:
        return False
    for section in plan_sections:
        if not isinstance(section, dict):
            continue
        steps = section.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "").strip().lower()
            if token_lc in text:
                return True
    return False


def build_query_bundle(
    *,
    base_query: str,
    query_type: str,
    cancer_type: str,
    case_facts: dict[str, Any],
    plan_sections: list[dict[str, Any]],
) -> list[str]:
    queries: list[str] = []
    _push_unique(queries, base_query)

    if str(query_type or "").strip().upper() != "NEXT_STEPS":
        return queries

    if str(cancer_type or "").strip().lower() != "gastric_cancer":
        return queries

    _push_unique(queries, "рак желудка 1 линия диагностика стадирование")
    _push_unique(queries, "рак желудка системная терапия по линиям")

    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    her2_mode = str(biomarkers.get("her2_interpretation") or "").strip().lower()
    if her2_mode == "positive":
        _push_unique(queries, "рак желудка HER2 positive trastuzumab 1 линия")
    else:
        _push_unique(queries, "рак желудка HER2 negative системная терапия")

    if isinstance(biomarkers.get("pd_l1_cps_values"), list) and biomarkers.get("pd_l1_cps_values"):
        _push_unique(queries, "рак желудка PD-L1 CPS иммунотерапия критерии")

    msi_status = str(biomarkers.get("msi_status") or "").strip().lower()
    if msi_status in {"msi-h", "dmmr"}:
        _push_unique(queries, "рак желудка MSI-H dMMR иммунотерапия")

    cldn_status = str(biomarkers.get("cldn18_2_interpretation") or "").strip().lower()
    if cldn_status == "positive" or biomarkers.get("cldn18_2_percent") is not None:
        _push_unique(queries, "CLDN18.2 zolbetuximab SPOTLIGHT GLOW gastric")

    if _has_step(plan_sections, "post-progression") or _has_step(plan_sections, "прогресс"):
        _push_unique(queries, "рак желудка post-progression после ramucirumab paclitaxel")

    return queries
