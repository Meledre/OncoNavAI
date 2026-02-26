from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_TOKEN_NORMALIZER = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _norm_token(value: str) -> str:
    return _TOKEN_NORMALIZER.sub("", str(value or "").strip().lower())


def _path_value(payload: Any, dotted_path: str) -> Any:
    current = payload
    for raw_part in str(dotted_path or "").split("."):
        part = raw_part.strip()
        if not part:
            return None
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return None
            idx = int(part)
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue
        return None
    return current


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return bool(normalized) and normalized not in {"unknown", "n/a", "na", "none", "null", "не указано"}
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _load_profiles() -> dict[str, Any]:
    path = _repo_root() / "data" / "clinical_profiles" / "nosology_minimum_dataset_v1.json"
    if not path.exists():
        return {"schema_version": "1.0", "defaults": {}, "nosologies": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"schema_version": "1.0", "defaults": {}, "nosologies": {}}
    return payload


def _resolve_profile_key(*, nosology: str, icd10: str, profiles: dict[str, Any]) -> str:
    key = str(nosology or "").strip().lower()
    if key in {"brain", "malignant_brain_tumor"}:
        if str(icd10 or "").strip().upper().startswith("C79.3"):
            return "cns_metastases_c79_3"
        if str(icd10 or "").strip().upper().startswith("C71"):
            return "brain_primary_c71"
    if key in {"brain_primary_c71", "cns_metastases_c79_3"}:
        return key
    if key in (profiles.get("nosologies") or {}):
        return key
    if str(icd10 or "").strip().upper().startswith("C79.3"):
        return "cns_metastases_c79_3"
    if str(icd10 or "").strip().upper().startswith("C71"):
        return "brain_primary_c71"
    return key


def _collect_biomarker_tokens(*, case_json: dict[str, Any], case_facts: dict[str, Any], disease_context: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()

    diagnoses = case_json.get("diagnoses") if isinstance(case_json.get("diagnoses"), list) else []
    for diagnosis in diagnoses:
        if not isinstance(diagnosis, dict):
            continue
        biomarkers = diagnosis.get("biomarkers") if isinstance(diagnosis.get("biomarkers"), list) else []
        for marker in biomarkers:
            if not isinstance(marker, dict):
                continue
            name = _norm_token(str(marker.get("name") or ""))
            value = marker.get("value")
            if name and _non_empty(value):
                tokens.add(name)

    context_markers = disease_context.get("biomarkers") if isinstance(disease_context.get("biomarkers"), list) else []
    for marker in context_markers:
        if not isinstance(marker, dict):
            continue
        name = _norm_token(str(marker.get("name") or ""))
        value = marker.get("value")
        if name and _non_empty(value):
            tokens.add(name)

    facts_markers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    for name, value in facts_markers.items():
        normalized_name = _norm_token(name)
        if normalized_name and _non_empty(value):
            tokens.add(normalized_name)
    return tokens


def _collect_lab_tokens(case_facts: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    v2 = case_facts.get("case_facts_v2") if isinstance(case_facts.get("case_facts_v2"), dict) else {}
    labs = v2.get("labs") if isinstance(v2.get("labs"), list) else []
    for lab in labs:
        if not isinstance(lab, dict):
            continue
        name = _norm_token(str(lab.get("name") or ""))
        value = lab.get("value")
        if name and _non_empty(value):
            tokens.add(name)
    return tokens


def _fallback_case_signal(*, field_path: str, case_facts: dict[str, Any], disease_context: dict[str, Any]) -> bool:
    if field_path == "patient.ecog":
        patient_v2 = (
            (case_facts.get("case_facts_v2") or {}).get("patient")
            if isinstance((case_facts.get("case_facts_v2") or {}), dict)
            else {}
        )
        return _non_empty((patient_v2 or {}).get("ecog")) or _non_empty(disease_context.get("ecog"))
    if field_path.startswith("diagnoses.0.stage"):
        return _non_empty(disease_context.get("stage_group")) or _non_empty((case_facts.get("current_stage") or {}).get("stage_group"))
    if field_path == "diagnoses.0.timeline":
        return bool(case_facts.get("treatment_history")) or bool(case_facts.get("case_facts_v2"))
    if field_path == "diagnoses.0.last_plan.line":
        return _non_empty(disease_context.get("line"))
    if field_path == "diagnoses.0.histology":
        return _non_empty((case_facts.get("case_facts_v2") or {}).get("tumor"))
    return False


def evaluate_min_case_requirements(
    *,
    case_json: dict[str, Any] | None,
    case_facts: dict[str, Any],
    disease_context: dict[str, Any],
    case_payload: dict[str, Any],
    routing_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profiles = _load_profiles()
    nosology_raw = str(
        (routing_meta or {}).get("resolved_cancer_type")
        or case_payload.get("cancer_type")
        or "unknown"
    ).strip().lower()
    icd10 = str(disease_context.get("icd10") or "").strip().upper()
    profile_key = _resolve_profile_key(nosology=nosology_raw, icd10=icd10, profiles=profiles)
    nosology_profiles = profiles.get("nosologies") if isinstance(profiles.get("nosologies"), dict) else {}
    defaults = profiles.get("defaults") if isinstance(profiles.get("defaults"), dict) else {}
    profile = nosology_profiles.get(profile_key) if isinstance(nosology_profiles.get(profile_key), dict) else defaults
    profile = profile if isinstance(profile, dict) else {}

    case_payload_norm = case_json if isinstance(case_json, dict) else {}
    min_case_fields = [str(item).strip() for item in profile.get("min_case_fields", []) if str(item).strip()]
    required_biomarkers = [str(item).strip() for item in profile.get("required_biomarkers", []) if str(item).strip()]
    required_labs = [str(item).strip() for item in profile.get("required_labs", []) if str(item).strip()]

    missing_fields: list[str] = []
    passed_checks = 0
    total_checks = len(min_case_fields) + len(required_biomarkers) + len(required_labs)

    for field in min_case_fields:
        value = _path_value(case_payload_norm, field)
        ok = _non_empty(value) or _fallback_case_signal(field_path=field, case_facts=case_facts, disease_context=disease_context)
        if ok:
            passed_checks += 1
        else:
            missing_fields.append(field)

    biomarker_tokens = _collect_biomarker_tokens(case_json=case_payload_norm, case_facts=case_facts, disease_context=disease_context)
    for marker in required_biomarkers:
        if _norm_token(marker) in biomarker_tokens:
            passed_checks += 1
        else:
            missing_fields.append(f"biomarker:{marker}")

    lab_tokens = _collect_lab_tokens(case_facts)
    for lab in required_labs:
        if _norm_token(lab) in lab_tokens:
            passed_checks += 1
        else:
            missing_fields.append(f"lab:{lab}")

    completeness = (float(passed_checks) / float(total_checks)) if total_checks else 1.0
    status = bool(missing_fields)
    intents = [
        str(item).strip()
        for item in profile.get("safe_missing_data_plan_intents", [])
        if str(item).strip()
    ] or ["дозапрос данных", "уточнение", "безопасность"]
    no_ready_plan = bool(profile.get("no_ready_plan_without_minimum", True))

    if str((routing_meta or {}).get("match_strategy") or "").strip().lower() == "ambiguous_brain_scope":
        if "brain_scope_icd10" not in missing_fields:
            missing_fields.append("brain_scope_icd10")
        status = True

    if status:
        reason = "Недостаточно минимальных клинических данных: " + ", ".join(missing_fields)
    else:
        reason = "Минимальный клинический набор заполнен."

    return {
        "status": status,
        "nosology_profile": profile_key or "default",
        "completeness": round(completeness, 4),
        "checks_total": total_checks,
        "checks_passed": passed_checks,
        "missing_critical_fields": sorted(set(missing_fields)),
        "safe_missing_data_plan_intents": intents,
        "no_ready_plan_without_minimum": no_ready_plan,
        "reason": reason,
    }
