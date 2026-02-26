from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


CORE_DISEASE_IDS: dict[str, str] = {
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _infer_core_nosology(icd10: str) -> str:
    value = str(icd10 or "").upper()
    if value.startswith("C16"):
        return "gastric"
    if value.startswith("C34"):
        return "lung"
    if value.startswith("C50"):
        return "breast"
    if value.startswith("C18") or value.startswith("C19") or value.startswith("C20"):
        return "colorectal"
    if value.startswith("C61"):
        return "prostate"
    if value.startswith("C64"):
        return "rcc"
    if value.startswith("C67"):
        return "bladder"
    if value.startswith("C71"):
        return "brain_primary_c71"
    if value.startswith("C79.3"):
        return "cns_metastases_c79_3"
    return ""


def _infer_shadow_nosology(icd10: str) -> str:
    value = str(icd10 or "").upper()
    if value.startswith("C43"):
        return "melanoma"
    if value.startswith("C01") or value.startswith("C04") or value.startswith("C11") or value.startswith("C12"):
        return "head_neck"
    if value.startswith("C73"):
        return "thyroid"
    if value.startswith("C25"):
        return "pancreas"
    if value.startswith("C22"):
        return "liver"
    if value.startswith("C15"):
        return "esophagus"
    if value.startswith("C56"):
        return "ovary"
    return "hematology_cup_small_bowel"


def test_core_control_manifest_routes_match_icd10_and_disease_id() -> None:
    root = _repo_root()
    manifest_files = sorted((root / "data" / "control_groups").glob("*/real_cases_manifest_v1.jsonl"))
    assert manifest_files

    for file_path in manifest_files:
        nosology = file_path.parent.name
        if nosology not in CORE_DISEASE_IDS:
            continue
        expected_disease_id = CORE_DISEASE_IDS[nosology]
        for row in _read_jsonl(file_path):
            icd10 = str(row.get("primary_icd10") or "")
            assert _infer_core_nosology(icd10) == nosology
            assert str(row.get("disease_id")) == expected_disease_id


def test_shadow_control_manifest_routes_match_icd10_prefixes() -> None:
    root = _repo_root()
    manifest_files = sorted((root / "data" / "control_groups_shadow").glob("*/real_cases_manifest_v1.jsonl"))
    assert manifest_files

    for file_path in manifest_files:
        nosology = file_path.parent.name
        for row in _read_jsonl(file_path):
            icd10 = str(row.get("primary_icd10") or "")
            assert _infer_shadow_nosology(icd10) == nosology
            uuid.UUID(str(row.get("disease_id")))


def test_canonical_cases_keep_icd10_to_nosology_routing() -> None:
    root = _repo_root()

    core_files = sorted((root / "data" / "canonical_real_cases" / "core").glob("*/canonical_cases_v1.jsonl"))
    assert core_files
    for file_path in core_files:
        nosology = file_path.parent.name
        for row in _read_jsonl(file_path):
            diagnoses = row.get("diagnoses")
            assert isinstance(diagnoses, list) and diagnoses
            diagnosis = diagnoses[0]
            assert isinstance(diagnosis, dict)
            icd10 = str(diagnosis.get("icd10") or "")
            assert _infer_core_nosology(icd10) == nosology
            assert str(diagnosis.get("disease_id")) == CORE_DISEASE_IDS[nosology]

    shadow_files = sorted((root / "data" / "canonical_real_cases" / "shadow").glob("*/canonical_cases_v1.jsonl"))
    assert shadow_files
    for file_path in shadow_files:
        nosology = file_path.parent.name
        for row in _read_jsonl(file_path):
            diagnoses = row.get("diagnoses")
            assert isinstance(diagnoses, list) and diagnoses
            diagnosis = diagnoses[0]
            assert isinstance(diagnosis, dict)
            icd10 = str(diagnosis.get("icd10") or "")
            assert _infer_shadow_nosology(icd10) == nosology
