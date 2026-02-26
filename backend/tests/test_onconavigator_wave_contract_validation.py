from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator, FormatChecker


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise AssertionError(f"expected JSON array at {path}")
    return [item for item in payload if isinstance(item, dict)]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _validator(schema: dict[str, Any], store: dict[str, Any] | None = None) -> Draft202012Validator:
    base_uri = str(schema.get("$id") or "urn:onco:local:schema")
    schema_store: dict[str, Any] = {
        base_uri: schema,
        "": schema,
    }
    if store:
        schema_store.update(store)
    resolver = jsonschema.RefResolver(base_uri=base_uri, referrer=schema, store=schema_store)
    return Draft202012Validator(schema, resolver=resolver, format_checker=FormatChecker())


def _assert_valid(validator: Draft202012Validator, payload: dict[str, Any], *, context: str) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if not errors:
        return
    first = errors[0]
    loc = "/".join(str(part) for part in first.absolute_path)
    raise AssertionError(f"{context}: {first.message} (path={loc or '<root>'})")


def test_control_case_manifests_validate_against_schema() -> None:
    root = _repo_root()
    schema = _read_json(
        root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas" / "control_case_manifest.schema.json"
    )
    validator = _validator(schema)

    manifest_files = sorted((root / "data" / "control_groups").glob("*/real_cases_manifest_v1.jsonl"))
    manifest_files.extend(sorted((root / "data" / "control_groups_shadow").glob("*/real_cases_manifest_v1.jsonl")))
    assert manifest_files

    validated_rows = 0
    for file_path in manifest_files:
        for line_no, row in enumerate(_read_jsonl(file_path), start=1):
            _assert_valid(validator, row, context=f"{file_path}:{line_no}")
            validated_rows += 1
    assert validated_rows > 0


def test_synthetic_cases_include_valid_scenario_contract() -> None:
    root = _repo_root()
    schema = _read_json(
        root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas" / "synthetic_case_scenario.schema.json"
    )
    validator = _validator(schema)

    synthetic_files = sorted((root / "data" / "synthetic_cases" / "packs").glob("*/cases_v1.json"))
    synthetic_files.extend(sorted((root / "data" / "synthetic_cases" / "packs_shadow").glob("*/cases_shadow_v1.json")))
    assert synthetic_files

    validated_rows = 0
    for file_path in synthetic_files:
        for line_no, row in enumerate(_read_json_array(file_path), start=1):
            for required in ("scenario_id", "scenario_tags", "source_lineage"):
                assert required in row, f"{file_path}:{line_no} missing {required}"
            projected = {
                "scenario_id": row.get("scenario_id"),
                "scenario_tags": row.get("scenario_tags"),
                "source_lineage": row.get("source_lineage"),
            }
            _assert_valid(validator, projected, context=f"{file_path}:{line_no}")
            validated_rows += 1
    assert validated_rows > 0


def test_golden_pairs_validate_against_v1_2_contract() -> None:
    root = _repo_root()
    schema_dir = root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas"
    golden_schema = _read_json(schema_dir / "golden_pair_v1_2.schema.json")
    doctor_schema = _read_json(schema_dir / "doctor_report.schema.json")
    patient_schema = _read_json(schema_dir / "patient_explain.schema.json")

    golden_wrapper_schema = copy.deepcopy(golden_schema)
    golden_wrapper_schema["properties"]["doctor_report"] = {"type": "object"}
    golden_wrapper_schema["properties"]["patient_explain"] = {"type": "object"}

    wrapper_validator = _validator(golden_wrapper_schema)
    doctor_validator = _validator(doctor_schema)
    patient_validator = _validator(patient_schema)

    golden_files = sorted((root / "data" / "golden_answers").glob("*/golden_pairs_v1_2.jsonl"))
    golden_files.extend(sorted((root / "data" / "golden_answers_shadow").glob("*/golden_pairs_v1_2_lite.jsonl")))
    assert golden_files

    validated_rows = 0
    for file_path in golden_files:
        for line_no, row in enumerate(_read_jsonl(file_path), start=1):
            _assert_valid(wrapper_validator, row, context=f"{file_path}:{line_no}")
            doctor_report = row.get("doctor_report")
            patient_explain = row.get("patient_explain")
            assert isinstance(doctor_report, dict), f"{file_path}:{line_no} doctor_report must be object"
            assert isinstance(patient_explain, dict), f"{file_path}:{line_no} patient_explain must be object"
            _assert_valid(doctor_validator, doctor_report, context=f"{file_path}:{line_no}:doctor_report")
            _assert_valid(patient_validator, patient_explain, context=f"{file_path}:{line_no}:patient_explain")
            validated_rows += 1
    assert validated_rows > 0


def test_golden_pair_reviewed_status_requires_reviewer_metadata() -> None:
    root = _repo_root()
    schema_dir = root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas"
    golden_schema = _read_json(schema_dir / "golden_pair_v1_2.schema.json")
    golden_wrapper_schema = copy.deepcopy(golden_schema)
    golden_wrapper_schema["properties"]["doctor_report"] = {"type": "object"}
    golden_wrapper_schema["properties"]["patient_explain"] = {"type": "object"}
    validator = _validator(golden_wrapper_schema)

    sample_file = next((root / "data" / "golden_answers").glob("*/golden_pairs_v1_2.jsonl"))
    sample_row = _read_jsonl(sample_file)[0]
    invalid_row = copy.deepcopy(sample_row)
    invalid_row["approval_status"] = "approved"
    invalid_row["reviewer_id"] = None
    invalid_row["reviewed_at"] = None
    invalid_row["review_notes"] = None

    errors = list(validator.iter_errors(invalid_row))
    assert errors, "approved row without reviewer metadata must fail schema validation"


def test_canonical_real_cases_validate_against_case_schema() -> None:
    root = _repo_root()
    case_schema = _read_json(root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas" / "case.schema.json")
    validator = _validator(case_schema)

    canonical_files = sorted((root / "data" / "canonical_real_cases").glob("**/canonical_cases_v1*.jsonl"))
    assert canonical_files

    validated_rows = 0
    for file_path in canonical_files:
        for line_no, row in enumerate(_read_jsonl(file_path), start=1):
            _assert_valid(validator, row, context=f"{file_path}:{line_no}")
            validated_rows += 1
    assert validated_rows > 0
