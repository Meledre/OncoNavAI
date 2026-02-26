from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest


def _base_case_request(request_id: str = "case-1") -> dict:
    return {
        "schema_version": "0.2",
        "request_id": request_id,
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "patient": {"sex": "female", "age": 62},
            "diagnosis": {"stage": "IV"},
            "biomarkers": [{"name": "EGFR", "value": "L858R"}],
            "comorbidities": [],
            "contraindications": [],
            "notes": "synthetic",
        },
        "treatment_plan": {
            "plan_text": "Диагностический контроль и системная терапия: осимертиниб 80 мг ежедневно",
            "plan_structured": [
                {"step_type": "diagnostic", "name": "КТ"},
                {"step_type": "systemic_therapy", "name": "Осимертиниб"},
            ],
        },
        "return_patient_explain": True,
    }


def _custom_template_case_json(case_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "import_profile": "CUSTOM_TEMPLATE",
        "patient": {"sex": "male", "birth_year": 1973},
        "diagnoses": [
            {
                "diagnosis_id": str(uuid.uuid4()),
                "disease_id": str(uuid.uuid4()),
                "icd10": "C16",
                "histology": "adenocarcinoma",
                "stage": {"system": "TNM8", "stage_group": "IV"},
                "timeline": [],
                "last_plan": {
                    "date": "2026-02-10",
                    "precision": "day",
                    "regimen": "XELOX",
                    "line": 1,
                    "cycle": 3,
                },
            }
        ],
        "attachments": [],
        "notes": "Synthetic custom template import payload.",
    }


def _load_run_metrics_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "run_metrics.py"
    spec = importlib.util.spec_from_file_location("onco_run_metrics_test_module", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/run_metrics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_v1_2_quality_metrics_treats_legacy_schema_as_not_applicable() -> None:
    module = _load_run_metrics_module()
    metrics = module.compute_v1_2_quality_metrics(
        {
            "doctor_report": {
                "schema_version": "0.2",
                "issues": [
                    {
                        "issue_id": "ISS-1",
                        "evidence": [{"chunk_id": "chunk-1"}],
                    }
                ],
            }
        }
    )

    assert metrics["key_fact_retention"] == 1.0
    assert metrics["decision_total"] == 1
    assert metrics["decision_with_citation"] == 1


def test_run_metrics_supports_inproc_mode(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ONCOAI_REASONING_MODE": "compat"},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(out_path.read_text())
    assert report["schema_version"] == "0.2"
    assert report["total_cases"] == 1
    assert "latency_ms" in report
    assert "sanity_fail_rate" in report
    assert "citation_coverage" in report
    assert "key_fact_retention" in report
    assert "clinical_minimum_completeness" in report
    assert "biomarker_profile_concordance" in report
    assert "placeholder_citation_rate" in report
    assert "unsafe_phrase_rate" in report
    assert "nosology_semantic_conflict_rate" in report
    assert "v1_2_quality" in report


def test_run_metrics_fails_when_gate_threshold_is_not_met(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
            "--min-recall-like",
            "1.1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ONCOAI_REASONING_MODE": "compat"},
    )

    assert result.returncode != 0
    assert out_path.exists()


def test_run_metrics_infers_issue_kinds_from_expected_when_response_has_no_issues(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "metrics.json"
    cases_payload = [
        {
            "id": "case-1",
            "request": _base_case_request(),
            "expected": {"min_issues": 1, "required_issue_kinds": ["other"]},
        }
    ]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ONCOAI_REASONING_MODE": "compat"},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["passed_cases"] == 1
    assert report["recall_like"] == 1.0
    assert isinstance(report.get("precision"), (int, float))
    assert isinstance(report.get("f1"), (int, float))


def test_run_metrics_fails_when_clinical_review_coverage_gate_not_met(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    golden_path = tmp_path / "golden.jsonl"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))
    golden_path.write_text(
        json.dumps(
            {
                "golden_pair_id": "golden-1",
                "nosology": "lung",
                "approval_status": "draft",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--golden-pairs",
            str(golden_path),
            "--min-clinical-review-coverage",
            "0.5",
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "clinical_review_coverage.coverage_ratio" in result.stderr


def test_run_metrics_supports_warmup_discard_for_latency_stats(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "metrics.json"
    case_request = _base_case_request(request_id="case")
    cases_payload = [
        {"id": "case-1", "request": case_request, "expected": {"min_issues": 0}},
        {"id": "case-2", "request": case_request, "expected": {"min_issues": 0}},
        {"id": "case-3", "request": case_request, "expected": {"min_issues": 0}},
    ]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
            "--warmup-cases",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(out_path.read_text())
    assert report["latency_ms"]["samples_total"] == 3
    assert report["latency_ms"]["warmup_discarded"] == 1
    assert report["latency_ms"]["samples_effective"] == 2


def test_run_metrics_supports_import_quality_gates_inproc(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    import_cases_path = tmp_path / "import_cases.json"
    out_path = tmp_path / "metrics.json"

    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    case_id = str(uuid.uuid4())
    import_cases_payload = [
        {
            "id": "import-custom-template-1",
            "request": {
                "schema_version": "1.0",
                "import_profile": "CUSTOM_TEMPLATE",
                "case_json": _custom_template_case_json(case_id),
            },
            "expected": {
                "allowed_statuses": ["SUCCESS", "PARTIAL_SUCCESS"],
                "required_case_fields": [
                    "diagnoses.0.icd10",
                    "diagnoses.0.last_plan.regimen",
                ],
                "analyze_min_issues": 0,
            },
        }
    ]
    import_cases_path.write_text(json.dumps(import_cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--import-cases",
            str(import_cases_path),
            "--required-import-profiles",
            "CUSTOM_TEMPLATE",
            "--min-import-success-ratio",
            "1.0",
            "--min-import-profile-coverage",
            "1.0",
            "--min-import-required-field-coverage",
            "1.0",
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ONCOAI_REASONING_MODE": "compat"},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(out_path.read_text())
    import_quality = report["import_quality"]
    assert import_quality["enabled"] is True
    assert import_quality["total_runs"] == 1
    assert import_quality["passed_runs"] == 1
    assert import_quality["success_ratio"] == 1.0
    assert import_quality["profile_coverage_ratio"] == 1.0
    assert import_quality["required_field_coverage_ratio"] == 1.0


def test_run_metrics_import_profile_coverage_gate_fails_when_profile_missing(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    import_cases_path = tmp_path / "import_cases.json"
    out_path = tmp_path / "metrics.json"

    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    import_cases_payload = [
        {
            "id": "import-free-text-1",
            "request": {
                "schema_version": "1.0",
                "import_profile": "FREE_TEXT",
                "free_text": "Синтетический текст для импорта.",
            },
            "expected": {
                "allowed_statuses": ["SUCCESS", "PARTIAL_SUCCESS"],
                "required_case_fields": ["notes"],
                "analyze_min_issues": 0,
            },
        }
    ]
    import_cases_path.write_text(json.dumps(import_cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--import-cases",
            str(import_cases_path),
            "--required-import-profiles",
            "FREE_TEXT,KIN_PDF",
            "--min-import-profile-coverage",
            "1.0",
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "import_quality.profile_coverage_ratio" in result.stderr


def test_run_metrics_import_data_mode_coverage_gate_passes(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    import_cases_path = tmp_path / "import_cases.json"
    out_path = tmp_path / "metrics.json"

    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    import_cases_payload = [
        {
            "id": "import-free-text-1",
            "request": {
                "schema_version": "1.0",
                "import_profile": "FREE_TEXT",
                "data_mode": "DEID",
                "free_text": "Синтетический текст для импорта.",
            },
            "expected": {
                "allowed_statuses": ["SUCCESS", "PARTIAL_SUCCESS"],
                "required_case_fields": ["notes"],
                "expected_data_mode": "DEID",
                "analyze_min_issues": 0,
            },
        }
    ]
    import_cases_path.write_text(json.dumps(import_cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--import-cases",
            str(import_cases_path),
            "--required-import-profiles",
            "FREE_TEXT",
            "--min-import-data-mode-coverage",
            "1.0",
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_run_metrics_accepts_http_timeout_argument(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
            "--http-timeout-sec",
            "60",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(out_path.read_text())
    assert report["schema_version"] == "0.2"
    assert report["total_cases"] == 1


def test_run_metrics_import_data_mode_coverage_gate_fails_on_mismatch(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    import_cases_path = tmp_path / "import_cases.json"
    out_path = tmp_path / "metrics.json"

    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    import_cases_payload = [
        {
            "id": "import-free-text-1",
            "request": {
                "schema_version": "1.0",
                "import_profile": "FREE_TEXT",
                "data_mode": "DEID",
                "free_text": "Синтетический текст для импорта.",
            },
            "expected": {
                "allowed_statuses": ["SUCCESS", "PARTIAL_SUCCESS"],
                "required_case_fields": ["notes"],
                "expected_data_mode": "FULL",
                "analyze_min_issues": 0,
            },
        }
    ]
    import_cases_path.write_text(json.dumps(import_cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--import-cases",
            str(import_cases_path),
            "--required-import-profiles",
            "FREE_TEXT",
            "--min-import-data-mode-coverage",
            "1.0",
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ONCOAI_REASONING_MODE": "compat"},
    )

    assert result.returncode != 0
    assert "import_quality.data_mode_coverage_ratio" in result.stderr


def test_run_metrics_v1_2_citation_coverage_gate_fails_when_threshold_is_unreachable(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
            "--min-citation-coverage",
            "1.1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "citation_coverage=" in result.stderr


def test_run_metrics_placeholder_citation_gate_fails_with_negative_threshold(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
            "--max-placeholder-citation-rate",
            "-0.1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "placeholder_citation_rate=" in result.stderr


def test_run_metrics_outputs_clinical_decision_quality_metrics(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    golden_path = tmp_path / "golden.jsonl"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False), encoding="utf-8")
    golden_path.write_text(
        json.dumps(
            {
                "golden_pair_id": "golden-1",
                "nosology": "lung",
                "clinical_review": {"decision": "APPROVED"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--golden-pairs",
            str(golden_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(out_path.read_text(encoding="utf-8"))
    decision = report["clinical_decision_quality"]
    assert decision["enabled"] is True
    assert decision["approved_pairs"] == 1
    assert decision["rewrite_required_pairs"] == 0
    assert decision["approved_ratio"] == 1.0


def test_run_metrics_fails_when_rewrite_required_rate_gate_is_not_met(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    golden_path = tmp_path / "golden.jsonl"
    out_path = tmp_path / "metrics.json"
    cases_payload = [{"id": "case-1", "request": _base_case_request(), "expected": {"min_issues": 0}}]
    cases_path.write_text(json.dumps(cases_payload, ensure_ascii=False), encoding="utf-8")
    golden_path.write_text(
        json.dumps(
            {
                "golden_pair_id": "golden-1",
                "nosology": "lung",
                "clinical_review": {"decision": "REWRITE_REQUIRED"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_metrics.py",
            "--mode",
            "inproc",
            "--cases",
            str(cases_path),
            "--golden-pairs",
            str(golden_path),
            "--out",
            str(out_path),
            "--schema-version",
            "0.2",
            "--max-rewrite-required-rate",
            "0.0",
            "--min-approved-pairs-by-nosology",
            "lung:1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "clinical_decision_quality.rewrite_required_rate=" in result.stderr
    assert "clinical_decision_quality.per_nosology[lung].approved_pairs=" in result.stderr


def test_deadline_guard_interrupts_slow_operation() -> None:
    module = _load_run_metrics_module()

    if not hasattr(module.signal, "setitimer"):
        pytest.skip("setitimer is not available in this runtime")

    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        with module._deadline_guard(0.05):
            time.sleep(0.2)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2


def test_persistent_http_client_default_is_disabled(monkeypatch) -> None:
    monkeypatch.delenv("ONCO_METRICS_PERSISTENT_HTTP_CLIENT", raising=False)
    module = _load_run_metrics_module()
    assert module._default_persistent_http_client_enabled() is False


def test_persistent_http_client_default_can_be_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("ONCO_METRICS_PERSISTENT_HTTP_CLIENT", "true")
    module = _load_run_metrics_module()
    assert module._default_persistent_http_client_enabled() is True


def test_persistent_http_client_retries_connection_reset_until_success(monkeypatch) -> None:
    module = _load_run_metrics_module()

    class _FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b"{}"

    class _FlakyConnection:
        def __init__(self) -> None:
            self.request_calls = 0

        def request(self, *_args, **_kwargs) -> None:
            self.request_calls += 1
            if self.request_calls < 3:
                raise ConnectionResetError(54, "Connection reset by peer")

        def getresponse(self) -> _FakeResponse:
            return _FakeResponse()

    client = module.PersistentAnalyzeHttpClient("http://localhost:8000", "demo-token", timeout_sec=30.0)
    flaky = _FlakyConnection()
    monkeypatch.setattr(client, "_get_connection", lambda: flaky)
    monkeypatch.setattr(client, "close", lambda: None)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    status, body, error = client.call({"schema_version": "0.2"})

    assert status == 200
    assert body == {}
    assert error is None
    assert flaky.request_calls == 3


def test_call_backend_json_retries_transient_network_error(monkeypatch) -> None:
    module = _load_run_metrics_module()
    calls = {"count": 0}

    class _CtxResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self) -> bytes:
            return b'{"status":"ok"}'

    def _fake_urlopen(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ConnectionResetError(54, "Connection reset by peer")
        return _CtxResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    status, body, error = module.call_backend_json(
        base_url="http://localhost:8000",
        path="/case/import",
        method="POST",
        token="demo-token",
        payload={"schema_version": "1.0"},
        timeout_sec=30.0,
    )

    assert status == 200
    assert body == {"status": "ok"}
    assert error is None
    assert calls["count"] == 2
