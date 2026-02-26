from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _non_empty(value: Any) -> str | None:
    text = _as_text(value)
    return text if text else None


def _first_text(*values: Any) -> str | None:
    for item in values:
        text = _non_empty(item)
        if text:
            return text
    return None


def _list_from_mapping_or_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _normalize_biomarkers(*candidates: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in candidates:
        if isinstance(raw, dict):
            for key, value in raw.items():
                name = _non_empty(key)
                biomarker_value = _non_empty(value)
                if not name or not biomarker_value:
                    continue
                items.append({"name": name, "value": biomarker_value})
            continue
        for entry in _as_list(raw):
            if isinstance(entry, str):
                text = _non_empty(entry)
                if text:
                    items.append({"name": text, "value": ""})
                continue
            record = _as_dict(entry)
            name = _first_text(
                record.get("name"),
                record.get("marker"),
                record.get("biomarker"),
                record.get("code"),
            )
            value = _first_text(record.get("value"), record.get("result"), record.get("status")) or ""
            if not name:
                continue
            items.append({"name": name, "value": value})
    dedup: dict[tuple[str, str], dict[str, str]] = {}
    for item in items:
        key = (_as_text(item.get("name")).lower(), _as_text(item.get("value")).lower())
        if key not in dedup:
            dedup[key] = {"name": _as_text(item.get("name")), "value": _as_text(item.get("value"))}
    return list(dedup.values())


def _normalize_comorbidities(*candidates: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in candidates:
        for entry in _list_from_mapping_or_list(raw):
            if isinstance(entry, str):
                name = _non_empty(entry)
                if name:
                    items.append({"name": name})
                continue
            record = _as_dict(entry)
            name = _first_text(
                record.get("name"),
                record.get("diagnosis"),
                record.get("title"),
                record.get("condition"),
            )
            if not name:
                continue
            item: dict[str, str] = {"name": name}
            code = _first_text(record.get("code"), record.get("icd10"))
            status = _first_text(record.get("status"), record.get("state"))
            if code:
                item["code"] = code
            if status:
                item["status"] = status
            items.append(item)
    dedup: dict[str, dict[str, str]] = {}
    for item in items:
        key = _as_text(item.get("name")).lower()
        if key and key not in dedup:
            dedup[key] = item
    return list(dedup.values())


def _classify_timeline_kind(kind_hint: str, text: str) -> str:
    normalized = f"{kind_hint} {text}".lower()
    therapy_tokens = (
        "therapy",
        "treat",
        "леч",
        "химио",
        "гормон",
        "иммуно",
        "препарат",
    )
    diagnostics_tokens = (
        "diagn",
        "кт",
        "мрт",
        "узи",
        "анализ",
        "лаборат",
        "биопс",
        "скан",
    )
    if any(token in normalized for token in diagnostics_tokens):
        return "diagnostics"
    if any(token in normalized for token in therapy_tokens):
        return "therapy"
    return "other"


def _normalize_timeline(items: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    therapy: list[dict[str, str]] = []
    diagnostics: list[dict[str, str]] = []
    for entry in _as_list(items):
        if isinstance(entry, str):
            text = _non_empty(entry)
            if not text:
                continue
            normalized = {"date": "", "event": text, "kind": _classify_timeline_kind("", text)}
        else:
            record = _as_dict(entry)
            text = _first_text(
                record.get("event"),
                record.get("text"),
                record.get("summary"),
                record.get("description"),
                record.get("title"),
            )
            if not text:
                continue
            kind_hint = _first_text(record.get("kind"), record.get("type"), record.get("section"), record.get("category")) or ""
            normalized = {
                "date": _first_text(record.get("date"), record.get("at"), record.get("timestamp")) or "",
                "event": text,
                "kind": _classify_timeline_kind(kind_hint, text),
            }
        if normalized["kind"] == "therapy":
            therapy.append(normalized)
        elif normalized["kind"] == "diagnostics":
            diagnostics.append(normalized)
    return therapy, diagnostics


def _normalize_current_therapy(*candidates: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in candidates:
        for entry in _list_from_mapping_or_list(raw):
            if isinstance(entry, str):
                text = _non_empty(entry)
                if text:
                    items.append({"name": text})
                continue
            record = _as_dict(entry)
            nested_current = record.get("current")
            if nested_current is not None and nested_current is not entry:
                for nested in _normalize_current_therapy(nested_current):
                    items.append(nested)
            name = _first_text(
                record.get("name"),
                record.get("drug"),
                record.get("regimen"),
                record.get("therapy"),
                record.get("text"),
            )
            if not name:
                continue
            item: dict[str, str] = {"name": name}
            dose = _first_text(record.get("dose"), record.get("dosage"))
            schedule = _first_text(record.get("schedule"), record.get("frequency"))
            status = _first_text(record.get("status"), record.get("state"))
            if dose:
                item["dose"] = dose
            if schedule:
                item["schedule"] = schedule
            if status:
                item["status"] = status
            items.append(item)
    dedup: dict[str, dict[str, str]] = {}
    for item in items:
        key = _as_text(item.get("name")).lower()
        if key and key not in dedup:
            dedup[key] = item
    return list(dedup.values())


def _build_upcoming_actions(plan_sections: Any) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for section in _as_list(plan_sections):
        section_record = _as_dict(section)
        section_name = _first_text(section_record.get("section"), section_record.get("title")) or "other"
        for step in _as_list(section_record.get("steps")):
            step_record = _as_dict(step)
            text = _first_text(step_record.get("text"), step_record.get("title"), step_record.get("summary"))
            if not text:
                continue
            actions.append(
                {
                    "text": text,
                    "priority": _first_text(step_record.get("priority")) or "medium",
                    "section": section_name,
                    "rationale": _first_text(step_record.get("rationale")) or "",
                }
            )
    if not actions:
        return []
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    actions.sort(key=lambda item: priority_rank.get(_as_text(item.get("priority")).lower(), 3))
    return actions[:8]


def build_patient_context_from_analyze_response(analyze_response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(analyze_response, dict):
        return {}

    doctor_report = _as_dict(analyze_response.get("doctor_report"))
    disease_context = _as_dict(doctor_report.get("disease_context"))
    case_facts = _as_dict(doctor_report.get("case_facts"))

    diagnosis_name = _first_text(
        disease_context.get("diagnosis_name"),
        disease_context.get("diagnosis"),
        disease_context.get("disease_name"),
        case_facts.get("diagnosis_name"),
        case_facts.get("diagnosis"),
        case_facts.get("disease_name"),
        case_facts.get("nosology"),
    )
    diagnosis_icd10 = _first_text(
        disease_context.get("icd10"),
        disease_context.get("icd10_code"),
        case_facts.get("icd10"),
        case_facts.get("icd10_code"),
    )
    diagnosis_stage = _first_text(
        disease_context.get("stage"),
        disease_context.get("stage_group"),
        case_facts.get("stage"),
        case_facts.get("stage_group"),
        case_facts.get("tnm_stage"),
    )
    diagnosis_biomarkers = _normalize_biomarkers(
        disease_context.get("biomarkers"),
        case_facts.get("biomarkers"),
        case_facts.get("molecular_markers"),
    )

    therapy_timeline, diagnostics_timeline = _normalize_timeline(doctor_report.get("timeline"))

    current_therapy = _normalize_current_therapy(
        case_facts.get("current_therapy"),
        case_facts.get("therapy"),
        case_facts.get("treatment"),
    )
    if not current_therapy and therapy_timeline:
        current_therapy = [{"name": item["event"]} for item in therapy_timeline[-2:]]

    upcoming_actions = _build_upcoming_actions(doctor_report.get("plan"))

    diagnosis: dict[str, Any] = {}
    if diagnosis_name:
        diagnosis["name"] = diagnosis_name
    if diagnosis_icd10:
        diagnosis["icd10"] = diagnosis_icd10
    if diagnosis_stage:
        diagnosis["stage"] = diagnosis_stage
    if diagnosis_biomarkers:
        diagnosis["biomarkers"] = diagnosis_biomarkers

    result = {
        "diagnosis": diagnosis,
        "comorbidities": _normalize_comorbidities(
            case_facts.get("comorbidities"),
            disease_context.get("comorbidities"),
        ),
        "therapy_timeline": therapy_timeline,
        "diagnostics_timeline": diagnostics_timeline,
        "current_therapy": current_therapy,
        "upcoming_actions": upcoming_actions,
    }

    has_meaningful_data = bool(
        result["diagnosis"]
        or result["comorbidities"]
        or result["therapy_timeline"]
        or result["diagnostics_timeline"]
        or result["current_therapy"]
        or result["upcoming_actions"]
    )
    return result if has_meaningful_data else {}

