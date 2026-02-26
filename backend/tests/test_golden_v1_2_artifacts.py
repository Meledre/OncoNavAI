from __future__ import annotations

import json
from pathlib import Path


def test_v1_2_golden_outputs_are_present_and_valid_json() -> None:
    root = Path(__file__).resolve().parents[2] / "backend" / "tests" / "golden"
    files = [
        root / "doctor_report_n5_v1_2.json",
        root / "doctor_report_case_a_v1_2.json",
        root / "doctor_report_case_b_v1_2.json",
    ]
    for file in files:
        assert file.exists(), f"missing golden file: {file}"
        payload = json.loads(file.read_text())
        assert payload.get("schema_version") == "1.2"
