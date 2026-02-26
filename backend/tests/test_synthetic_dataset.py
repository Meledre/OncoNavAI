from __future__ import annotations

import json
from pathlib import Path


def test_synthetic_cases_dataset_size_and_schema() -> None:
    dataset_path = Path(__file__).resolve().parents[2] / "data" / "synthetic_cases" / "cases_v0.json"
    payload = json.loads(dataset_path.read_text())

    assert isinstance(payload, list)
    assert 30 <= len(payload) <= 50

    required_top_level = {"id", "request", "expected"}
    required_request = {"schema_version", "request_id", "case", "treatment_plan"}
    required_case = {"cancer_type", "language", "notes"}
    required_expected = {"min_issues"}

    for item in payload:
        assert required_top_level.issubset(item.keys())
        assert required_request.issubset(item["request"].keys())
        assert required_case.issubset(item["request"]["case"].keys())
        assert required_expected.issubset(item["expected"].keys())


def test_synthetic_cases_cover_release_nosology_scope() -> None:
    dataset_path = Path(__file__).resolve().parents[2] / "data" / "synthetic_cases" / "cases_v0.json"
    payload = json.loads(dataset_path.read_text())

    cancer_types = {item["request"]["case"]["cancer_type"] for item in payload}
    assert {"nsclc_egfr", "gastric_cancer"}.issubset(cancer_types)
    gastric_cases = [
        item
        for item in payload
        if str(item.get("request", {}).get("case", {}).get("cancer_type", "")) == "gastric_cancer"
    ]
    assert len(gastric_cases) >= 2
