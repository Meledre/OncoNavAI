from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "prod_release_orchestrator.py"
    module_name = "onco_prod_release_orchestrator_module"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/prod_release_orchestrator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_default_bakeoff_case_ids_are_fixed_and_unique() -> None:
    module = _load_module()
    ids = module.DEFAULT_BAKEOFF_CASE_IDS
    assert len(ids) == 10
    assert len(set(ids)) == 10
    assert ids[0] == "PDF-0049"


def test_percentile_handles_empty_input() -> None:
    module = _load_module()
    assert module._percentile([], 95) == 0.0


def test_latency_stats_ms_from_case_rows() -> None:
    module = _load_module()
    rows = [
        {"runtime": {"duration_sec": 12.0}},
        {"runtime": {"duration_sec": 20.0}},
        {"runtime": {"duration_sec": 40.0}},
    ]
    stats = module._latency_stats_ms(rows)
    assert stats["count"] == 3
    assert stats["p50_ms"] == 20000.0
    assert stats["p95_ms"] >= stats["p90_ms"]


def test_select_model_profile_prefers_first_sla_passing_profile() -> None:
    module = _load_module()
    results = [
        {"model": "gpt-5.2", "cases_failed": 0, "latency": {"p95_ms": 61000.0}},
        {"model": "gpt-4.1", "cases_failed": 0, "latency": {"p95_ms": 55000.0}},
        {"model": "gpt-4.1-mini", "cases_failed": 0, "latency": {"p95_ms": 52000.0}},
    ]
    selected = module._select_model_profile(results, sla_ms=60000.0)
    assert selected["model"] == "gpt-4.1"
    assert selected["decision"] == "sla_pass"


def test_select_model_profile_falls_back_when_all_profiles_fail_sla() -> None:
    module = _load_module()
    results = [
        {"model": "gpt-5.2", "cases_failed": 0, "latency": {"p95_ms": 91000.0}},
        {"model": "gpt-4.1", "cases_failed": 0, "latency": {"p95_ms": 81000.0}},
        {"model": "gpt-4.1-mini", "cases_failed": 1, "latency": {"p95_ms": 70000.0}},
    ]
    selected = module._select_model_profile(results, sla_ms=60000.0)
    assert selected["model"] == "gpt-4.1"
    assert selected["decision"] == "no_sla_pass_best_quality"


def test_parse_case_ids_supports_inline_and_file(tmp_path: Path) -> None:
    module = _load_module()
    from_inline = module._parse_case_ids("PDF-0001, PDF-0002", default_ids=["X"])
    assert from_inline == ["PDF-0001", "PDF-0002"]

    case_file = tmp_path / "ids.txt"
    case_file.write_text("PDF-0003\nPDF-0004\n", encoding="utf-8")
    from_file = module._parse_case_ids(str(case_file), default_ids=["X"])
    assert from_file == ["PDF-0003", "PDF-0004"]


def test_build_demo_waiver_markdown_lists_yellow_items() -> None:
    module = _load_module()
    traceability = {
        "cr": [
            {"id": "CR-01", "status": "GREEN", "owner": "platform"},
            {"id": "CR-02", "status": "YELLOW", "owner": "backend", "eta": "2026-03-05"},
        ],
        "df": [
            {"id": "DF-2", "status": "YELLOW", "owner": "frontend", "eta": "2026-03-07"},
        ],
    }
    markdown = module._build_demo_waiver_markdown(
        traceability=traceability,
        generated_at="2026-02-25T10:00:00Z",
        remediation_deadline="2026-03-10",
        mitigation="strict_full + manual clinical review",
    )
    assert "CR-02" in markdown
    assert "DF-2" in markdown
    assert "2026-03-10" in markdown


def test_model_decision_markdown_mentions_sla_and_selected_model() -> None:
    module = _load_module()
    report = {
        "sla_ms": 60000.0,
        "selected": {"model": "gpt-4.1", "decision": "sla_pass", "latency": {"p95_ms": 55200.0}},
        "profiles": [
            {"model": "gpt-5.2", "cases_failed": 0, "latency": {"p95_ms": 61000.0}},
            {"model": "gpt-4.1", "cases_failed": 0, "latency": {"p95_ms": 55200.0}},
        ],
    }
    markdown = module._build_model_decision_markdown(report)
    assert "SLA" in markdown
    assert "gpt-4.1" in markdown
    assert "55200.0" in markdown


def test_load_json_file_requires_object(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    payload = module._load_json_file(path)
    assert payload["ok"] is True


def test_go_live_report_does_not_crash_with_empty_optional_paths(tmp_path: Path) -> None:
    module = _load_module()
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps({"ok": True}), encoding="utf-8")
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"latency_p95_ms": 1234, "passed_cases": 3}), encoding="utf-8")
    out_dir = tmp_path / "out"
    from types import SimpleNamespace

    args = SimpleNamespace(
        readiness_report=str(readiness),
        latest_metrics=str(latest),
        model_bakeoff_report="",
        connectivity_report="",
        waiver_path="",
        out_dir=str(out_dir),
    )
    rc = module.cmd_go_live_report(args)
    assert rc == 1


def test_go_live_report_accepts_existing_waiver_for_non_sla_decision(tmp_path: Path) -> None:
    module = _load_module()
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps({"ok": True}), encoding="utf-8")
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"latency_p95_ms": 1234, "passed_cases": 3}), encoding="utf-8")
    bakeoff = tmp_path / "bakeoff.json"
    bakeoff.write_text(
        json.dumps({"selected": {"model": "gpt-4o-mini", "decision": "no_quality_pass_fastest_available"}}),
        encoding="utf-8",
    )
    connectivity = tmp_path / "connectivity.json"
    connectivity.write_text(json.dumps({"selected_route": "native"}), encoding="utf-8")
    waiver = tmp_path / "waiver.md"
    waiver.write_text("# demo waiver", encoding="utf-8")

    out_dir = tmp_path / "out"
    from types import SimpleNamespace

    args = SimpleNamespace(
        readiness_report=str(readiness),
        latest_metrics=str(latest),
        model_bakeoff_report=str(bakeoff),
        connectivity_report=str(connectivity),
        waiver_path=str(waiver),
        out_dir=str(out_dir),
    )
    rc = module.cmd_go_live_report(args)
    assert rc == 0
