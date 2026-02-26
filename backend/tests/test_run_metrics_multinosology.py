from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_run_metrics_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "run_metrics.py"
    spec = importlib.util.spec_from_file_location("onco_run_metrics_multi_module", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/run_metrics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_cases_dataset_supports_glob_and_nosology_filter(tmp_path: Path) -> None:
    module = _load_run_metrics_module()

    pack_a = [
        {
            "id": "a1",
            "nosology": "lung",
            "request": {"schema_version": "0.1", "case": {"cancer_type": "nsclc_egfr"}, "treatment_plan": {"plan_text": "x"}},
            "expected": {"min_issues": 0},
        }
    ]
    pack_b = [
        {
            "id": "b1",
            "nosology": "breast",
            "request": {"schema_version": "0.1", "case": {"cancer_type": "breast_hr+/her2-"}, "treatment_plan": {"plan_text": "x"}},
            "expected": {"min_issues": 0},
        }
    ]
    file_a = tmp_path / "pack_a.json"
    file_b = tmp_path / "pack_b.json"
    file_a.write_text(json.dumps(pack_a, ensure_ascii=False))
    file_b.write_text(json.dumps(pack_b, ensure_ascii=False))

    all_cases = module.load_cases_dataset(
        cases_path=str(file_a),
        cases_glob=str(tmp_path / "pack_*.json"),
        nosology_filter_csv="",
    )
    assert len(all_cases) == 2

    filtered = module.load_cases_dataset(
        cases_path="",
        cases_glob=str(tmp_path / "pack_*.json"),
        nosology_filter_csv="breast",
    )
    assert len(filtered) == 1
    assert filtered[0]["nosology"] == "breast"


def test_compute_per_nosology_metrics_aggregates_case_results() -> None:
    module = _load_run_metrics_module()
    case_rows = [
        {
            "case_id": "c1",
            "nosology": "lung",
            "status": 200,
            "latency_ms": 100.0,
            "quality": {"decision_total": 2, "decision_with_citation": 2, "sanity_fail": False, "key_fact_retention": 1.0},
            "passed": True,
            "insufficient_data": False,
            "issues_total": 2,
            "issues_with_evidence": 2,
            "clinical_minimum_completeness": 1.0,
            "biomarker_profile_concordance": 1.0,
            "placeholder_citations": 0,
            "citations_total": 2,
            "unsafe_phrase_found": False,
            "nosology_semantic_conflict": False,
        },
        {
            "case_id": "c2",
            "nosology": "lung",
            "status": 200,
            "latency_ms": 120.0,
            "quality": {"decision_total": 1, "decision_with_citation": 0, "sanity_fail": True, "key_fact_retention": 0.8},
            "passed": False,
            "insufficient_data": True,
            "issues_total": 1,
            "issues_with_evidence": 1,
            "clinical_minimum_completeness": 0.5,
            "biomarker_profile_concordance": 0.75,
            "placeholder_citations": 1,
            "citations_total": 2,
            "unsafe_phrase_found": True,
            "nosology_semantic_conflict": False,
        },
        {
            "case_id": "c3",
            "nosology": "breast",
            "status": 200,
            "latency_ms": 90.0,
            "quality": {"decision_total": 1, "decision_with_citation": 1, "sanity_fail": False, "key_fact_retention": 1.0},
            "passed": True,
            "insufficient_data": False,
            "issues_total": 1,
            "issues_with_evidence": 1,
            "clinical_minimum_completeness": 1.0,
            "biomarker_profile_concordance": 1.0,
            "placeholder_citations": 0,
            "citations_total": 1,
            "unsafe_phrase_found": False,
            "nosology_semantic_conflict": False,
        },
    ]

    per = module.compute_per_nosology_metrics(case_rows)
    assert set(per.keys()) == {"lung", "breast"}
    assert per["lung"]["total_cases"] == 2
    assert per["lung"]["recall_like"] == 0.5
    assert per["lung"]["citation_coverage"] == 0.6667
    assert per["lung"]["clinical_minimum_completeness"] == 0.75
    assert per["lung"]["placeholder_citation_rate"] == 0.25
    assert per["lung"]["unsafe_phrase_rate"] == 0.5
    assert per["breast"]["total_cases"] == 1
    assert per["breast"]["recall_like"] == 1.0


def test_compute_clinical_quality_signals_detects_placeholders_unsafe_and_conflict() -> None:
    module = _load_run_metrics_module()
    signals = module.compute_clinical_quality_signals(
        nosology="brain_primary_c71",
        response_body={
            "doctor_report": {
                "disease_context": {
                    "icd10": "C79.3",
                    "biomarkers": [{"name": "IDH1/2", "value": "wild_type"}],
                },
                "case_facts": {"minimum_dataset": {"completeness": 0.4}},
                "consilium_md": "План согласован.",
                "citations": [
                    {
                        "source_id": "minzdrav",
                        "file_uri": "files/minzdrav/guideline_1.pdf",
                        "quote": "Рекомендация подтверждена клиническими источниками.",
                    }
                ],
            },
            "patient_explain": {"summary_plain": "План согласован"},
        },
        biomarker_matrix={
            "defaults": {"required": [], "forbidden_global_defaults": []},
            "nosologies": {"brain_primary_c71": {"required": ["IDH1/2"], "forbidden_global_defaults": []}},
        },
    )
    assert signals["clinical_minimum_completeness"] == 0.4
    assert signals["biomarker_profile_concordance"] == 1.0
    assert signals["placeholder_citations"] == 1
    assert signals["citations_total"] == 1
    assert signals["unsafe_phrase_found"] is True
    assert signals["nosology_semantic_conflict"] is True


def test_compute_golden_alignment_reads_expectations() -> None:
    module = _load_run_metrics_module()

    response_body = {
        "doctor_report": {
            "plan": [
                {
                    "section": "treatment",
                    "title": "Тактика",
                    "steps": [{"text": "Провести оценка ответа"}],
                }
            ],
            "issues": [{"kind": "missing_data"}],
            "citations": [{"source_id": "minzdrav"}],
        },
        "insufficient_data": {"status": True},
    }

    golden_map = {
        "golden-lung-001": {
            "alignment_expectations": {
                "required_issue_kinds": ["missing_data"],
                "required_plan_intents": ["оценка ответа"],
                "minimal_citation_sources": ["minzdrav"],
                "expected_insufficient_data": True,
            }
        }
    }

    result = module.evaluate_golden_alignment(
        case_id="case-1",
        golden_pair_id="golden-lung-001",
        response_body=response_body,
        golden_pairs_by_id=golden_map,
    )

    assert result["matched"] is True
    assert result["checks_total"] == 4
    assert result["checks_passed"] == 4


def test_precision_recall_f1_uses_issue_kind_overlap() -> None:
    module = _load_run_metrics_module()
    rows = [
        {
            "expected_issue_kinds": ["missing_data", "deviation"],
            "predicted_issue_kinds": ["missing_data", "contraindication"],
        },
        {
            "expected_issue_kinds": ["inconsistency"],
            "predicted_issue_kinds": ["inconsistency"],
        },
    ]
    result = module.compute_precision_recall_f1(rows)
    assert result["tp"] == 2
    assert result["fp"] == 1
    assert result["fn"] == 1
    assert result["precision"] == 0.6667
    assert result["f1"] == 0.6667


def test_clinical_review_coverage_counts_reviewed_pairs() -> None:
    module = _load_run_metrics_module()
    payload = {
        "g1": {"nosology": "lung", "approval_status": "draft"},
        "g2": {
            "nosology": "lung",
            "approval_status": "clinician_reviewed",
            "reviewer_id": "clinician-1",
            "reviewed_at": "2026-02-23T10:00:00Z",
        },
        "g3": {
            "nosology": "breast",
            "approval_status": "approved",
            "reviewer_id": "clinician-2",
            "reviewed_at": "2026-02-23T11:00:00Z",
        },
        "g4": {"nosology": "breast", "approval_status": "approved"},
    }
    result = module.compute_clinical_review_coverage(payload)
    assert result["enabled"] is True
    assert result["total_pairs"] == 4
    assert result["reviewed_pairs"] == 2
    assert result["approved_pairs"] == 1
    assert result["invalid_review_rows"] == 1
    assert result["coverage_ratio"] == 0.5


def test_clinical_decision_quality_counts_approved_and_rewrite_required() -> None:
    module = _load_run_metrics_module()
    payload = {
        "g1": {"nosology": "lung", "clinical_review": {"decision": "APPROVED"}},
        "g2": {"nosology": "lung", "clinical_review": {"decision": "REWRITE_REQUIRED"}},
        "g3": {"nosology": "breast", "decision": "APPROVED"},
        "g4": {"nosology": "breast", "approval_status": "clinician_reviewed"},
    }
    result = module.compute_clinical_decision_quality(payload)
    assert result["enabled"] is True
    assert result["total_pairs"] == 4
    assert result["decided_pairs"] == 3
    assert result["approved_pairs"] == 2
    assert result["rewrite_required_pairs"] == 1
    assert result["approved_ratio"] == 0.6667
    assert result["rewrite_required_rate"] == 0.3333
    assert result["per_nosology"]["lung"]["approved_pairs"] == 1
    assert result["per_nosology"]["lung"]["rewrite_required_pairs"] == 1
