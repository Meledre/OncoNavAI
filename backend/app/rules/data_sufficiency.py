from __future__ import annotations

import re
from typing import Any


_MISSING_PREFIX_PATTERN = r"(?:отсутств\w*|нет|не\s+(?:определ\w*|выполн\w*|исслед\w*|представ\w*|получен\w*|извест\w*|провод\w*|оцен\w*))"


def _clinical_scope_text(case_text: str) -> str:
    text = str(case_text or "")
    if not text:
        return ""
    lowered = text.lower()
    markers = [
        "рекомендация ai-помощника",
        "для врача (краткое обоснование",
        "что нужно сделать:",
    ]
    cut_positions = [lowered.find(marker) for marker in markers if lowered.find(marker) >= 0]
    cutoff = min(cut_positions) if cut_positions else len(text)
    return text[:cutoff].strip()[:6000]


def _has_stage(case_facts: dict[str, Any]) -> bool:
    initial_stage = case_facts.get("initial_stage")
    current_stage = case_facts.get("current_stage")
    for item in (initial_stage, current_stage):
        if isinstance(item, dict) and (str(item.get("tnm") or "").strip() or str(item.get("stage_group") or "").strip()):
            return True
    return False


def _has_metastases_signal(case_facts: dict[str, Any], case_text: str) -> bool:
    metastases = case_facts.get("metastases")
    if isinstance(metastases, list) and metastases:
        return True
    return bool(re.search(r"\bM1\b|\bIV\b|метастаз", str(case_text or ""), flags=re.IGNORECASE))


def _has_biomarker_value(case_facts: dict[str, Any], key: str) -> bool:
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    value = biomarkers.get(key)
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return True
    return bool(str(value or "").strip()) and str(value).strip().lower() != "unknown"


def _minimum_dataset_from_case_facts(case_facts: dict[str, Any]) -> dict[str, Any]:
    block = case_facts.get("minimum_dataset")
    return block if isinstance(block, dict) else {}


def _contains_step(plan_sections: list[dict[str, Any]], pattern: str) -> bool:
    regex = re.compile(pattern, flags=re.IGNORECASE)
    for section in plan_sections:
        if not isinstance(section, dict):
            continue
        steps = section.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or step.get("name") or "").strip()
            if text and regex.search(text):
                return True
    return False


def _has_explicit_missing_signal(case_text: str, token_pattern: str) -> bool:
    text = _clinical_scope_text(case_text)
    forward = re.compile(
        rf"{_MISSING_PREFIX_PATTERN}[^.\n\r]{{0,90}}(?:{token_pattern})",
        flags=re.IGNORECASE,
    )
    backward = re.compile(
        rf"(?:{token_pattern})[^.\n\r]{{0,90}}{_MISSING_PREFIX_PATTERN}",
        flags=re.IGNORECASE,
    )
    return bool(forward.search(text) or backward.search(text))


def evaluate_data_sufficiency(
    *,
    case_facts: dict[str, Any],
    query_type: str,
    case_text: str,
    plan_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    minimum_dataset = _minimum_dataset_from_case_facts(case_facts)
    if bool(minimum_dataset) and isinstance(minimum_dataset.get("status"), bool):
        missing_critical = [
            str(item).strip()
            for item in minimum_dataset.get("missing_critical_fields", [])
            if str(item).strip()
        ] if isinstance(minimum_dataset.get("missing_critical_fields"), list) else []
        missing_optional = [
            str(item).strip()
            for item in minimum_dataset.get("missing_optional_fields", [])
            if str(item).strip()
        ] if isinstance(minimum_dataset.get("missing_optional_fields"), list) else []
        status = bool(minimum_dataset.get("status"))
        reason = str(minimum_dataset.get("reason") or "")
        if not reason:
            if status:
                reason = "Недостаточно минимальных клинических данных: " + ", ".join(missing_critical)
            elif missing_optional:
                reason = "Есть рекомендуемые к уточнению данные: " + ", ".join(missing_optional)
            else:
                reason = "Критических пробелов клинических данных не выявлено."
        return {
            "status": status,
            "missing_critical_fields": sorted(set(missing_critical)),
            "missing_optional_fields": sorted(set(missing_optional)),
            "reason": reason,
        }

    missing_critical_fields: list[str] = []
    missing_optional_fields: list[str] = []
    scoped_case_text = _clinical_scope_text(case_text)
    nosology = str(case_facts.get("nosology") or "").strip().lower()
    is_gastric_profile = nosology in {"gastric", "gastric_cancer"}
    if not is_gastric_profile and not nosology:
        is_gastric_profile = bool(re.search(r"желуд|gastric|stomach", scoped_case_text, flags=re.IGNORECASE))

    normalized_query = str(query_type or "").strip().upper()
    if normalized_query == "NEXT_STEPS":
        if not _has_stage(case_facts):
            missing_critical_fields.append("stage_or_tnm")
        if is_gastric_profile and _has_metastases_signal(case_facts, scoped_case_text):
            if not _has_biomarker_value(case_facts, "her2"):
                missing_critical_fields.append("HER2")
            if not _has_biomarker_value(case_facts, "pd_l1_cps_values"):
                missing_critical_fields.append("PD-L1 CPS")
            if not _has_biomarker_value(case_facts, "msi_status"):
                missing_critical_fields.append("MSI/dMMR")

    if _has_explicit_missing_signal(scoped_case_text, r"HER2|ERBB2"):
        missing_critical_fields.append("HER2")
    if is_gastric_profile:
        if _has_explicit_missing_signal(scoped_case_text, r"PD[-\s]?L1|CPS|combined\s+positive\s+score"):
            missing_critical_fields.append("PD-L1 CPS")
        if _has_explicit_missing_signal(scoped_case_text, r"MSI|MSS|dMMR|pMMR"):
            missing_critical_fields.append("MSI/dMMR")

    if _contains_step(plan_sections, r"\bcisplatin\b|\bцисплатин\b"):
        if not re.search(r"\bкреатинин\b|\bcreatinine\b", scoped_case_text, flags=re.IGNORECASE):
            missing_critical_fields.append("creatinine")
        if not re.search(r"\bрскф\b|\begfr\b|\bckd-epi\b", scoped_case_text, flags=re.IGNORECASE):
            missing_critical_fields.append("eGFR")

    if _has_explicit_missing_signal(scoped_case_text, r"креатинин|creatinine"):
        missing_critical_fields.append("creatinine")
    if _has_explicit_missing_signal(scoped_case_text, r"рскф|egfr|ckd-epi"):
        missing_critical_fields.append("eGFR")
    if _has_explicit_missing_signal(scoped_case_text, r"билирубин|альбумин|child[-\s]?pugh|мно|inr"):
        missing_critical_fields.append("liver_function_panel")
    if _has_explicit_missing_signal(scoped_case_text, r"нейропат\w*(?:.{0,20}?(?:grade|ctcae|степен\w*))"):
        missing_critical_fields.append("neuropathy_grade")
    if _has_explicit_missing_signal(scoped_case_text, r"антикоагулян\w*|антиагрегант\w*|коагул\w*|inr|мно"):
        missing_critical_fields.append("anticoagulation_profile")
    if _has_explicit_missing_signal(scoped_case_text, r"когнитив\w*|mini-cog|mmse|mocha|мoca"):
        missing_critical_fields.append("cognitive_assessment")
    if _has_explicit_missing_signal(scoped_case_text, r"социальн\w*\s+поддержк\w*|caregiver|опекун|прожива\w*\s+одн"):
        missing_critical_fields.append("social_support")
    if _has_explicit_missing_signal(scoped_case_text, r"предшеств\w*\s+лечени\w*|режим\w*|доз\w*|токсичност\w*|даты"):
        missing_critical_fields.append("treatment_history_detail")

    if _contains_step(plan_sections, r"\bbiopsy\b|биопси"):
        if not re.search(r"\bINR\b|\bМНО\b", scoped_case_text, flags=re.IGNORECASE):
            missing_optional_fields.append("INR_before_biopsy")

    dedup_critical = sorted({item for item in missing_critical_fields if str(item).strip()})
    dedup_optional = sorted({item for item in missing_optional_fields if str(item).strip()})
    status = bool(dedup_critical)
    if status:
        reason = "Недостаточно клинических данных: " + ", ".join(dedup_critical)
    elif dedup_optional:
        reason = "Есть рекомендуемые к уточнению данные: " + ", ".join(dedup_optional)
    else:
        reason = "Критических пробелов клинических данных не выявлено."

    return {
        "status": status,
        "missing_critical_fields": dedup_critical,
        "missing_optional_fields": dedup_optional,
        "reason": reason,
    }
