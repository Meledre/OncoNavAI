from __future__ import annotations

import csv
import json
import runpy
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_rewrite_script_parse_bool_ru_handles_negative_risk_phrase() -> None:
    module = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "rewrite_golden_from_feedback.py"))
    parse_bool = module["_parse_bool_ru"]
    assert parse_bool("Да") is True
    assert parse_bool("нет риска") is False


def test_rewrite_golden_from_feedback_script_rewrites_and_splits_brain(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    golden_root = tmp_path / "golden"
    control_root = tmp_path / "control"
    canonical_root = tmp_path / "canonical"
    profiles_root = tmp_path / "profiles"
    reports_root = tmp_path / "reports"

    _write_json(
        profiles_root / "nosology_minimum_dataset_v1.json",
        {
            "defaults": {
                "min_case_fields": ["diagnoses.0.icd10", "patient.ecog"],
                "required_biomarkers": [],
                "required_labs": [],
                "safe_missing_data_plan_intents": ["дозапрос данных", "уточнение", "безопасность"],
            },
            "nosologies": {
                "bladder": {
                    "min_case_fields": ["diagnoses.0.icd10", "patient.ecog"],
                    "required_biomarkers": ["fgfr2_3", "pd_l1"],
                    "required_labs": ["creatinine"],
                    "safe_missing_data_plan_intents": ["дозапрос данных", "уточнение", "безопасность"],
                },
                "brain_primary_c71": {
                    "min_case_fields": ["diagnoses.0.icd10", "patient.ecog"],
                    "required_biomarkers": ["idh1_2"],
                    "required_labs": [],
                    "safe_missing_data_plan_intents": ["дозапрос данных", "уточнение", "безопасность"],
                },
                "cns_metastases_c79_3": {
                    "min_case_fields": ["diagnoses.0.icd10", "patient.ecog"],
                    "required_biomarkers": ["primary_tumor_type"],
                    "required_labs": [],
                    "safe_missing_data_plan_intents": ["дозапрос данных", "уточнение", "безопасность"],
                },
            },
        },
    )
    _write_json(
        profiles_root / "nosology_biomarker_matrix_v1.json",
        {
            "defaults": {"required": [], "optional": [], "forbidden_global_defaults": []},
            "nosologies": {
                "bladder": {"required": ["FGFR2/3", "PD-L1"], "optional": [], "forbidden_global_defaults": []},
                "brain_primary_c71": {"required": ["IDH1/2"], "optional": [], "forbidden_global_defaults": []},
                "cns_metastases_c79_3": {"required": ["Primary tumor type"], "optional": [], "forbidden_global_defaults": []},
            },
        },
    )

    base_row = {
        "schema_version": "1.0",
        "golden_pair_id": "golden-bladder-001",
        "nosology": "bladder",
        "disease_id": "d80c5e16-28df-5f1d-b88b-f76795db4c59",
        "derived_from": {"mode": "synthetic_derived", "control_case_id": None},
        "approval_status": "draft",
        "alignment_expectations": {
            "required_issue_kinds": ["other"],
            "required_plan_intents": ["оценка ответа"],
            "minimal_citation_sources": ["minzdrav"],
            "expected_insufficient_data": False,
        },
        "updated_at": "2026-02-23T00:00:00Z",
    }
    _write_jsonl(golden_root / "bladder" / "golden_pairs_v1_2.jsonl", [base_row])
    brain_row = dict(base_row)
    brain_row["golden_pair_id"] = "golden-brain-001"
    brain_row["nosology"] = "brain"
    brain_row["disease_id"] = "f7f1cf42-fc0f-5d9f-8fa6-c0464ce9f8b2"
    _write_jsonl(golden_root / "brain" / "golden_pairs_v1_2.jsonl", [brain_row])

    feedback_path = tmp_path / "feedback.csv"
    with feedback_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "review_item_id",
                "golden_pair_id",
                "nosology",
                "clinical_validity",
                "doctor_report_completeness",
                "patient_text_clarity",
                "citation_relevance",
                "safety_risk_found",
                "required_changes",
                "proposed_fix_text",
                "final_decision",
                "reviewer_id",
                "reviewed_at",
                "review_notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "review_item_id": "R001",
                "golden_pair_id": "golden-bladder-001",
                "nosology": "bladder",
                "clinical_validity": "4/5",
                "doctor_report_completeness": "4/5",
                "patient_text_clarity": "4/5",
                "citation_relevance": "4/5",
                "safety_risk_found": "Да",
                "required_changes": "Уточнить клинические факты; убрать ложную уверенность",
                "proposed_fix_text": "",
                "final_decision": "REWRITE_REQUIRED",
                "reviewer_id": "clinician-qa-1",
                "reviewed_at": "2026-02-23T10:00:00Z",
                "review_notes": "Проведено очное ревью, требуется доработка текста и клинической конкретики.",
            }
        )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/rewrite_golden_from_feedback.py",
            "--feedback-csv",
            str(feedback_path),
            "--golden-root",
            str(golden_root),
            "--control-root",
            str(control_root),
            "--canonical-root",
            str(canonical_root),
            "--profiles-root",
            str(profiles_root),
            "--reports-root",
            str(reports_root),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    assert (golden_root / "brain").exists() is False
    assert (golden_root / "brain_primary_c71" / "golden_pairs_v1_2.jsonl").exists()
    assert (golden_root / "cns_metastases_c79_3" / "golden_pairs_v1_2.jsonl").exists()

    bladder_rows = [
        json.loads(line)
        for line in (golden_root / "bladder" / "golden_pairs_v1_2.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert bladder_rows
    first = bladder_rows[0]
    consilium = str(first["doctor_report"]["consilium_md"]).lower()
    assert "план согласован" not in consilium
    first_citation_uri = str(first["doctor_report"]["citations"][0]["file_uri"]).lower()
    assert first_citation_uri.startswith("http")
    assert "guideline_" not in first_citation_uri
    assert first["approval_status"] == "clinician_reviewed"
    assert first["reviewer_id"] == "clinician-qa-1"
    assert first["reviewed_at"] == "2026-02-23T10:00:00Z"
    assert "очное ревью" in str(first["review_notes"]).lower()

    generated = json.loads(result.stdout.strip().splitlines()[-1])
    assert Path(generated["feedback_apply_report"]).exists()
    assert Path(generated["clinical_review_zip"]).exists()
    assert Path(generated["reference_answers_zip"]).exists()
