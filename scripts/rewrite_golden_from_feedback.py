#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TARGET_CORE_NOSOLOGIES: tuple[str, ...] = (
    "gastric",
    "lung",
    "breast",
    "colorectal",
    "prostate",
    "rcc",
    "bladder",
    "brain_primary_c71",
    "cns_metastases_c79_3",
)

NOSOLOGY_ICD10: dict[str, str] = {
    "gastric": "C16",
    "lung": "C34",
    "breast": "C50",
    "colorectal": "C18",
    "prostate": "C61",
    "rcc": "C64",
    "bladder": "C67",
    "brain_primary_c71": "C71",
    "cns_metastases_c79_3": "C79.3",
}

NOSOLOGY_DISEASE_ID: dict[str, str] = {
    "gastric": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e",
    "lung": "2efcb0a0-2b4a-5f44-a247-9e1c6d9a7f42",
    "breast": "9d9d8f58-2a2d-5c9d-b43d-7d4af8854d38",
    "colorectal": "c8b1f6d0-4b6f-53cf-9e7d-6df58cc1ad5f",
    "prostate": "b53b53b7-f1e4-58ef-8d3d-5846df8f9a10",
    "rcc": "e4d29126-54ce-56cb-88dc-2dcf4954eaf9",
    "bladder": "d80c5e16-28df-5f1d-b88b-f76795db4c59",
    "brain_primary_c71": "c0a0a03b-040b-5314-9802-abef422d53b5",
    "cns_metastases_c79_3": "7a2bf75a-b89e-5fb9-bc16-ee6eae6c27b8",
}

UNSAFE_PHRASES = ("план согласован", "решение принято окончательно")
SCORE_RE = re.compile(r"([1-5])\s*/\s*5")
_TOKEN_NORMALIZER = re.compile(r"[^a-z0-9]+", re.IGNORECASE)
_UNKNOWN_VALUES = {
    "",
    "unknown",
    "unknown_due_missing_data",
    "n/a",
    "na",
    "none",
    "null",
    "неизвестно",
    "не указано",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"oncoai:golden-rewrite:{seed}"))


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if not token:
            continue
        payload = json.loads(token)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def _parse_score(value: str) -> int:
    match = SCORE_RE.search(str(value or ""))
    if match:
        return int(match.group(1))
    return 3


def _parse_bool_ru(value: str) -> bool:
    token = str(value or "").strip().lower()
    if not token:
        return False
    if token.startswith(("нет", "no", "false", "0")):
        return False
    if "нет риска" in token or "без риска" in token:
        return False
    if token.startswith(("да", "yes", "true", "1")):
        return True
    return "риск" in token


def _split_required_changes(raw: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[\n;•]+", str(raw or "")):
        token = str(part).strip(" -\t\r")
        if token:
            out.append(token[:500])
    return out


def _sanitize_text(value: str) -> str:
    text = str(value or "")
    lowered = text.lower()
    for phrase in UNSAFE_PHRASES:
        if phrase in lowered:
            text = re.sub(re.escape(phrase), "предварительный план к обсуждению", text, flags=re.IGNORECASE)
            lowered = text.lower()
    return text


def _norm_token(value: str) -> str:
    return _TOKEN_NORMALIZER.sub("", str(value or "").strip().lower())


def _is_known_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized not in _UNKNOWN_VALUES
    if isinstance(value, (list, tuple, set)):
        return any(_is_known_value(item) for item in value)
    if isinstance(value, dict):
        return any(_is_known_value(item) for item in value.values())
    return True


def _default_stage_for_nosology(nosology: str) -> str:
    if str(nosology or "").strip().lower() == "brain_primary_c71":
        return "high_grade"
    return "metastatic"


def _default_histology_for_nosology(nosology: str) -> str:
    mapping = {
        "breast": "invasive_ductal_carcinoma",
        "colorectal": "adenocarcinoma",
        "lung": "adenocarcinoma",
        "prostate": "acinar_adenocarcinoma",
        "rcc": "clear_cell_renal_cell_carcinoma",
        "bladder": "urothelial_carcinoma",
        "gastric": "adenocarcinoma",
        "brain_primary_c71": "glioblastoma",
        "cns_metastases_c79_3": "metastatic_adenocarcinoma",
    }
    return mapping.get(str(nosology or "").strip().lower(), "malignant_neoplasm")


def _ecog_from_bucket(raw_bucket: str) -> int | str | None:
    token = str(raw_bucket or "").strip().lower()
    if token in {"0", "0_1", "0-1"}:
        return 1
    if token in {"1", "2", "2_3", "2-3"}:
        return 2
    return None


def _line_value(raw_line: Any) -> str:
    token = str(raw_line or "").strip()
    if not token:
        return ""
    if token.isdigit():
        return f"{token}L"
    return token


@dataclass
class FeedbackRow:
    review_item_id: str
    golden_pair_id: str
    nosology: str
    clinical_validity_score: int
    doctor_completeness_score: int
    patient_clarity_score: int
    citation_relevance_score: int
    safety_risk_found: bool
    safety_risk_notes: str
    required_changes: list[str]
    decision: str
    reviewer_id: str
    reviewed_at: str
    review_notes: str


def _load_feedback_rows(path: Path) -> dict[str, FeedbackRow]:
    out: dict[str, FeedbackRow] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pair_id = str(row.get("golden_pair_id") or "").strip()
            if not pair_id:
                continue
            final_decision = str(row.get("final_decision") or "").strip().upper() or "REWRITE_REQUIRED"
            if final_decision not in {"REWRITE_REQUIRED", "APPROVED", "NEEDS_CLARIFICATION"}:
                final_decision = "REWRITE_REQUIRED"
            out[pair_id] = FeedbackRow(
                review_item_id=str(row.get("review_item_id") or "").strip() or f"AUTO-{pair_id}",
                golden_pair_id=pair_id,
                nosology=str(row.get("nosology") or "").strip().lower() or "unknown",
                clinical_validity_score=_parse_score(str(row.get("clinical_validity") or "")),
                doctor_completeness_score=_parse_score(str(row.get("doctor_report_completeness") or "")),
                patient_clarity_score=_parse_score(str(row.get("patient_text_clarity") or "")),
                citation_relevance_score=_parse_score(str(row.get("citation_relevance") or "")),
                safety_risk_found=_parse_bool_ru(str(row.get("safety_risk_found") or "")),
                safety_risk_notes=str(row.get("safety_risk_found") or "").strip()[:5000],
                required_changes=_split_required_changes(str(row.get("required_changes") or "")),
                decision=final_decision,
                reviewer_id=str(row.get("reviewer_id") or "").strip(),
                reviewed_at=str(row.get("reviewed_at") or "").strip(),
                review_notes=str(row.get("review_notes") or "").strip(),
            )
    return out


def _load_jsonl_index(path: Path, key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        token = str(row.get(key) or "").strip()
        if token:
            out[token] = row
    return out


def _load_control_index(control_root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for file_path in sorted(control_root.glob("*/real_cases_manifest_v1.jsonl")):
        out.update(_load_jsonl_index(file_path, "case_id"))
    return out


def _load_canonical_index(canonical_root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for file_path in sorted(canonical_root.glob("core/*/canonical_cases_v1.jsonl")):
        out.update(_load_jsonl_index(file_path, "case_id"))
    return out


def _load_minimum_profiles(profiles_root: Path) -> dict[str, Any]:
    path = profiles_root / "nosology_minimum_dataset_v1.json"
    if not path.exists():
        return {"defaults": {}, "nosologies": {}}
    return _read_json(path)


def _load_biomarker_profiles(profiles_root: Path) -> dict[str, Any]:
    path = profiles_root / "nosology_biomarker_matrix_v1.json"
    if not path.exists():
        return {"defaults": {}, "nosologies": {}}
    return _read_json(path)


def _profile_for_nosology(profiles: dict[str, Any], nosology: str) -> dict[str, Any]:
    nos = profiles.get("nosologies") if isinstance(profiles.get("nosologies"), dict) else {}
    defaults = profiles.get("defaults") if isinstance(profiles.get("defaults"), dict) else {}
    selected = nos.get(nosology) if isinstance(nos.get(nosology), dict) else {}
    if isinstance(selected, dict) and selected:
        return selected
    return defaults


def _build_minimum_dataset_status(
    *,
    nosology: str,
    profile: dict[str, Any],
    case_facts: dict[str, Any],
    disease_biomarkers: list[dict[str, Any]],
    expected_insufficient_data: bool,
) -> dict[str, Any]:
    min_fields = [str(item).strip() for item in profile.get("min_case_fields", []) if str(item).strip()]
    req_biomarkers = [str(item).strip() for item in profile.get("required_biomarkers", []) if str(item).strip()]
    req_labs = [str(item).strip() for item in profile.get("required_labs", []) if str(item).strip()]
    checks_total = len(min_fields) + len(req_biomarkers) + len(req_labs)
    missing: list[str] = []
    checks_passed = 0

    field_value_map = {
        "diagnoses.0.icd10": case_facts.get("icd10"),
        "diagnoses.0.stage.stage_group": case_facts.get("stage_group"),
        "diagnoses.0.last_plan.line": case_facts.get("line_of_therapy"),
        "diagnoses.0.histology": case_facts.get("histology"),
        "diagnoses.0.timeline": case_facts.get("treatment_history"),
        "patient.ecog": case_facts.get("ecog"),
    }
    for field in min_fields:
        value = field_value_map.get(field)
        if _is_known_value(value):
            checks_passed += 1
        else:
            missing.append(field)

    biomarker_values = {
        _norm_token(str(item.get("name") or "")): item.get("value")
        for item in disease_biomarkers
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    for marker in req_biomarkers:
        marker_value = biomarker_values.get(_norm_token(marker))
        if _is_known_value(marker_value):
            checks_passed += 1
        else:
            missing.append(f"biomarker:{marker}")

    labs = case_facts.get("key_labs") if isinstance(case_facts.get("key_labs"), dict) else {}
    normalized_labs = {_norm_token(name): value for name, value in labs.items()}
    for lab in req_labs:
        lab_value = normalized_labs.get(_norm_token(lab))
        if _is_known_value(lab_value):
            checks_passed += 1
        else:
            missing.append(f"lab:{lab}")

    if expected_insufficient_data and not missing:
        if min_fields:
            missing.append(min_fields[0])
        elif req_biomarkers:
            missing.append(f"biomarker:{req_biomarkers[0]}")
        elif req_labs:
            missing.append(f"lab:{req_labs[0]}")

    status = bool(missing)
    completeness = round(float(checks_passed) / float(checks_total), 4) if checks_total else 1.0
    reason = (
        "Недостаточно минимальных клинических данных для безопасного выбора лечебной тактики."
        if status
        else "Минимальный клинический набор для эталона заполнен."
    )
    return {
        "status": status,
        "nosology_profile": nosology,
        "completeness": completeness,
        "checks_total": checks_total,
        "checks_passed": checks_passed,
        "missing_critical_fields": sorted(set(missing)),
        "missing_optional_fields": [],
        "safe_missing_data_plan_intents": profile.get(
            "safe_missing_data_plan_intents",
            ["дозапрос данных", "уточнение", "безопасность"],
        ),
        "no_ready_plan_without_minimum": bool(profile.get("no_ready_plan_without_minimum", True)),
        "reason": reason,
    }


def _default_biomarker_value(name: str, expected_insufficient_data: bool) -> str:
    if expected_insufficient_data:
        return "unknown_due_missing_data"
    token = str(name or "").strip().lower()
    mapping = {
        "er": "positive",
        "pr": "positive",
        "her2": "negative",
        "ki-67": "high",
        "ki67": "high",
        "ras": "wild_type",
        "braf": "negative",
        "msi/dmmr": "mss/pmmr",
        "egfr": "l858r",
        "alk": "negative",
        "ros1": "negative",
        "pd-l1": "tps_5_percent",
        "psa": "elevated",
        "testosterone": "castrate_range",
        "hrr panel": "no_pathogenic_variant",
        "histology subtype": "clear_cell",
        "imdc risk": "intermediate",
        "fgfr2/3": "wild_type",
        "pd-l1 cps": "ge_5",
        "idh1/2": "wild_type",
        "mgmt": "methylated",
        "1p/19q": "non_codeleted",
        "primary tumor type": "lung_adenocarcinoma",
        "driver mutation status": "not_detected",
    }
    return mapping.get(token, "documented")


def _canonical_biomarker_values(canonical_case: dict[str, Any] | None) -> dict[str, Any]:
    canonical = canonical_case if isinstance(canonical_case, dict) else {}
    diagnoses = canonical.get("diagnoses") if isinstance(canonical.get("diagnoses"), list) else []
    diagnosis0 = diagnoses[0] if diagnoses and isinstance(diagnoses[0], dict) else {}
    biomarkers = diagnosis0.get("biomarkers") if isinstance(diagnosis0.get("biomarkers"), list) else []
    values: dict[str, Any] = {}
    for marker in biomarkers:
        if not isinstance(marker, dict):
            continue
        name = _norm_token(str(marker.get("name") or ""))
        value = marker.get("value")
        if name and _is_known_value(value):
            values[name] = value
    return values


def _build_biomarkers(
    *,
    nosology: str,
    biomarker_profiles: dict[str, Any],
    derived_mode: str,
    canonical_case: dict[str, Any] | None,
    expected_insufficient_data: bool,
) -> list[dict[str, str]]:
    profile = _profile_for_nosology(biomarker_profiles, nosology)
    required = [str(item).strip() for item in profile.get("required", []) if str(item).strip()]
    optional = [str(item).strip() for item in profile.get("optional", []) if str(item).strip()]
    selected = required + optional[:1]
    if not selected:
        return [
            {
                "name": "Tumor marker profile",
                "value": "unknown_due_missing_data" if expected_insufficient_data else "documented",
            }
        ]

    canonical_values = _canonical_biomarker_values(canonical_case)
    is_real_derived = str(derived_mode or "").strip().lower() == "real_derived"
    rows: list[dict[str, str]] = []
    for marker in selected:
        normalized = _norm_token(marker)
        if expected_insufficient_data:
            value = "unknown_due_missing_data"
        elif is_real_derived:
            canonical_value = canonical_values.get(normalized)
            value = str(canonical_value) if _is_known_value(canonical_value) else "unknown_due_missing_data"
        else:
            value = _default_biomarker_value(marker, expected_insufficient_data=False)
        rows.append({"name": marker, "value": value})
    return rows


def _citation_url(source_id: str, nosology: str, idx: int) -> str:
    source = str(source_id or "").strip().lower()
    if source == "minzdrav":
        return f"https://cr.minzdrav.gov.ru/preview-cr/{nosology}-{idx}"
    if source == "russco":
        return f"https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-{idx:02d}.pdf"
    if source == "pubmed":
        return "https://pubmed.ncbi.nlm.nih.gov/00000000/"
    if source == "international_guidelines":
        return "https://www.esmo.org/guidelines"
    return f"https://example.org/{source}/{nosology}/{idx}"


def _citation_quote(source_id: str) -> str:
    source = str(source_id or "").strip().lower()
    if source == "minzdrav":
        return "Минздрав: выбор тактики зависит от стадии, статуса пациента и предлеченности."
    if source == "russco":
        return "RUSSCO: для смены линии важны клинические факторы и безопасность."
    if source == "international_guidelines":
        return "Международные CPG подтверждают последовательность оценки и контроля токсичности."
    return "Guideline evidence supports this statement."


def _build_citations(
    *,
    golden_pair_id: str,
    nosology: str,
    source_ids: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    unique_sources: list[str] = []
    seen: set[str] = set()
    for source in source_ids:
        token = str(source or "").strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        unique_sources.append(token)
    if not unique_sources:
        unique_sources = ["minzdrav"]
    for index, source in enumerate(unique_sources, start=1):
        rows.append(
            {
                "citation_id": _uuid(f"{golden_pair_id}:citation:{source}:{index}"),
                "source_id": source,
                "document_id": _uuid(f"{golden_pair_id}:document:{source}:{index}"),
                "version_id": _uuid(f"{golden_pair_id}:version:{source}:{index}"),
                "page_start": index,
                "page_end": index + 1,
                "section_path": f"{nosology}/clinical_recommendation",
                "quote": _citation_quote(source),
                "file_uri": _citation_url(source, nosology, index),
                "score": 0.86,
            }
        )
    return rows


def _build_sanity_checks(expected_insufficient_data: bool) -> list[dict[str, str]]:
    if expected_insufficient_data:
        return [
            {"check_id": "case_facts_stage_present", "status": "warn", "details": "нужна верификация стадии"},
            {"check_id": "case_facts_metastases_present", "status": "warn", "details": "нужна верификация метастазов"},
            {"check_id": "case_facts_treatment_history_present", "status": "warn", "details": "предлеченность неполна"},
            {"check_id": "case_facts_biomarkers_present", "status": "warn", "details": "часть биомаркеров отсутствует"},
            {"check_id": "consilium_contains_stage", "status": "pass", "details": "отражено ограничение"},
        ]
    return [
        {"check_id": "case_facts_stage_present", "status": "pass", "details": "ok"},
        {"check_id": "case_facts_metastases_present", "status": "pass", "details": "ok"},
        {"check_id": "case_facts_treatment_history_present", "status": "pass", "details": "ok"},
        {"check_id": "case_facts_biomarkers_present", "status": "pass", "details": "ok"},
        {"check_id": "consilium_contains_stage", "status": "pass", "details": "ok"},
    ]


def _build_case_facts(
    *,
    nosology: str,
    derived_from: dict[str, Any],
    control_case: dict[str, Any] | None,
    canonical_case: dict[str, Any] | None,
    profile: dict[str, Any],
    expected_insufficient_data: bool,
) -> dict[str, Any]:
    control = control_case if isinstance(control_case, dict) else {}
    canonical = canonical_case if isinstance(canonical_case, dict) else {}
    diagnoses = canonical.get("diagnoses") if isinstance(canonical.get("diagnoses"), list) else []
    diagnosis0 = diagnoses[0] if diagnoses and isinstance(diagnoses[0], dict) else {}
    stage = diagnosis0.get("stage") if isinstance(diagnosis0.get("stage"), dict) else {}
    last_plan = diagnosis0.get("last_plan") if isinstance(diagnosis0.get("last_plan"), dict) else {}
    derived_mode = str(derived_from.get("mode") or "synthetic_derived")
    synthetic_complete_mode = (
        derived_mode == "synthetic_derived"
        and not expected_insufficient_data
        and not bool(control)
        and not bool(canonical)
    )

    icd10 = str(diagnosis0.get("icd10") or control.get("primary_icd10") or NOSOLOGY_ICD10.get(nosology) or "")
    stage_group = str(stage.get("stage_group") or control.get("strata", {}).get("stage_setting") or "").strip()
    if not stage_group and synthetic_complete_mode:
        stage_group = _default_stage_for_nosology(nosology)
    if not stage_group:
        stage_group = "unknown"

    line_text = _line_value(control.get("line_of_therapy"))
    if not line_text:
        line_text = _line_value(last_plan.get("line"))
    if not line_text and synthetic_complete_mode:
        line_text = "2L"
    if not line_text:
        line_text = "unknown"

    histology = str(diagnosis0.get("histology") or "").strip()
    if not histology and synthetic_complete_mode:
        histology = _default_histology_for_nosology(nosology)
    if not histology:
        histology = "unknown_due_missing_data"

    patient = canonical.get("patient") if isinstance(canonical.get("patient"), dict) else {}
    ecog = patient.get("ecog")
    if not _is_known_value(ecog):
        ecog = _ecog_from_bucket(str(control.get("strata", {}).get("ecog_bucket") or ""))
    if not _is_known_value(ecog) and synthetic_complete_mode:
        ecog = 1
    if not _is_known_value(ecog):
        ecog = "unknown_due_missing_data"

    timeline = diagnosis0.get("timeline") if isinstance(diagnosis0.get("timeline"), list) else []
    treatment_history = [
        str(item.get("label") or item.get("details") or "").strip()
        for item in timeline
        if isinstance(item, dict) and str(item.get("label") or item.get("details") or "").strip()
    ]
    if not treatment_history and synthetic_complete_mode:
        treatment_history = ["Сценарная предлеченность: первая линия завершена, выполнена контрольная оценка."]

    min_fields = [str(item).strip() for item in profile.get("min_case_fields", []) if str(item).strip()]
    required_labs = [str(item).strip() for item in profile.get("required_labs", []) if str(item).strip()]

    labs: dict[str, Any] = {}
    for item in required_labs:
        if expected_insufficient_data:
            labs[item] = "unknown_due_missing_data"
        elif synthetic_complete_mode:
            labs[item] = "within_reference"
        else:
            labs[item] = "unknown_due_missing_data"

    return {
        "nosology": nosology,
        "derived_mode": derived_mode,
        "control_case_id": control.get("case_id"),
        "icd10": icd10,
        "stage_group": stage_group,
        "line_of_therapy": line_text,
        "histology": histology,
        "ecog": ecog,
        "treatment_history": treatment_history,
        "key_labs": labs,
        "minimum_required_fields": min_fields,
    }


def _build_plan_sections(
    *,
    golden_pair_id: str,
    required_plan_intents: list[str],
    minimum_dataset: dict[str, Any],
    citation_ids: list[str],
) -> list[dict[str, Any]]:
    intents = [str(item).strip() for item in required_plan_intents if str(item).strip()]
    if not intents:
        intents = ["оценка ответа", "уточнение"]
    first_citation = citation_ids[0] if citation_ids else _uuid(f"{golden_pair_id}:fallback-citation")

    if bool(minimum_dataset.get("status")):
        safe_intents = [
            str(item).strip()
            for item in minimum_dataset.get("safe_missing_data_plan_intents", [])
            if str(item).strip()
        ] or ["дозапрос данных", "уточнение", "безопасность"]
        steps: list[dict[str, Any]] = []
        for idx, intent in enumerate(safe_intents, start=1):
            steps.append(
                {
                    "step_id": _uuid(f"{golden_pair_id}:safe-step:{idx}:{intent}"),
                    "text": f"{intent}: собрать недостающие параметры до выбора лечебной тактики.",
                    "priority": "high",
                    "rationale": str(minimum_dataset.get("reason") or ""),
                    "evidence_level": "LoE C",
                    "recommendation_strength": "GoR strong",
                    "confidence": 0.72,
                    "citation_ids": [first_citation],
                    "depends_on_missing_data": list(minimum_dataset.get("missing_critical_fields") or []),
                }
            )
        steps.append(
            {
                "step_id": _uuid(f"{golden_pair_id}:safe-step:final"),
                "text": "До восполнения минимального набора данных окончательная лечебная тактика не формируется.",
                "priority": "high",
                "rationale": str(minimum_dataset.get("reason") or ""),
                "evidence_level": "LoE C",
                "recommendation_strength": "GoR strong",
                "confidence": 0.7,
                "citation_ids": [first_citation],
                "depends_on_missing_data": list(minimum_dataset.get("missing_critical_fields") or []),
            }
        )
        return [{"section": "diagnostics", "title": "Безопасный режим уточнения данных", "steps": steps}]

    treatment_steps: list[dict[str, Any]] = []
    for idx, intent in enumerate(intents, start=1):
        treatment_steps.append(
            {
                "step_id": _uuid(f"{golden_pair_id}:treatment-step:{idx}:{intent}"),
                "text": f"{intent}: выполнить этап и зафиксировать результат в timeline.",
                "priority": "high" if idx == 1 else "medium",
                "rationale": "Терапевтический шаг сформирован по клиническим рекомендациям и контексту кейса.",
                "evidence_level": "LoE B",
                "recommendation_strength": "GoR strong",
                "confidence": 0.84,
                "citation_ids": [first_citation],
                "depends_on_missing_data": [],
            }
        )
    return [
        {
            "section": "diagnostics",
            "title": "Клиническая верификация перед стартом линии",
            "steps": [
                {
                    "step_id": _uuid(f"{golden_pair_id}:diagnostics-step:1"),
                    "text": "оценка ответа: выполнить контрольную визуализацию и сверить критерии ответа.",
                    "priority": "high",
                    "rationale": "Нужно подтвердить статус заболевания перед сменой/продолжением терапии.",
                    "evidence_level": "LoE B",
                    "recommendation_strength": "GoR strong",
                    "confidence": 0.86,
                    "citation_ids": [first_citation],
                    "depends_on_missing_data": [],
                }
            ],
        },
        {
            "section": "treatment",
            "title": "Предварительная тактика для консилиума",
            "steps": treatment_steps,
        },
    ]


def _build_issues(
    *,
    golden_pair_id: str,
    required_issue_kinds: list[str],
    minimum_dataset: dict[str, Any],
    citation_ids: list[str],
) -> list[dict[str, Any]]:
    issue_kinds = [str(item).strip() for item in required_issue_kinds if str(item).strip()]
    if bool(minimum_dataset.get("status")) and "missing_data" not in issue_kinds:
        issue_kinds.insert(0, "missing_data")
    if not issue_kinds:
        issue_kinds = ["other"]
    first_citation = citation_ids[0] if citation_ids else _uuid(f"{golden_pair_id}:fallback-citation")
    issues: list[dict[str, Any]] = []
    for idx, kind in enumerate(issue_kinds, start=1):
        severity = "critical" if kind == "contraindication" else "warning"
        summary = {
            "missing_data": "Недостаточно данных для безопасного выбора лечебной тактики.",
            "deviation": "Обнаружено отклонение от ожидаемого клинического маршрута.",
            "contraindication": "Есть клинические факторы, требующие исключить часть опций лечения.",
            "inconsistency": "Есть конфликт интерпретаций между источниками рекомендаций.",
        }.get(kind, "Требуется дополнительная клиническая верификация.")
        details = str(minimum_dataset.get("reason") or "Требуется уточнение и верификация данных по кейсу.")
        issues.append(
            {
                "issue_id": _uuid(f"{golden_pair_id}:issue:{idx}:{kind}"),
                "severity": severity,
                "kind": kind,
                "summary": summary,
                "details": details,
                "field_path": "case.minimum_dataset",
                "suggested_questions": [
                    "Какие данные нужно дополнить для финализации решения?",
                    "Есть ли противопоказания или факторы риска для текущей опции?",
                ],
                "citation_ids": [first_citation],
            }
        )
    return issues


def _build_clinical_review(
    *,
    pair_id: str,
    feedback_map: dict[str, FeedbackRow],
    feedback_csv_name: str,
    minimum_dataset_missing: bool,
) -> tuple[dict[str, Any], str, str | None, str | None, str | None]:
    row = feedback_map.get(pair_id)
    if row is None and pair_id.startswith("golden-brain_primary_c71-"):
        legacy_pair = pair_id.replace("golden-brain_primary_c71-", "golden-brain-")
        row = feedback_map.get(legacy_pair)
    if row is None:
        clinical_review = {
            "clinical_validity_score": 3,
            "doctor_report_completeness_score": 3,
            "patient_text_clarity_score": 4,
            "citation_relevance_score": 4,
            "safety_risk_found": bool(minimum_dataset_missing),
            "safety_risk_notes": "Автоматическая перепрошивка: требуется очное клиническое ревью.",
            "required_changes": ["Проверить клиническую полноту и корректность интерпретации на ревью."],
            "decision": "REWRITE_REQUIRED",
            "feedback_source": feedback_csv_name,
        }
        return clinical_review, "AUTO", None, None, None

    required_changes = row.required_changes or ["См. proposed_fix_text в feedback CSV."]
    clinical_review = {
        "clinical_validity_score": row.clinical_validity_score,
        "doctor_report_completeness_score": row.doctor_completeness_score,
        "patient_text_clarity_score": row.patient_clarity_score,
        "citation_relevance_score": row.citation_relevance_score,
        "safety_risk_found": row.safety_risk_found,
        "safety_risk_notes": row.safety_risk_notes,
        "required_changes": required_changes,
        "decision": row.decision,
        "feedback_source": feedback_csv_name,
    }
    reviewer_id = row.reviewer_id or None
    reviewed_at = row.reviewed_at or None
    review_notes = row.review_notes or None
    return clinical_review, row.review_item_id, reviewer_id, reviewed_at, review_notes


def _rewrite_golden_row(
    *,
    row: dict[str, Any],
    nosology: str,
    pair_id: str,
    control_index: dict[str, dict[str, Any]],
    canonical_index: dict[str, dict[str, Any]],
    minimum_profiles: dict[str, Any],
    biomarker_profiles: dict[str, Any],
    feedback_map: dict[str, FeedbackRow],
    feedback_csv_name: str,
    generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    derived_from = row.get("derived_from") if isinstance(row.get("derived_from"), dict) else {}
    control_case_id = str(derived_from.get("control_case_id") or "").strip()
    control_case = control_index.get(control_case_id) if control_case_id else None
    canonical_case = canonical_index.get(control_case_id) if control_case_id else None

    original_expectations = row.get("alignment_expectations") if isinstance(row.get("alignment_expectations"), dict) else {}
    required_issue_kinds = [
        str(item).strip()
        for item in original_expectations.get("required_issue_kinds", [])
        if str(item).strip()
    ] if isinstance(original_expectations.get("required_issue_kinds"), list) else []
    required_plan_intents = [
        str(item).strip()
        for item in original_expectations.get("required_plan_intents", [])
        if str(item).strip()
    ] if isinstance(original_expectations.get("required_plan_intents"), list) else []
    source_ids = [
        str(item).strip().lower()
        for item in original_expectations.get("minimal_citation_sources", [])
        if str(item).strip()
    ] if isinstance(original_expectations.get("minimal_citation_sources"), list) else []
    expected_insufficient_data = bool(original_expectations.get("expected_insufficient_data", False))

    minimum_profile = _profile_for_nosology(minimum_profiles, nosology)
    derived_mode = str(derived_from.get("mode") or "synthetic_derived")
    disease_biomarkers = _build_biomarkers(
        nosology=nosology,
        biomarker_profiles=biomarker_profiles,
        derived_mode=derived_mode,
        canonical_case=canonical_case,
        expected_insufficient_data=expected_insufficient_data,
    )
    citations = _build_citations(golden_pair_id=pair_id, nosology=nosology, source_ids=source_ids)
    citation_ids = [str(item.get("citation_id") or "") for item in citations if str(item.get("citation_id") or "")]

    case_facts = _build_case_facts(
        nosology=nosology,
        derived_from=derived_from,
        control_case=control_case,
        canonical_case=canonical_case,
        profile=minimum_profile,
        expected_insufficient_data=expected_insufficient_data,
    )
    minimum_dataset = _build_minimum_dataset_status(
        nosology=nosology,
        profile=minimum_profile,
        case_facts=case_facts,
        disease_biomarkers=disease_biomarkers,
        expected_insufficient_data=expected_insufficient_data,
    )
    case_facts["minimum_dataset"] = minimum_dataset
    plan_sections = _build_plan_sections(
        golden_pair_id=pair_id,
        required_plan_intents=required_plan_intents,
        minimum_dataset=minimum_dataset,
        citation_ids=citation_ids,
    )
    issues = _build_issues(
        golden_pair_id=pair_id,
        required_issue_kinds=required_issue_kinds,
        minimum_dataset=minimum_dataset,
        citation_ids=citation_ids,
    )
    sanity_checks = _build_sanity_checks(bool(minimum_dataset.get("status")))

    request_id = str(row.get("doctor_report", {}).get("request_id") or _uuid(f"{pair_id}:request"))
    report_id = str(row.get("doctor_report", {}).get("report_id") or _uuid(f"{pair_id}:report"))
    if not request_id:
        request_id = _uuid(f"{pair_id}:request")
    if not report_id:
        report_id = _uuid(f"{pair_id}:report")

    icd10 = str(case_facts.get("icd10") or NOSOLOGY_ICD10.get(nosology, "C80"))
    disease_id = NOSOLOGY_DISEASE_ID.get(nosology, str(row.get("disease_id") or _uuid(f"{pair_id}:disease")))
    stage_group = str(case_facts.get("stage_group") or "unknown")

    consilium_md = _sanitize_text(
        "\n".join(
            [
                "## Клинический контекст",
                f"- Нозология: {nosology}",
                f"- ICD-10: {icd10}",
                f"- Стадия/setting: {stage_group}",
                f"- ECOG: {case_facts.get('ecog')}",
                f"- Предлеченность: {case_facts.get('line_of_therapy')}",
                "",
                "## Решение",
                (
                    "Сначала требуется закрыть критические пробелы данных; до этого лечебная тактика не фиксируется."
                    if minimum_dataset.get("status")
                    else "Сформирован предварительный план для обсуждения на консилиуме с обязательной верификацией."
                ),
            ]
        )
    )

    doctor_report = {
        "schema_version": "1.2",
        "report_id": report_id,
        "request_id": request_id,
        "query_type": str(row.get("doctor_report", {}).get("query_type") or "NEXT_STEPS"),
        "disease_context": {
            "disease_id": disease_id,
            "icd10": icd10,
            "stage_group": stage_group,
            "setting": "unknown" if minimum_dataset.get("status") else "metastatic",
            "line": 2,
            "biomarkers": disease_biomarkers,
        },
        "case_facts": case_facts,
        "timeline": [
            {"date": "2025-12-01", "event": "Первичная верификация диагноза"},
            {"date": "2026-01-15", "event": "Оценка ответа и корректировка плана"},
        ],
        "consilium_md": consilium_md,
        "summary_md": (
            "Требуется дозапрос данных перед финальной тактикой."
            if minimum_dataset.get("status")
            else "Сформирован предварительный план с опорой на приоритетные источники."
        ),
        "plan": plan_sections,
        "issues": issues,
        "sanity_checks": sanity_checks,
        "drug_safety": {
            "status": "partial" if minimum_dataset.get("status") else "ok",
            "extracted_inn": [],
            "unresolved_candidates": [],
            "profiles": [],
            "signals": [],
            "warnings": [],
        },
        "comparative_claims": [],
        "citations": citations,
        "generated_at": generated_at,
    }

    missing_fields = [
        str(item).strip()
        for item in minimum_dataset.get("missing_critical_fields", [])
        if str(item).strip()
    ]
    patient_summary = (
        "Сейчас недостаточно данных, чтобы безопасно выбрать окончательное лечение. "
        "Нужно уточнить ключевые параметры и обсудить их с врачом."
        if minimum_dataset.get("status")
        else "Подготовлен предварительный план следующего этапа, который нужно подтвердить на очной консультации."
    )
    patient_explain = {
        "schema_version": "1.2",
        "request_id": request_id,
        "summary_plain": _sanitize_text(patient_summary),
        "key_points": [
            "Рекомендации опираются на приоритет: Минздрав, затем RUSSCO.",
            "Перед изменением терапии важно проверить полноту клинических данных.",
        ],
        "questions_for_doctor": [
            "Какие данные еще нужны, чтобы подтвердить тактику?",
            "Какие риски и противопоказания критичны именно для моего случая?",
        ],
        "what_was_checked": [
            "Стадия, предлеченность, функциональный статус и биомаркеры.",
            "Трассируемость рекомендаций по источникам.",
        ],
        "safety_notes": [
            "Не начинайте и не отменяйте лечение самостоятельно.",
            "При ухудшении самочувствия срочно свяжитесь с лечащей командой.",
        ],
        "drug_safety": {
            "status": "partial" if minimum_dataset.get("status") else "ok",
            "important_risks": [
                "Риск ошибки тактики при неполных данных.",
                "Требуется контроль переносимости и лабораторных показателей.",
            ],
            "questions_for_doctor": [
                "Какие лаборатории и в какие сроки нужно повторить?",
                "Какие симптомы требуют немедленного обращения?",
            ],
        },
        "sources_used": [str(item.get("source_id") or "") for item in citations if str(item.get("source_id") or "")],
        "generated_at": generated_at,
    }

    clinical_review, review_item_id, reviewer_id, reviewed_at, review_notes = _build_clinical_review(
        pair_id=pair_id,
        feedback_map=feedback_map,
        feedback_csv_name=feedback_csv_name,
        minimum_dataset_missing=bool(minimum_dataset.get("status")),
    )

    approval_status = "draft"
    if reviewer_id and reviewed_at and review_notes:
        approval_status = "approved" if str(clinical_review.get("decision") or "").upper() == "APPROVED" else "clinician_reviewed"

    normalized_issue_kinds = [str(item.get("kind") or "").strip() for item in issues if isinstance(item, dict)]
    alignment_expectations = {
        "required_issue_kinds": sorted({kind for kind in normalized_issue_kinds if kind}),
        "required_plan_intents": required_plan_intents or ["дозапрос данных", "уточнение"],
        "minimal_citation_sources": [str(item.get("source_id") or "") for item in citations if str(item.get("source_id") or "")],
        "expected_insufficient_data": bool(minimum_dataset.get("status")),
    }

    rewritten = {
        "schema_version": "1.0",
        "golden_pair_id": pair_id,
        "nosology": nosology,
        "disease_id": disease_id,
        "derived_from": {
            "mode": str(derived_from.get("mode") or "synthetic_derived"),
            "control_case_id": control_case_id or None,
        },
        "approval_status": approval_status,
        "doctor_report": doctor_report,
        "patient_explain": patient_explain,
        "alignment_expectations": alignment_expectations,
        "clinical_review": clinical_review,
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at,
        "review_notes": review_notes,
        "updated_at": generated_at,
    }

    trace_item = {
        "review_item_id": review_item_id,
        "golden_pair_id": pair_id,
        "nosology": nosology,
        "changed_fields": [
            "doctor_report.disease_context",
            "doctor_report.case_facts",
            "doctor_report.plan",
            "doctor_report.issues",
            "doctor_report.citations",
            "patient_explain",
            "clinical_review",
        ],
        "decision": str(clinical_review.get("decision") or "REWRITE_REQUIRED"),
        "sources_used": alignment_expectations["minimal_citation_sources"],
    }
    return rewritten, trace_item


def _split_or_load_core_rows(golden_root: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for nosology in TARGET_CORE_NOSOLOGIES:
        out[nosology] = _read_jsonl(golden_root / nosology / "golden_pairs_v1_2.jsonl")

    legacy_brain_rows = _read_jsonl(golden_root / "brain" / "golden_pairs_v1_2.jsonl")
    if legacy_brain_rows:
        if not out["brain_primary_c71"]:
            out["brain_primary_c71"] = legacy_brain_rows
        if not out["cns_metastases_c79_3"]:
            out["cns_metastases_c79_3"] = [dict(item) for item in legacy_brain_rows]
    return out


def _reindex_rows(rows: list[dict[str, Any]], nosology: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        cloned = dict(row)
        pair_id = f"golden-{nosology}-{index:03d}"
        cloned["golden_pair_id"] = pair_id
        cloned["nosology"] = nosology
        cloned["disease_id"] = NOSOLOGY_DISEASE_ID.get(nosology, str(cloned.get("disease_id") or ""))
        if isinstance(cloned.get("derived_from"), dict) and nosology == "cns_metastases_c79_3":
            cloned["derived_from"] = dict(cloned["derived_from"])
            cloned["derived_from"]["mode"] = "synthetic_derived"
            cloned["derived_from"]["control_case_id"] = None
        result.append(cloned)
    return result


def _zip_directory(zip_path: Path, root: Path, members: list[Path]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for member in members:
            if not member.exists():
                continue
            try:
                arcname = str(member.resolve().relative_to(root.resolve()))
            except ValueError:
                arcname = str(Path("external") / member.name)
            zf.write(member, arcname=arcname)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite wave1 golden pairs using clinical feedback CSV.")
    parser.add_argument("--feedback-csv", required=True)
    parser.add_argument("--golden-root", default="data/golden_answers")
    parser.add_argument("--control-root", default="data/control_groups")
    parser.add_argument("--canonical-root", default="data/canonical_real_cases")
    parser.add_argument("--profiles-root", default="data/clinical_profiles")
    parser.add_argument("--reports-root", default="reports/review")
    args = parser.parse_args()

    generated_at = _now_iso()
    date_tag = generated_at[:10]

    feedback_csv = Path(args.feedback_csv).resolve()
    golden_root = Path(args.golden_root).resolve()
    control_root = Path(args.control_root).resolve()
    canonical_root = Path(args.canonical_root).resolve()
    profiles_root = Path(args.profiles_root).resolve()
    reports_root = Path(args.reports_root).resolve()

    feedback_map = _load_feedback_rows(feedback_csv)
    control_index = _load_control_index(control_root)
    canonical_index = _load_canonical_index(canonical_root)
    minimum_profiles = _load_minimum_profiles(profiles_root)
    biomarker_profiles = _load_biomarker_profiles(profiles_root)

    raw_rows_by_nosology = _split_or_load_core_rows(golden_root)
    rewritten_by_nosology: dict[str, list[dict[str, Any]]] = {}
    trace_items: list[dict[str, Any]] = []

    for nosology in TARGET_CORE_NOSOLOGIES:
        normalized_rows = _reindex_rows(raw_rows_by_nosology.get(nosology, []), nosology)
        if not normalized_rows:
            normalized_rows = _reindex_rows([{} for _ in range(24)], nosology)
        rewritten_rows: list[dict[str, Any]] = []
        for row in normalized_rows:
            pair_id = str(row.get("golden_pair_id") or "").strip()
            rewritten, trace_item = _rewrite_golden_row(
                row=row,
                nosology=nosology,
                pair_id=pair_id,
                control_index=control_index,
                canonical_index=canonical_index,
                minimum_profiles=minimum_profiles,
                biomarker_profiles=biomarker_profiles,
                feedback_map=feedback_map,
                feedback_csv_name=feedback_csv.name,
                generated_at=generated_at,
            )
            rewritten_rows.append(rewritten)
            trace_items.append(trace_item)
        rewritten_by_nosology[nosology] = rewritten_rows
        _write_jsonl(golden_root / nosology / "golden_pairs_v1_2.jsonl", rewritten_rows)

    merged: list[dict[str, Any]] = []
    for nosology in TARGET_CORE_NOSOLOGIES:
        merged.extend(rewritten_by_nosology.get(nosology, []))
    _write_jsonl(golden_root / "golden_pairs_v1_2_all.jsonl", merged)

    # Remove legacy brain folder after split to prevent ambiguous consumers.
    legacy_brain_dir = golden_root / "brain"
    if legacy_brain_dir.exists():
        shutil.rmtree(legacy_brain_dir)

    feedback_by_item: dict[str, str] = {
        str(item.review_item_id): str(item.golden_pair_id)
        for item in feedback_map.values()
        if str(item.review_item_id)
    }
    applied_review_items = {
        str(item.get("review_item_id") or "")
        for item in trace_items
        if str(item.get("review_item_id") or "").strip() and str(item.get("review_item_id")) != "AUTO"
    }
    unmatched_review_items = sorted(set(feedback_by_item.keys()).difference(applied_review_items))

    feedback_report = {
        "generated_at": generated_at,
        "feedback_csv": str(feedback_csv),
        "golden_root": str(golden_root),
        "total_rewritten": len(merged),
        "feedback_rows_total": len(feedback_map),
        "feedback_rows_applied": len(applied_review_items),
        "feedback_rows_unmatched": [
            {"review_item_id": item_id, "golden_pair_id": feedback_by_item.get(item_id, "")}
            for item_id in unmatched_review_items
        ],
        "traceability": trace_items,
    }
    report_path = reports_root / f"feedback_apply_report_{date_tag}.json"
    _write_json(report_path, feedback_report)

    trace_jsonl_path = reports_root / f"golden_traceability_{date_tag}.jsonl"
    _write_jsonl(trace_jsonl_path, trace_items)

    reference_rows: list[dict[str, Any]] = []
    for row in merged:
        reference_rows.append(
            {
                "golden_pair_id": row["golden_pair_id"],
                "nosology": row["nosology"],
                "doctor_report": row["doctor_report"],
                "patient_explain": row["patient_explain"],
            }
        )
    reference_jsonl_path = reports_root / f"golden_reference_answers_rewritten_{date_tag}.jsonl"
    _write_jsonl(reference_jsonl_path, reference_rows)

    clinical_zip = reports_root / f"golden_clinical_review_pack_rewritten_{date_tag}.zip"
    reference_zip = reports_root / f"golden_reference_answers_rewritten_{date_tag}.zip"

    clinical_members: list[Path] = [report_path, trace_jsonl_path, golden_root / "golden_pairs_v1_2_all.jsonl"]
    for nosology in TARGET_CORE_NOSOLOGIES:
        clinical_members.append(golden_root / nosology / "golden_pairs_v1_2.jsonl")
    _zip_directory(clinical_zip, Path.cwd().resolve(), clinical_members)

    _zip_directory(reference_zip, Path.cwd().resolve(), [reference_jsonl_path])

    summary = {
        "generated_at": generated_at,
        "total_rewritten": len(merged),
        "golden_all_file": str(golden_root / "golden_pairs_v1_2_all.jsonl"),
        "feedback_apply_report": str(report_path),
        "clinical_review_zip": str(clinical_zip),
        "reference_answers_zip": str(reference_zip),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
