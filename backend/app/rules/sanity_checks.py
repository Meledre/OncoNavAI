from __future__ import annotations

import copy
from typing import Any


def _has_consilium_fact(consilium_md: str, token: str) -> bool:
    return token.lower() in str(consilium_md or "").lower()


def _fact_status(*, source_has: bool, target_has: bool) -> str:
    if not source_has:
        return "warn"
    return "pass" if target_has else "fail"


def run_sanity_checks(case_facts: dict[str, Any], doctor_report: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    report_case_facts = doctor_report.get("case_facts") if isinstance(doctor_report.get("case_facts"), dict) else {}
    consilium_md = str(doctor_report.get("consilium_md") or "")

    source_initial_stage = bool(case_facts.get("initial_stage"))
    target_initial_stage = bool(report_case_facts.get("initial_stage"))
    stage_present = _fact_status(source_has=source_initial_stage, target_has=target_initial_stage)
    checks.append(
        {
            "check_id": "case_facts_stage_present",
            "status": stage_present,
            "details": "initial_stage must persist from extraction into doctor_report.case_facts",
        }
    )

    source_mets = bool(case_facts.get("metastases"))
    target_mets = bool(report_case_facts.get("metastases"))
    mets_present = _fact_status(source_has=source_mets, target_has=target_mets)
    checks.append(
        {
            "check_id": "case_facts_metastases_present",
            "status": mets_present,
            "details": "metastases must persist into doctor_report.case_facts",
        }
    )

    source_treatment = bool(case_facts.get("treatment_history"))
    target_treatment = bool(report_case_facts.get("treatment_history"))
    treatment_present = _fact_status(source_has=source_treatment, target_has=target_treatment)
    checks.append(
        {
            "check_id": "case_facts_treatment_history_present",
            "status": treatment_present,
            "details": "treatment history must persist into doctor_report.case_facts",
        }
    )

    source_biomarkers = bool(case_facts.get("biomarkers"))
    target_biomarkers = bool(report_case_facts.get("biomarkers"))
    biomarkers_present = _fact_status(source_has=source_biomarkers, target_has=target_biomarkers)
    checks.append(
        {
            "check_id": "case_facts_biomarkers_present",
            "status": biomarkers_present,
            "details": "biomarkers must persist into doctor_report.case_facts",
        }
    )

    stage_token = str((case_facts.get("initial_stage") or {}).get("tnm") or "")
    consilium_stage = True if not stage_token else _has_consilium_fact(consilium_md, stage_token)
    checks.append(
        {
            "check_id": "consilium_contains_stage",
            "status": "pass" if consilium_stage else "fail",
            "details": "consilium must explicitly mention extracted stage facts",
        }
    )

    mets_tokens = [
        str(item.get("site") or "").strip()
        for item in (case_facts.get("metastases") if isinstance(case_facts.get("metastases"), list) else [])
        if isinstance(item, dict)
    ]
    if mets_tokens:
        has_any_met = any(_has_consilium_fact(consilium_md, token) for token in mets_tokens if token)
        checks.append(
            {
                "check_id": "consilium_contains_metastases",
                "status": "pass" if has_any_met else "fail",
                "details": "consilium must mention at least one extracted metastatic site.",
            }
        )

    treatment_tokens = [
        str(item.get("name") or "").strip()
        for item in (case_facts.get("treatment_history") if isinstance(case_facts.get("treatment_history"), list) else [])
        if isinstance(item, dict)
    ]
    if treatment_tokens:
        has_any_treatment = any(_has_consilium_fact(consilium_md, token) for token in treatment_tokens if token)
        checks.append(
            {
                "check_id": "consilium_contains_treatment_history",
                "status": "pass" if has_any_treatment else "fail",
                "details": "consilium must mention extracted treatment history.",
            }
        )

    return checks


def auto_repair_report(case_facts: dict[str, Any], doctor_report: dict[str, Any]) -> dict[str, Any]:
    repaired = copy.deepcopy(doctor_report)
    current = repaired.get("case_facts") if isinstance(repaired.get("case_facts"), dict) else {}

    for key in ("initial_stage", "current_stage", "metastases", "treatment_history", "biomarkers"):
        if case_facts.get(key) and not current.get(key):
            current[key] = case_facts.get(key)
    repaired["case_facts"] = current

    consilium_md = str(repaired.get("consilium_md") or "")
    additions: list[str] = []
    initial_stage = (case_facts.get("initial_stage") or {}).get("tnm")
    if initial_stage and initial_stage not in consilium_md:
        additions.append(f"- Стадия/TNM: {initial_stage}")
    for item in case_facts.get("treatment_history") or []:
        name = str((item or {}).get("name") or "").strip()
        if name and name not in consilium_md:
            additions.append(f"- Линия терапии: {name}")
    for item in case_facts.get("metastases") or []:
        site = str((item or {}).get("site") or "").strip()
        if site and site not in consilium_md:
            additions.append(f"- Метастазы: {site}")
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    her2 = str(biomarkers.get("her2") or "").strip()
    if her2 and her2 not in consilium_md:
        additions.append(f"- HER2: {her2}")
    msi = str(biomarkers.get("msi_status") or "").strip()
    if msi and msi.lower() != "unknown" and msi not in consilium_md:
        additions.append(f"- MSI/dMMR: {msi}")

    if additions:
        if "## Ключевые клинические факты" not in consilium_md:
            consilium_md = f"## Ключевые клинические факты\n{consilium_md}".strip()
        consilium_md = f"{consilium_md}\n" + "\n".join(additions)
    repaired["consilium_md"] = consilium_md.strip()
    return repaired
