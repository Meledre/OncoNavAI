from __future__ import annotations

from pathlib import Path


def test_frontend_validator_uses_native_v1_2_parsing_with_flagged_legacy_compat() -> None:
    frontend_root = Path(__file__).resolve().parents[2] / "frontend"
    validate_text = (frontend_root / "lib" / "contracts" / "validate.ts").read_text()
    types_text = (frontend_root / "lib" / "contracts" / "types.ts").read_text()

    assert "normalizeAnalyzeResponse" in validate_text
    assert "parseAnalyzeResponseV1_2" in validate_text
    assert "normalizeLegacyDoctorReportV1_0" in validate_text
    assert "NEXT_PUBLIC_ONCOAI_DOCTOR_REPORT_1_0_COMPAT_ENABLED" in validate_text
    assert "packToLegacy" not in validate_text
    assert "consilium_md" in validate_text
    assert "case_facts" in validate_text
    assert "sanity_checks" in validate_text
    assert "parseDoctorDrugSafety" in validate_text
    assert "parsePatientDrugSafety" in validate_text
    assert "normalizePatientContext" in validate_text
    assert "citation_ids" in validate_text
    assert "parseCompatibility" in validate_text
    assert "payload.compatibility ?? payload._compatibility" in validate_text
    assert "verification_summary" in validate_text

    assert "DoctorReportV1_2" in types_text
    assert "PatientExplainV1_2" in types_text
    assert "PlanSectionV1_2" in types_text
    assert "IssueV1_2" in types_text
    assert "DoctorDrugSafetyV1_2" in types_text
    assert "PatientDrugSafetyV1_2" in types_text
    assert "PatientContext" in types_text
    assert "AnalyzeCompatibility" in types_text
    assert "VerificationSummaryV1_2" in types_text
