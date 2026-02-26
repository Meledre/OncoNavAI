from __future__ import annotations

import re
from typing import Any


def _has_xelox_capox(text: str) -> bool:
    return bool(re.search(r"\b(xelox|capox)\b", text, flags=re.IGNORECASE))


def _surgery_signature(text: str) -> dict[str, bool]:
    has_r1 = bool(re.search(r"\bR1\b", text, flags=re.IGNORECASE))
    has_d2 = bool(re.search(r"\bD2\b", text, flags=re.IGNORECASE))
    has_lwis = bool(re.search(r"льюис|lewis|эзофагэктом|хирургическ\w+\s+лечени\w*", text, flags=re.IGNORECASE))
    return {
        "has_r1": has_r1,
        "has_d2": has_d2,
        "has_lewis": has_lwis,
    }


def _has_adjuvant_capecitabine(text: str) -> bool:
    if re.search(r"адъювант\w*[^.\n\r]{0,96}капецитаб", text, flags=re.IGNORECASE):
        return True
    capecitabine = re.search(r"капецитаб", text, flags=re.IGNORECASE)
    surgery = re.search(r"хирургическ\w+\s+лечени\w*|операци\w+|льюис|lewis", text, flags=re.IGNORECASE)
    if not capecitabine or not surgery:
        return False
    progression = re.search(r"прогресс\w*|progress\w*", text, flags=re.IGNORECASE)
    cap_pos = capecitabine.start()
    if cap_pos <= surgery.start():
        return False
    if progression and cap_pos > progression.start():
        return False
    return True


def _has_pjp_diagnosis(text: str) -> bool:
    return bool(
        re.search(
            r"пищеводно[-\s]?желудоч\w*\s+переход|пжп|гастроэзофагеальн\w*\s+переход|gej|кардиоэзофаг",
            text,
            flags=re.IGNORECASE,
        )
    )


def _extract_tnm_by_prefix(text: str, prefix: str) -> str | None:
    pattern = re.compile(
        rf"\b{prefix}\s*T\s*(is|[0-4xX](?:[a-cA-C])?)\s*N\s*([0-3xX](?:[a-cA-C])?)\s*M\s*([01xX])\b",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    t_value = str(match.group(1) or "").upper()
    n_value = str(match.group(2) or "").upper()
    m_value = str(match.group(3) or "").upper()
    return f"{prefix}T{t_value}N{n_value}M{m_value}"


def _extract_stage_group(text: str) -> str | None:
    match = re.search(r"(?:стадия|stage)\s*[:\-]?\s*(IV|III|II|I)\b", text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\b(IV|III|II|I)\s*ст\.?\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    return str(match.group(1) or "").upper()


def _infer_clinical_tnm_from_pathological(ptnm: str | None, stage_group: str | None) -> str | None:
    token = str(ptnm or "").strip()
    stage = str(stage_group or "").strip().upper()
    if not token or not token.startswith("pT"):
        return None
    if stage not in {"I", "II", "III", "IV"}:
        return None
    return f"c{token[1:]}"


def _has_progression_on_ramu_pacli(case_text: str, case_facts: dict[str, Any]) -> bool:
    history = case_facts.get("treatment_history") if isinstance(case_facts.get("treatment_history"), list) else []
    for item in history:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").lower()
        response = str(item.get("response") or "").lower()
        if ("рамуцирумаб" in name or "ramucirumab" in name) and ("паклитаксел" in name or "paclitaxel" in name):
            if "progress" in response or "прогресс" in response:
                return True
    text = str(case_text or "")
    return bool(
        re.search(r"рамуцирумаб[^.\n\r]{0,80}паклитаксел", text, flags=re.IGNORECASE)
        and re.search(r"прогресс\w*", text, flags=re.IGNORECASE)
    )


def _biomarker_snapshot(case_facts: dict[str, Any]) -> str | None:
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    her2 = str(biomarkers.get("her2") or "").strip()
    cps_values = biomarkers.get("pd_l1_cps_values") if isinstance(biomarkers.get("pd_l1_cps_values"), list) else []
    msi = str(biomarkers.get("msi_status") or "").strip()
    if not (her2 or cps_values or msi):
        return None
    cps_text = "/".join(str(int(item) if float(item).is_integer() else item) for item in cps_values[:2] if isinstance(item, (int, float)))
    parts: list[str] = []
    if her2:
        normalized_her2 = her2.replace(" ", "")
        if normalized_her2 == "1+":
            parts.append("HER2 1+ (1+ HER2)")
        else:
            parts.append(f"HER2 {her2}")
    if cps_text:
        parts.append(f"PD-L1 CPS {cps_text}")
    if msi:
        parts.append(msi)
    return ", ".join(parts) if parts else None


def reconcile_timeline_signals(
    *,
    case_text: str,
    case_facts: dict[str, Any],
    timeline: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    text = str(case_text or "")
    stage_item = case_facts.get("initial_stage") if isinstance(case_facts.get("initial_stage"), dict) else {}
    stage_text = str(stage_item.get("tnm") or stage_item.get("stage_group") or "").strip()
    ctnm = _extract_tnm_by_prefix(text, "c")
    ptnm = _extract_tnm_by_prefix(text, "p")
    stage_group = _extract_stage_group(text)
    if not ctnm:
        ctnm = _infer_clinical_tnm_from_pathological(ptnm, stage_group)

    observed: list[str] = []
    missing: list[str] = []
    facts_lines: list[str] = []

    if _has_pjp_diagnosis(text):
        observed.append("diagnosis_pjp")
        facts_lines.append("Локализация: пищеводно-желудочный переход (ПЖП).")

    if stage_text:
        observed.append("stage")
    if ctnm and ptnm and stage_group:
        facts_lines.append(f"Исходное стадирование: стадия {stage_group} ({ctnm}), послеоперационный статус {ptnm}.")
    elif stage_text:
        facts_lines.append(f"Исходное стадирование: {stage_text}.")
    else:
        missing.append("исходное стадирование (TNM/стадия)")

    if _has_xelox_capox(text):
        observed.append("periop_xelox")
        facts_lines.append("Периоперационная системная терапия: XELOX/CAPOX.")
    else:
        missing.append("этап периоперационной терапии XELOX/CAPOX")

    surgery = _surgery_signature(text)
    has_surgery_core = bool(surgery.get("has_r1")) and bool(surgery.get("has_lewis"))
    if has_surgery_core:
        observed.append("surgery_r1_d2")
        if bool(surgery.get("has_d2")):
            facts_lines.append("Хирургический этап: R1/D2/Льюис.")
        else:
            facts_lines.append("Хирургический этап: R1/Льюис (объём D2 не подтверждён).")
            missing.append("подтверждение объёма лимфодиссекции D2")
    else:
        if not bool(surgery.get("has_lewis")):
            missing.append("подтверждение хирургического этапа (тип операции)")
        if not bool(surgery.get("has_r1")):
            missing.append("подтверждение радикальности хирургического этапа (R-статус)")
        if not bool(surgery.get("has_d2")):
            missing.append("подтверждение объёма лимфодиссекции D2")

    if _has_adjuvant_capecitabine(text):
        observed.append("adjuvant_capecitabine")
        facts_lines.append("Послеоперационный этап: капецитабин (адъювантный/послеоперационный контекст).")
    else:
        missing.append("этап адъювантной терапии капецитабином")

    if _has_progression_on_ramu_pacli(text, case_facts):
        observed.append("line2_progression")
        facts_lines.append("2-я линия: рамуцирумаб + паклитаксел с последующим прогрессированием.")
    else:
        missing.append("сигнал прогрессирования после рамуцирумаба + паклитаксела")

    biomarker_line = _biomarker_snapshot(case_facts)
    if biomarker_line:
        facts_lines.append(f"Ключевые биомаркеры: {biomarker_line}.")

    core_hits = {"periop_xelox", "surgery_r1_d2", "adjuvant_capecitabine", "line2_progression"}
    n5_profile = len(core_hits.intersection(set(observed))) >= 2

    return {
        "n5_profile": n5_profile,
        "observed_items": observed,
        "missing_items": missing,
        "facts_lines": facts_lines,
        "timeline_items_count": len(timeline or []),
    }
