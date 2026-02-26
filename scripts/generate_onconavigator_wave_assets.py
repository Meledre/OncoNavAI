#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CORE_NOSOLOGIES: dict[str, dict[str, str]] = {
    "gastric": {
        "icd10_prefix": "C16",
        "disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e",
        "cancer_type": "gastric_cancer",
        "name_ru": "Рак желудка",
    },
    "lung": {
        "icd10_prefix": "C34",
        "disease_id": "2efcb0a0-2b4a-5f44-a247-9e1c6d9a7f42",
        "cancer_type": "nsclc_egfr",
        "name_ru": "Немелкоклеточный рак легкого",
    },
    "breast": {
        "icd10_prefix": "C50",
        "disease_id": "9d9d8f58-2a2d-5c9d-b43d-7d4af8854d38",
        "cancer_type": "breast_hr+/her2-",
        "name_ru": "Рак молочной железы",
    },
    "colorectal": {
        "icd10_prefix": "C18",
        "disease_id": "c8b1f6d0-4b6f-53cf-9e7d-6df58cc1ad5f",
        "cancer_type": "colorectal_cancer",
        "name_ru": "Колоректальный рак",
    },
    "prostate": {
        "icd10_prefix": "C61",
        "disease_id": "b53b53b7-f1e4-58ef-8d3d-5846df8f9a10",
        "cancer_type": "prostate_cancer",
        "name_ru": "Рак предстательной железы",
    },
    "rcc": {
        "icd10_prefix": "C64",
        "disease_id": "e4d29126-54ce-56cb-88dc-2dcf4954eaf9",
        "cancer_type": "renal_cell_carcinoma",
        "name_ru": "Почечно-клеточный рак",
    },
    "bladder": {
        "icd10_prefix": "C67",
        "disease_id": "d80c5e16-28df-5f1d-b88b-f76795db4c59",
        "cancer_type": "bladder_cancer",
        "name_ru": "Рак мочевого пузыря",
    },
    "brain_primary_c71": {
        "icd10_prefix": "C71",
        "disease_id": "c0a0a03b-040b-5314-9802-abef422d53b5",
        "cancer_type": "brain_primary_c71",
        "name_ru": "Первичные опухоли головного мозга",
    },
    "cns_metastases_c79_3": {
        "icd10_prefix": "C79.3",
        "disease_id": "7a2bf75a-b89e-5fb9-bc16-ee6eae6c27b8",
        "cancer_type": "cns_metastases_c79_3",
        "name_ru": "Метастазы в ЦНС",
    },
}

SHADOW_NOSOLOGIES: dict[str, dict[str, str]] = {
    "melanoma": {"icd10_prefix": "C43", "name_ru": "Меланома"},
    "head_neck": {"icd10_prefix": "C01", "name_ru": "Опухоли головы и шеи"},
    "thyroid": {"icd10_prefix": "C73", "name_ru": "Рак щитовидной железы"},
    "pancreas": {"icd10_prefix": "C25", "name_ru": "Рак поджелудочной железы"},
    "liver": {"icd10_prefix": "C22", "name_ru": "Гепатоцеллюлярный рак"},
    "esophagus": {"icd10_prefix": "C15", "name_ru": "Рак пищевода"},
    "ovary": {"icd10_prefix": "C56", "name_ru": "Рак яичника"},
    "hematology_cup_small_bowel": {"icd10_prefix": "C17", "name_ru": "Гематология, CUP и тонкая кишка"},
}

SCENARIO_MATRIX: list[tuple[str, int]] = [
    ("standard_route", 24),
    ("biomarker_branch", 18),
    ("comorbidity_contra", 12),
    ("complication_supportive", 12),
    ("insufficient_data", 10),
    ("guideline_conflict", 8),
    ("clinical_edge", 6),
    ("ambiguous_routing", 6),
]

REAL_CASES: list[tuple[str, str]] = [
    ("1.pdf", "C43.3"),
    ("2.pdf", "C61"),
    ("3.pdf", "C56"),
    ("4.pdf", "C50.8"),
    ("5.pdf", "C50.4"),
    ("6.pdf", "C43.4"),
    ("7.pdf", "C43.5"),
    ("8.pdf", "C11.1"),
    ("9.pdf", "C80.0"),
    ("10.pdf", "C61"),
    ("11.pdf", "C25.0"),
    ("12.pdf", "C20"),
    ("13.pdf", "C73"),
    ("14.pdf", "C12"),
    ("15.pdf", "C61"),
    ("16.pdf", "C17.9"),
    ("17.pdf", "C48.0"),
    ("18.pdf", "C22.0"),
    ("19.pdf", "C34.2"),
    ("20.pdf", "C04.1"),
    ("21.pdf", "C73"),
    ("22.pdf", "C50.9"),
    ("23.pdf", "C50.4"),
    ("24.pdf", "C50.4"),
    ("25.pdf", "C50.4"),
    ("26.pdf", "C61"),
    ("27.pdf", "C20"),
    ("28.pdf", "C34.1"),
    ("29.pdf", "C67.2"),
    ("30.pdf", "D44.0"),
    ("31.pdf", "C18.6"),
    ("32.pdf", "C18.7"),
    ("33.pdf", "C19"),
    ("34.pdf", "C15.4"),
    ("35.pdf", "C43.5"),
    ("36.pdf", "C01"),
    ("37.pdf", "C91.1"),
    ("38.pdf", "C17.0"),
]


def _uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"onconavigator:{seed}"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _core_nosology_by_icd10(icd10: str) -> str:
    if icd10.startswith("C16"):
        return "gastric"
    if icd10.startswith("C34"):
        return "lung"
    if icd10.startswith("C50"):
        return "breast"
    if icd10.startswith("C18") or icd10.startswith("C19") or icd10.startswith("C20"):
        return "colorectal"
    if icd10.startswith("C61"):
        return "prostate"
    if icd10.startswith("C64"):
        return "rcc"
    if icd10.startswith("C67"):
        return "bladder"
    if icd10.startswith("C71"):
        return "brain_primary_c71"
    if icd10.startswith("C79.3"):
        return "cns_metastases_c79_3"
    return ""


def _shadow_nosology_by_icd10(icd10: str) -> str:
    if icd10.startswith("C43"):
        return "melanoma"
    if icd10.startswith("C01") or icd10.startswith("C04") or icd10.startswith("C11") or icd10.startswith("C12"):
        return "head_neck"
    if icd10.startswith("C73"):
        return "thyroid"
    if icd10.startswith("C25"):
        return "pancreas"
    if icd10.startswith("C22"):
        return "liver"
    if icd10.startswith("C15"):
        return "esophagus"
    if icd10.startswith("C56"):
        return "ovary"
    return "hematology_cup_small_bowel"


def _line_of_therapy(idx: int) -> str:
    if idx % 3 == 0:
        return "1L"
    if idx % 3 == 1:
        return "2L"
    return "3L+"


def _strata(idx: int, *, line: str) -> dict[str, Any]:
    stage = ["localized", "metastatic", "recurrent"][idx % 3]
    age = ["lt50", "50_69", "ge70"][idx % 3]
    ecog = ["0_1", "2", "3+"][idx % 3]
    major_comorbidity = ["none", "cardio", "renal"][idx % 3]
    return {
        "stage_setting": stage,
        "line_of_therapy": line,
        "biomarkers_present": bool(idx % 2 == 0),
        "age_bucket": age,
        "ecog_bucket": ecog,
        "major_comorbidity": major_comorbidity,
        "urgent_complication_flag": bool(idx % 5 == 0),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def _cleanup_legacy_brain_dirs(root: Path) -> None:
    legacy_paths = [
        root / "data" / "control_groups" / "brain",
        root / "data" / "synthetic_cases" / "packs" / "brain",
        root / "data" / "golden_answers" / "brain",
        root / "data" / "canonical_real_cases" / "core" / "brain",
    ]
    for path in legacy_paths:
        if path.exists():
            shutil.rmtree(path)


def _holdout_size(n_real: int) -> int:
    holdout = min(40, int((0.2 * n_real) // 1))
    if n_real < 5:
        return 0
    if holdout == 0 and n_real >= 5:
        return 1
    return holdout


def _base_citation(source_id: str, idx: int) -> dict[str, Any]:
    citation_id = _uuid(f"citation:{source_id}:{idx}")
    source = str(source_id or "").strip().lower()
    if source == "minzdrav":
        file_uri = f"https://cr.minzdrav.gov.ru/preview-cr/{200 + idx}"
        quote = "Клиническая рекомендация: тактика зависит от стадии и клинических факторов риска."
    elif source == "russco":
        file_uri = f"https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-{idx:02d}.pdf"
        quote = "RUSSCO: решение по линии терапии принимается с учетом биомаркеров и переносимости."
    elif source == "international_guidelines":
        file_uri = "https://www.esmo.org/guidelines"
        quote = "International CPG corroborate sequencing and safety checks."
    else:
        file_uri = f"https://example.org/guidelines/{source or 'unknown'}/{idx}"
        quote = "Guideline-backed recommendation."
    return {
        "citation_id": citation_id,
        "source_id": source_id,
        "document_id": _uuid(f"document:{source_id}:{idx}"),
        "version_id": _uuid(f"version:{source_id}:{idx}"),
        "page_start": 1,
        "page_end": 2,
        "section_path": "clinical_recommendation",
        "quote": quote,
        "file_uri": file_uri,
        "score": 0.8,
    }


def _default_biomarkers_for_nosology(nosology: str) -> list[dict[str, str]]:
    normalized = str(nosology or "").strip().lower()
    mapping: dict[str, list[tuple[str, str]]] = {
        "breast": [("ER", "positive"), ("PR", "positive"), ("HER2", "negative"), ("Ki-67", "high")],
        "colorectal": [("RAS", "wild_type"), ("BRAF", "negative"), ("MSI/dMMR", "MSS/pMMR")],
        "lung": [("EGFR", "L858R"), ("ALK", "negative"), ("ROS1", "negative"), ("PD-L1", "TPS 5%")],
        "prostate": [("PSA", "elevated"), ("Testosterone", "castrate_range")],
        "rcc": [("Histology subtype", "clear_cell"), ("IMDC risk", "intermediate")],
        "bladder": [("FGFR2/3", "unknown_due_missing_data"), ("PD-L1", "CPS 10")],
        "gastric": [("HER2", "negative"), ("PD-L1 CPS", ">=5"), ("MSI/dMMR", "MSS/pMMR")],
        "brain_primary_c71": [("IDH1/2", "wild_type"), ("MGMT", "methylated"), ("1p/19q", "non-codeleted")],
        "cns_metastases_c79_3": [("Primary tumor type", "lung_adenocarcinoma"), ("Driver mutation status", "unknown_due_missing_data")],
    }
    selected = mapping.get(normalized) or [("Tumor marker profile", "unknown_due_missing_data")]
    return [{"name": name, "value": value} for name, value in selected]


def _scenario_expectations(family: str) -> dict[str, Any]:
    if family == "standard_route":
        return {
            "required_issue_kinds": ["other"],
            "required_plan_intents": ["оценка ответа", "системная терапия"],
            "minimal_citation_sources": ["minzdrav"],
            "expected_insufficient_data": False,
            "min_issues": 1,
        }
    if family == "biomarker_branch":
        return {
            "required_issue_kinds": ["missing_data"],
            "required_plan_intents": ["биомаркер", "уточнение"],
            "minimal_citation_sources": ["minzdrav"],
            "expected_insufficient_data": False,
            "min_issues": 1,
        }
    if family == "comorbidity_contra":
        return {
            "required_issue_kinds": ["contraindication"],
            "required_plan_intents": ["коррекция", "безопасность"],
            "minimal_citation_sources": ["minzdrav"],
            "expected_insufficient_data": False,
            "min_issues": 1,
        }
    if family == "complication_supportive":
        return {
            "required_issue_kinds": ["deviation"],
            "required_plan_intents": ["сопроводительная терапия", "контроль токсичности"],
            "minimal_citation_sources": ["minzdrav"],
            "expected_insufficient_data": False,
            "min_issues": 1,
        }
    if family == "insufficient_data":
        return {
            "required_issue_kinds": ["missing_data"],
            "required_plan_intents": ["дозапрос данных", "уточнение"],
            "minimal_citation_sources": ["minzdrav"],
            "expected_insufficient_data": True,
            "min_issues": 1,
        }
    if family == "guideline_conflict":
        return {
            "required_issue_kinds": ["inconsistency"],
            "required_plan_intents": ["разбор конфликта", "мультидисциплинарный консилиум"],
            "minimal_citation_sources": ["minzdrav", "russco"],
            "expected_insufficient_data": False,
            "min_issues": 1,
        }
    if family == "clinical_edge":
        return {
            "required_issue_kinds": ["other"],
            "required_plan_intents": ["индивидуализация", "реоценка"],
            "minimal_citation_sources": ["minzdrav"],
            "expected_insufficient_data": False,
            "min_issues": 1,
        }
    return {
        "required_issue_kinds": ["missing_data"],
        "required_plan_intents": ["маршрутизация", "уточнение нозологии"],
        "minimal_citation_sources": ["minzdrav"],
        "expected_insufficient_data": True,
        "min_issues": 1,
    }


def _build_core_control_groups(root: Path, generated_at: str, snapshot_id: str) -> dict[str, list[dict[str, Any]]]:
    by_nosology: dict[str, list[dict[str, Any]]] = {k: [] for k in CORE_NOSOLOGIES}
    for idx, (source_file, icd10) in enumerate(REAL_CASES, start=1):
        nosology = _core_nosology_by_icd10(icd10)
        if not nosology:
            continue
        disease = CORE_NOSOLOGIES[nosology]
        line = _line_of_therapy(idx)
        entry = {
            "schema_version": "1.0",
            "snapshot_id": snapshot_id,
            "generated_at": generated_at,
            "case_id": _uuid(f"real:{source_file}:{icd10}"),
            "source": "onko_examples_2026_02_23",
            "source_case_ref": source_file,
            "primary_icd10": icd10,
            "nosology": nosology,
            "disease_id": disease["disease_id"],
            "patient_fingerprint": _hash(f"patient:{source_file}"),
            "line_of_therapy": line,
            "event_date_window": {
                "start_date": f"2025-{(idx % 12) + 1:02d}-01",
                "end_date": f"2025-{(idx % 12) + 1:02d}-28",
                "precision": "month",
            },
            "strata": _strata(idx, line=line),
            "holdout_candidate": True,
            "real_data_gap": False,
            "provenance": {
                "source_zip": "/Users/meledre/Downloads/ОНКО ПРИМЕРЫ.zip",
                "source_file": source_file,
                "extraction_method": "pdfkit_text + icd10_line",
            },
        }
        by_nosology[nosology].append(entry)

    control_root = root / "data" / "control_groups"
    for nosology in CORE_NOSOLOGIES:
        entries = sorted(by_nosology[nosology], key=lambda item: str(item["case_id"]))
        _write_jsonl(control_root / nosology / "real_cases_manifest_v1.jsonl", entries)

        holdout_size = _holdout_size(len(entries))
        holdout_case_ids = [item["case_id"] for item in entries[:holdout_size]]
        holdout_payload = {
            "schema_version": "1.0",
            "snapshot_id": snapshot_id,
            "generated_at": generated_at,
            "nosology": nosology,
            "n_real": len(entries),
            "holdout_size": holdout_size,
            "holdout_case_ids": holdout_case_ids,
            "policy": {
                "formula": "min(40, floor(0.2 * N_real)); if N_real < 5 => 0; if N_real >= 5 and holdout==0 => 1",
                "cap": 40,
                "fraction": 0.2,
            },
            "real_data_gap": len(entries) == 0,
        }
        _write_json(control_root / nosology / "holdout_v1.json", holdout_payload)
    return by_nosology


def _build_shadow_control_groups(root: Path, generated_at: str, snapshot_id: str) -> dict[str, list[dict[str, Any]]]:
    by_nosology: dict[str, list[dict[str, Any]]] = {k: [] for k in SHADOW_NOSOLOGIES}
    for idx, (source_file, icd10) in enumerate(REAL_CASES, start=1):
        if _core_nosology_by_icd10(icd10):
            continue
        nosology = _shadow_nosology_by_icd10(icd10)
        meta = SHADOW_NOSOLOGIES[nosology]
        entry = {
            "schema_version": "1.0",
            "snapshot_id": snapshot_id,
            "generated_at": generated_at,
            "case_id": _uuid(f"shadow-real:{source_file}:{icd10}"),
            "source": "onko_examples_2026_02_23",
            "source_case_ref": source_file,
            "primary_icd10": icd10,
            "nosology": nosology,
            "disease_id": _uuid(f"shadow-disease:{nosology}"),
            "patient_fingerprint": _hash(f"shadow-patient:{source_file}"),
            "line_of_therapy": _line_of_therapy(idx),
            "event_date_window": {
                "start_date": f"2025-{(idx % 12) + 1:02d}-01",
                "end_date": f"2025-{(idx % 12) + 1:02d}-28",
                "precision": "month",
            },
            "strata": _strata(idx, line=_line_of_therapy(idx)),
            "holdout_candidate": False,
            "real_data_gap": False,
            "provenance": {
                "source_zip": "/Users/meledre/Downloads/ОНКО ПРИМЕРЫ.zip",
                "source_file": source_file,
                "icd10_prefix_scope": meta["icd10_prefix"],
                "extraction_method": "pdfkit_text + icd10_line",
            },
        }
        by_nosology[nosology].append(entry)

    shadow_root = root / "data" / "control_groups_shadow"
    for nosology in SHADOW_NOSOLOGIES:
        entries = sorted(by_nosology[nosology], key=lambda item: str(item["case_id"]))
        _write_jsonl(shadow_root / nosology / "real_cases_manifest_v1.jsonl", entries)
    return by_nosology


def _line_to_int(value: str) -> int:
    text = str(value or "").strip().lower()
    if text.startswith("1"):
        return 1
    if text.startswith("2"):
        return 2
    if text.startswith("3"):
        return 3
    return 0


def _manifest_to_case_json(manifest: dict[str, Any], *, case_kind: str) -> dict[str, Any]:
    case_id = str(manifest.get("case_id") or "")
    icd10 = str(manifest.get("primary_icd10") or "")
    line_of_therapy = str(manifest.get("line_of_therapy") or "unknown")
    line_int = _line_to_int(line_of_therapy)
    source_case_ref = str(manifest.get("source_case_ref") or "")
    event_date = str((manifest.get("event_date_window") or {}).get("start_date") or "2025-01-01")
    source_zip = str((manifest.get("provenance") or {}).get("source_zip") or "")
    notes = (
        "Канонический кейс сформирован из real-case manifest. "
        f"type={case_kind}; source={source_case_ref}; source_zip={source_zip}; "
        "данные обезличены."
    )
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "data_mode": "DEID",
        "import_profile": "KIN_PDF",
        "patient": {
            "sex": "unknown",
            "ecog": 1,
        },
        "diagnoses": [
            {
                "diagnosis_id": _uuid(f"diagnosis:{case_id}"),
                "disease_id": str(manifest.get("disease_id") or _uuid(f"disease:{case_id}")),
                "icd10": icd10,
                "stage": {
                    "system": "UNKNOWN",
                    "stage_group": str((manifest.get("strata") or {}).get("stage_setting") or "unknown"),
                    "precision": "unknown",
                },
                "biomarkers": [
                    {
                        "name": "biomarker_presence",
                        "value": "present" if bool((manifest.get("strata") or {}).get("biomarkers_present")) else "unknown",
                        "precision": "unknown",
                    }
                ],
                "timeline": [
                    {
                        "event_id": _uuid(f"timeline:{case_id}:{event_date}"),
                        "date": event_date,
                        "precision": "month",
                        "type": "other",
                        "label": "Real-case normalization event",
                        "details": f"line_of_therapy={line_of_therapy}",
                    }
                ],
                "last_plan": {
                    "date": event_date,
                    "precision": "month",
                    "regimen": "unspecified_real_case_regimen",
                    "intent": "unknown",
                    "line": line_int,
                },
            }
        ],
        "attachments": [],
        "notes": notes,
    }


def _dedupe_manifest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in entries:
        key = (
            str(item.get("patient_fingerprint") or ""),
            str(item.get("primary_icd10") or ""),
            str(item.get("line_of_therapy") or ""),
            str((item.get("event_date_window") or {}).get("start_date") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _build_canonical_real_cases(
    root: Path,
    *,
    core_control: dict[str, list[dict[str, Any]]],
    shadow_control: dict[str, list[dict[str, Any]]],
) -> None:
    canonical_root = root / "data" / "canonical_real_cases"
    all_core_rows: list[dict[str, Any]] = []
    all_shadow_rows: list[dict[str, Any]] = []

    for nosology, rows in core_control.items():
        deduped = _dedupe_manifest_entries(rows)
        normalized = [_manifest_to_case_json(item, case_kind="core") for item in deduped]
        all_core_rows.extend(normalized)
        _write_jsonl(canonical_root / "core" / nosology / "canonical_cases_v1.jsonl", normalized)

    for nosology, rows in shadow_control.items():
        deduped = _dedupe_manifest_entries(rows)
        normalized = [_manifest_to_case_json(item, case_kind="shadow") for item in deduped]
        all_shadow_rows.extend(normalized)
        _write_jsonl(canonical_root / "shadow" / nosology / "canonical_cases_v1.jsonl", normalized)

    _write_jsonl(canonical_root / "core" / "canonical_cases_v1_all.jsonl", all_core_rows)
    _write_jsonl(canonical_root / "shadow" / "canonical_cases_v1_all.jsonl", all_shadow_rows)


def _build_core_synthetic_cases(
    root: Path,
    generated_at: str,
) -> dict[str, list[dict[str, Any]]]:
    by_nosology: dict[str, list[dict[str, Any]]] = {}
    synthetic_root = root / "data" / "synthetic_cases" / "packs"

    for nosology, meta in CORE_NOSOLOGIES.items():
        items: list[dict[str, Any]] = []
        case_seq = 1
        for family, amount in SCENARIO_MATRIX:
            for index in range(1, amount + 1):
                case_id = f"wave1-{nosology}-{case_seq:03d}"
                scenario_id = f"{nosology}-{family}-{index:03d}"
                expected = _scenario_expectations(family)
                item = {
                    "id": case_id,
                    "nosology": nosology,
                    "scenario_id": scenario_id,
                    "scenario_tags": [family, "wave1_core"],
                    "source_lineage": {
                        "primary_source": "minzdrav",
                        "secondary_sources": ["russco"],
                        "supplementary_refs": [],
                        "conflict_policy": "minzdrav_gt_russco_gt_supplementary",
                        "source_readiness": (
                            "pending_manual_upload"
                            if nosology == "brain_primary_c71"
                            else ("partial" if nosology == "cns_metastases_c79_3" else "complete")
                        ),
                        "manual_source_backlog": (
                            ["EANO primary CNS tumor guideline pack", "Минздрав C71 профиль (ручная дозагрузка)"]
                            if nosology == "brain_primary_c71"
                            else (
                                ["EANO-ESMO brain metastases guideline pack"] if nosology == "cns_metastases_c79_3" else []
                            )
                        ),
                    },
                    "golden_pair_id": f"golden-{nosology}-{((case_seq - 1) % 24) + 1:03d}",
                    "request": {
                        "schema_version": "0.1",
                        "request_id": case_id,
                        "case": {
                            "cancer_type": meta["cancer_type"],
                            "language": "ru",
                            "notes": (
                                f"Синтетический кейс {meta['name_ru']} ({family}), "
                                f"матрица сценариев wave1, generated_at={generated_at}."
                            ),
                        },
                        "treatment_plan": {
                            "plan_text": (
                                "Проверка тактики лечения и сопроводительной терапии с учетом "
                                f"сценария {family}."
                            )
                        },
                        "return_patient_explain": True,
                    },
                    "expected": {
                        "min_issues": expected["min_issues"],
                        "required_issue_kinds": expected["required_issue_kinds"],
                        "required_plan_intents": expected["required_plan_intents"],
                        "minimal_citation_sources": expected["minimal_citation_sources"],
                        "expected_insufficient_data": expected["expected_insufficient_data"],
                    },
                    "real_data_gap": nosology in {"gastric", "rcc", "brain_primary_c71", "cns_metastases_c79_3"},
                }
                items.append(item)
                case_seq += 1

        by_nosology[nosology] = items
        _write_json(synthetic_root / nosology / "cases_v1.json", items)
    merged: list[dict[str, Any]] = []
    for nosology in CORE_NOSOLOGIES:
        merged.extend(by_nosology[nosology])
    _write_json(root / "data" / "synthetic_cases" / "cases_v1_all.json", merged)
    return by_nosology


def _build_shadow_synthetic_cases(root: Path) -> dict[str, list[dict[str, Any]]]:
    by_nosology: dict[str, list[dict[str, Any]]] = {}
    shadow_root = root / "data" / "synthetic_cases" / "packs_shadow"

    for nosology, meta in SHADOW_NOSOLOGIES.items():
        items: list[dict[str, Any]] = []
        for index in range(1, 25):
            family = "shadow_standard" if index <= 12 else "shadow_edge"
            expected = {
                "min_issues": 1,
                "required_issue_kinds": ["missing_data" if family == "shadow_edge" else "other"],
                "required_plan_intents": ["маршрутизация", "уточнение"],
                "minimal_citation_sources": ["minzdrav"],
                "expected_insufficient_data": family == "shadow_edge",
            }
            items.append(
                {
                    "id": f"wave2-{nosology}-{index:03d}",
                    "nosology": nosology,
                    "scenario_id": f"{nosology}-{family}-{index:03d}",
                    "scenario_tags": [family, "wave2_shadow"],
                    "source_lineage": {
                        "primary_source": "minzdrav",
                        "secondary_sources": ["russco"],
                        "supplementary_refs": [],
                        "conflict_policy": "minzdrav_gt_russco_gt_supplementary",
                        "source_readiness": "partial",
                        "manual_source_backlog": [],
                    },
                    "golden_pair_id": f"golden-lite-{nosology}-{((index - 1) % 6) + 1:03d}",
                    "request": {
                        "schema_version": "0.1",
                        "request_id": f"wave2-{nosology}-{index:03d}",
                        "case": {
                            "cancer_type": nosology,
                            "language": "ru",
                            "notes": f"Shadow synthetic lite: {meta['name_ru']} case #{index}.",
                        },
                        "treatment_plan": {"plan_text": "Shadow validation case."},
                        "return_patient_explain": True,
                    },
                    "expected": expected,
                    "real_data_gap": False,
                }
            )
        by_nosology[nosology] = items
        _write_json(shadow_root / nosology / "cases_shadow_v1.json", items)
    return by_nosology


def _build_golden_pair(
    *,
    golden_pair_id: str,
    nosology: str,
    disease_id: str,
    icd10_prefix: str,
    issue_kind: str,
    plan_intents: list[str],
    citation_sources: list[str],
    expected_insufficient_data: bool,
    approval_status: str,
    mode: str,
    control_case_id: str = "",
    reviewer_id: str | None = None,
    reviewed_at: str | None = None,
    review_notes: str | None = None,
) -> dict[str, Any]:
    request_id = _uuid(f"request:{golden_pair_id}")
    report_id = _uuid(f"report:{golden_pair_id}")
    citation_rows = [_base_citation(source_id, idx + 1) for idx, source_id in enumerate(citation_sources)]
    citation_ids = [item["citation_id"] for item in citation_rows]
    step_id = _uuid(f"step:{golden_pair_id}")
    issue_id = _uuid(f"issue:{golden_pair_id}")
    now = _now_iso()

    doctor_report = {
        "schema_version": "1.2",
        "report_id": report_id,
        "request_id": request_id,
        "query_type": "NEXT_STEPS",
        "disease_context": {
            "disease_id": disease_id,
            "icd10": icd10_prefix,
            "setting": "metastatic" if expected_insufficient_data else "recurrent",
            "line": 2,
            "biomarkers": _default_biomarkers_for_nosology(nosology),
        },
        "case_facts": {
            "nosology": nosology,
            "expected_insufficient_data": expected_insufficient_data,
        },
        "timeline": [
            {"date": "2025-12-01", "event": "Диагноз подтвержден"},
            {"date": "2026-01-15", "event": "Оценка ответа"},
        ],
        "consilium_md": (
            "## Ключевые факты\n"
            f"- Нозология: {nosology}\n"
            f"- ICD-10: {icd10_prefix}\n"
            f"- Контур: {mode}\n"
            "\n## Решение\n"
            "Предварительный план требует клинического консилиума и проверки полноты данных."
        ),
        "summary_md": "Сводка для врача сформирована по эталонному сценарию.",
        "plan": [
            {
                "section": "treatment",
                "title": "Тактика",
                "steps": [
                    {
                        "step_id": step_id,
                        "text": f"Выполнить: {plan_intents[0]} и документировать результат.",
                        "priority": "high",
                        "rationale": "Эталонный шаг для сценарной валидации.",
                        "citation_ids": [citation_ids[0]],
                        "depends_on_missing_data": ["diagnoses.0.last_plan"] if expected_insufficient_data else [],
                    }
                ],
            }
        ],
        "issues": [
            {
                "issue_id": issue_id,
                "severity": "warning" if issue_kind != "contraindication" else "critical",
                "kind": issue_kind,
                "summary": f"Сценарная проверка: {issue_kind}.",
                "details": "Эталонный issue для golden alignment.",
                "citation_ids": [citation_ids[0]],
            }
        ],
        "sanity_checks": [
            {"check_id": "case_facts_stage_present", "status": "pass", "details": "ok"},
            {"check_id": "case_facts_metastases_present", "status": "pass", "details": "ok"},
            {"check_id": "case_facts_treatment_history_present", "status": "pass", "details": "ok"},
            {"check_id": "case_facts_biomarkers_present", "status": "pass", "details": "ok"},
            {"check_id": "consilium_contains_stage", "status": "pass", "details": "ok"},
        ],
        "drug_safety": {
            "status": "ok",
            "extracted_inn": [],
            "unresolved_candidates": [],
            "profiles": [],
            "signals": [],
            "warnings": [],
        },
        "citations": citation_rows,
        "generated_at": now,
    }

    patient_explain = {
        "schema_version": "1.2",
        "request_id": request_id,
        "summary_plain": "Мы подготовили понятный план обсуждения с лечащим врачом.",
        "key_points": [
            "Решение опирается на клинические рекомендации и данные вашей карты.",
            "Приоритет источников: Минздрав, затем RUSSCO.",
        ],
        "questions_for_doctor": [
            "Какая цель следующего этапа лечения и как будем оценивать ответ?",
            "Какие риски терапии и как их контролировать?",
        ],
        "what_was_checked": [
            "Стадия заболевания, предыдущая терапия и данные биомаркеров.",
            "Согласованность плана с рекомендациями.",
        ],
        "safety_notes": [
            "Не меняйте лечение самостоятельно.",
            "При новых симптомах обратитесь к лечащему врачу незамедлительно.",
        ],
        "drug_safety": {
            "status": "ok",
            "important_risks": ["Нужен мониторинг переносимости терапии."],
            "questions_for_doctor": ["Какие показатели нужно контролировать между визитами?"],
        },
        "sources_used": citation_sources,
        "generated_at": now,
    }

    return {
        "schema_version": "1.0",
        "golden_pair_id": golden_pair_id,
        "nosology": nosology,
        "disease_id": disease_id,
        "derived_from": {
            "mode": mode,
            "control_case_id": control_case_id or None,
        },
        "approval_status": approval_status,
        "doctor_report": doctor_report,
        "patient_explain": patient_explain,
        "alignment_expectations": {
            "required_issue_kinds": [issue_kind],
            "required_plan_intents": plan_intents,
            "minimal_citation_sources": citation_sources,
            "expected_insufficient_data": expected_insufficient_data,
        },
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at,
        "review_notes": review_notes,
        "updated_at": now,
    }


def _build_core_goldens(
    root: Path,
    control_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    golden_root = root / "data" / "golden_answers"
    by_nosology: dict[str, list[dict[str, Any]]] = {}

    for nosology, meta in CORE_NOSOLOGIES.items():
        rows: list[dict[str, Any]] = []
        control_case_ids = [item["case_id"] for item in control_groups[nosology]]
        real_derived_limit = min(len(control_case_ids), 24)

        for i in range(1, 25):
            golden_pair_id = f"golden-{nosology}-{i:03d}"
            mode = "real_derived" if i <= real_derived_limit else "synthetic_derived"
            control_case_id = control_case_ids[i - 1] if i <= real_derived_limit else ""
            family = SCENARIO_MATRIX[(i - 1) % len(SCENARIO_MATRIX)][0]
            exp = _scenario_expectations(family)
            issue_kind = exp["required_issue_kinds"][0]
            plan_intents = exp["required_plan_intents"]
            sources = exp["minimal_citation_sources"]
            row = _build_golden_pair(
                golden_pair_id=golden_pair_id,
                nosology=nosology,
                disease_id=meta["disease_id"],
                icd10_prefix=meta["icd10_prefix"],
                issue_kind=issue_kind,
                plan_intents=plan_intents,
                citation_sources=sources,
                expected_insufficient_data=bool(exp["expected_insufficient_data"]),
                approval_status="draft",
                mode=mode,
                control_case_id=control_case_id,
            )
            rows.append(row)

        by_nosology[nosology] = rows
        _write_jsonl(golden_root / nosology / "golden_pairs_v1_2.jsonl", rows)
    merged: list[dict[str, Any]] = []
    for nosology in CORE_NOSOLOGIES:
        merged.extend(by_nosology[nosology])
    _write_jsonl(golden_root / "golden_pairs_v1_2_all.jsonl", merged)
    return by_nosology


def _build_shadow_goldens(root: Path) -> dict[str, list[dict[str, Any]]]:
    shadow_root = root / "data" / "golden_answers_shadow"
    by_nosology: dict[str, list[dict[str, Any]]] = {}
    for nosology, meta in SHADOW_NOSOLOGIES.items():
        rows: list[dict[str, Any]] = []
        disease_id = _uuid(f"shadow-disease:{nosology}")
        for i in range(1, 7):
            row = _build_golden_pair(
                golden_pair_id=f"golden-lite-{nosology}-{i:03d}",
                nosology=nosology,
                disease_id=disease_id,
                icd10_prefix=meta["icd10_prefix"],
                issue_kind="missing_data",
                plan_intents=["маршрутизация", "уточнение"],
                citation_sources=["minzdrav"],
                expected_insufficient_data=True,
                approval_status="shadow_lite",
                mode="synthetic_derived",
                control_case_id="",
            )
            rows.append(row)
        by_nosology[nosology] = rows
        _write_jsonl(shadow_root / nosology / "golden_pairs_v1_2_lite.jsonl", rows)
    return by_nosology


def _build_coverage_report(
    root: Path,
    *,
    generated_at: str,
    snapshot_id: str,
    core_control: dict[str, list[dict[str, Any]]],
    shadow_control: dict[str, list[dict[str, Any]]],
    core_synthetic: dict[str, list[dict[str, Any]]],
    shadow_synthetic: dict[str, list[dict[str, Any]]],
    core_goldens: dict[str, list[dict[str, Any]]],
    shadow_goldens: dict[str, list[dict[str, Any]]],
) -> None:
    core_metrics: dict[str, Any] = {}
    for nosology in CORE_NOSOLOGIES:
        n_real = len(core_control[nosology])
        core_metrics[nosology] = {
            "real_cases": n_real,
            "holdout_size": _holdout_size(n_real),
            "synthetic_cases": len(core_synthetic[nosology]),
            "golden_pairs": len(core_goldens[nosology]),
            "real_data_gap": n_real == 0,
        }

    shadow_metrics: dict[str, Any] = {}
    for nosology in SHADOW_NOSOLOGIES:
        shadow_metrics[nosology] = {
            "real_cases": len(shadow_control[nosology]),
            "synthetic_lite_cases": len(shadow_synthetic[nosology]),
            "golden_lite_pairs": len(shadow_goldens[nosology]),
            "hard_ci_gates": False,
        }

    report = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "wave1": {
            "status": "core_full",
            "nosologies": core_metrics,
            "thresholds": {
                "recall_like": 0.88,
                "evidence_valid_ratio": 0.95,
                "insufficient_data_ratio": 0.25,
                "sanity_fail_rate": 0.05,
                "citation_coverage": 0.9,
                "key_fact_retention": 0.9,
            },
        },
        "wave2": {
            "status": "shadow_pack",
            "nosologies": shadow_metrics,
            "hard_gates_enabled": False,
        },
        "source_priority": ["minzdrav", "russco", "supplementary"],
    }
    _write_json(root / "reports" / "metrics" / "nosology_coverage_2026-02-23.json", report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OncoNavigator wave1/wave2 synthetic, control and golden artifacts")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    generated_at = _now_iso()
    snapshot_id = f"onconav-wave1-{generated_at[:10]}"
    _cleanup_legacy_brain_dirs(root)

    core_control = _build_core_control_groups(root, generated_at, snapshot_id)
    shadow_control = _build_shadow_control_groups(root, generated_at, snapshot_id)
    core_synthetic = _build_core_synthetic_cases(root, generated_at)
    shadow_synthetic = _build_shadow_synthetic_cases(root)
    core_goldens = _build_core_goldens(root, core_control)
    shadow_goldens = _build_shadow_goldens(root)
    _build_canonical_real_cases(
        root,
        core_control=core_control,
        shadow_control=shadow_control,
    )
    _build_coverage_report(
        root,
        generated_at=generated_at,
        snapshot_id=snapshot_id,
        core_control=core_control,
        shadow_control=shadow_control,
        core_synthetic=core_synthetic,
        shadow_synthetic=shadow_synthetic,
        core_goldens=core_goldens,
        shadow_goldens=shadow_goldens,
    )

    summary = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "core": {
            nosology: {
                "real_cases": len(core_control[nosology]),
                "synthetic_cases": len(core_synthetic[nosology]),
                "golden_pairs": len(core_goldens[nosology]),
            }
            for nosology in CORE_NOSOLOGIES
        },
        "shadow": {
            nosology: {
                "real_cases": len(shadow_control[nosology]),
                "synthetic_lite_cases": len(shadow_synthetic[nosology]),
                "golden_lite_pairs": len(shadow_goldens[nosology]),
            }
            for nosology in SHADOW_NOSOLOGIES
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
