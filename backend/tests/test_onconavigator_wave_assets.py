from __future__ import annotations

import json
from pathlib import Path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def test_wave_asset_schemas_exist_and_are_valid_json() -> None:
    root = Path(__file__).resolve().parents[2]
    schema_root = root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas"
    files = [
        schema_root / "control_case_manifest.schema.json",
        schema_root / "synthetic_case_scenario.schema.json",
        schema_root / "golden_pair_v1_2.schema.json",
        schema_root / "nosology_minimum_dataset.schema.json",
    ]
    for file in files:
        assert file.exists(), f"missing schema file: {file}"
        payload = _read_json(file)
        assert payload.get("$schema") == "https://json-schema.org/draft/2020-12/schema"


def test_wave1_core_assets_have_expected_cardinality() -> None:
    root = Path(__file__).resolve().parents[2]
    core = [
        "gastric",
        "lung",
        "breast",
        "colorectal",
        "prostate",
        "rcc",
        "bladder",
        "brain_primary_c71",
        "cns_metastases_c79_3",
    ]

    for nosology in core:
        synthetic_file = root / "data" / "synthetic_cases" / "packs" / nosology / "cases_v1.json"
        synthetic_rows = _read_json(synthetic_file)
        assert len(synthetic_rows) == 96
        assert all("scenario_id" in item for item in synthetic_rows)
        assert all("scenario_tags" in item for item in synthetic_rows)
        assert all("source_lineage" in item for item in synthetic_rows)
        assert all("golden_pair_id" in item for item in synthetic_rows)

        golden_file = root / "data" / "golden_answers" / nosology / "golden_pairs_v1_2.jsonl"
        golden_rows = _read_jsonl(golden_file)
        assert len(golden_rows) == 24
        assert all(str(item.get("approval_status")) in {"draft", "clinician_reviewed", "approved"} for item in golden_rows)
        assert all("reviewer_id" in item for item in golden_rows)
        assert all("reviewed_at" in item for item in golden_rows)
        assert all("review_notes" in item for item in golden_rows)
        assert all(item.get("doctor_report", {}).get("schema_version") == "1.2" for item in golden_rows)
        assert all(item.get("patient_explain", {}).get("schema_version") == "1.2" for item in golden_rows)


def test_wave1_holdout_sizes_match_current_real_distribution() -> None:
    root = Path(__file__).resolve().parents[2]
    expected_holdout = {
        "breast": 1,
        "colorectal": 1,
        "prostate": 0,
        "lung": 0,
        "bladder": 0,
        "gastric": 0,
        "rcc": 0,
        "brain_primary_c71": 0,
        "cns_metastases_c79_3": 0,
    }

    for nosology, holdout_size in expected_holdout.items():
        holdout_file = root / "data" / "control_groups" / nosology / "holdout_v1.json"
        payload = _read_json(holdout_file)
        assert int(payload.get("holdout_size", -1)) == holdout_size


def test_wave2_shadow_assets_have_lite_cardinality() -> None:
    root = Path(__file__).resolve().parents[2]
    shadow = [
        "melanoma",
        "head_neck",
        "thyroid",
        "pancreas",
        "liver",
        "esophagus",
        "ovary",
        "hematology_cup_small_bowel",
    ]

    for nosology in shadow:
        synthetic_file = root / "data" / "synthetic_cases" / "packs_shadow" / nosology / "cases_shadow_v1.json"
        synthetic_rows = _read_json(synthetic_file)
        assert len(synthetic_rows) == 24

        golden_file = root / "data" / "golden_answers_shadow" / nosology / "golden_pairs_v1_2_lite.jsonl"
        golden_rows = _read_jsonl(golden_file)
        assert len(golden_rows) == 6
        assert all(str(item.get("approval_status")) == "shadow_lite" for item in golden_rows)


def test_wave_coverage_report_exists_with_wave_flags() -> None:
    root = Path(__file__).resolve().parents[2]
    report_file = root / "reports" / "metrics" / "nosology_coverage_2026-02-23.json"
    payload = _read_json(report_file)
    assert payload.get("wave1", {}).get("status") == "core_full"
    assert payload.get("wave2", {}).get("status") == "shadow_pack"
    assert payload.get("source_priority") == ["minzdrav", "russco", "supplementary"]
