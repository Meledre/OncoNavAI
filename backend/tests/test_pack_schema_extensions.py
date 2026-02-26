from __future__ import annotations

import json
from pathlib import Path


def test_analyze_request_schema_supports_historical_reference_date_alias() -> None:
    root = Path(__file__).resolve().parents[2]
    schema_path = root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas" / "analyze_request.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    request_schema = schema["$defs"]["AnalyzeRequest_v0_2"]
    properties = request_schema["properties"]
    assert "historical_reference_date" in properties
    assert properties["historical_reference_date"]["type"] == "string"
    assert properties["historical_reference_date"]["format"] == "date"
    assert "historical_reference_date" not in request_schema["required"]


def test_doctor_report_schema_supports_verification_summary() -> None:
    root = Path(__file__).resolve().parents[2]
    schema_path = root / "docs" / "contracts" / "onco_json_pack_v1" / "schemas" / "doctor_report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert "verification_summary" in properties
    assert "verification_summary" not in schema["required"]
    summary_def = schema["$defs"]["VerificationSummary"]
    assert summary_def["type"] == "object"
    categories = summary_def["properties"]["category"]["enum"]
    assert categories == ["OK", "NOT_COMPLIANT", "NEEDS_DATA", "RISK"]
