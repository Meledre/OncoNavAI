from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from zipfile import ZipFile

import pytest


def _load_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "eval_pdf_pack.py"
    module_name = "onco_eval_pdf_pack_module"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/eval_pdf_pack.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _build_zip(tmp_path: Path, *, case_ids: list[str], missing_members: set[str] | None = None) -> Path:
    missing = missing_members or set()
    zip_path = tmp_path / "pack.zip"
    root = "synthetic_pdf_cases_200_v8_smooth"
    manifest_rows: list[dict[str, Any]] = []

    with ZipFile(zip_path, "w") as zf:
        for idx, case_id in enumerate(case_ids, start=1):
            pdf_rel = f"pdf/{case_id}.pdf"
            doctor_rel = f"expected/{case_id}.doctor.json"
            patient_rel = f"expected/{case_id}.patient.json"
            manifest_rows.append(
                {
                    "case_id": case_id,
                    "pdf_file": pdf_rel,
                    "doctor_expected": doctor_rel,
                    "patient_expected": patient_rel,
                    "request_id": f"req-{idx}",
                    "schema_version": "1.2",
                    "query_type": "NEXT_STEPS",
                    "nosology_key": "breast",
                    "stage_group": "IV",
                    "setting": "metastatic",
                    "line": 1,
                    "source_set": "v8_smooth",
                }
            )

            if pdf_rel not in missing:
                zf.writestr(f"{root}/{pdf_rel}", b"%PDF-1.4\n%%EOF\n")
            if doctor_rel not in missing:
                zf.writestr(
                    f"{root}/{doctor_rel}",
                    json.dumps(
                        {
                            "schema_version": "1.2",
                            "report_id": f"report-{case_id}",
                            "issues": [{"issue_id": "i1", "citation_ids": ["c1"]}],
                            "citations": [{"citation_id": "c1", "source_id": "minzdrav"}],
                        },
                        ensure_ascii=False,
                    ),
                )
            if patient_rel not in missing:
                zf.writestr(
                    f"{root}/{patient_rel}",
                    json.dumps(
                        {
                            "schema_version": "1.2",
                            "summary_plain": "ok",
                            "key_points": ["k1"],
                        },
                        ensure_ascii=False,
                    ),
                )

        manifest_blob = "\n".join(json.dumps(row, ensure_ascii=False) for row in manifest_rows) + "\n"
        zf.writestr(f"{root}/manifest.jsonl", manifest_blob)

    return zip_path


class _FakeClient:
    def __init__(self, *, leak_doctor_report: bool = False, zero_citations: bool = False) -> None:
        self.leak_doctor_report = leak_doctor_report
        self.zero_citations = zero_citations

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        role: str,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        _ = method
        _ = role
        _ = payload
        _ = extra_headers
        if path == "/api/case/import-file":
            return 200, {"case_id": "case-1", "import_run_id": "run-1"}
        if path == "/api/analyze":
            citations = [] if self.zero_citations else [{"citation_id": "c1", "source_id": "minzdrav"}]
            citation_ids = [] if self.zero_citations else ["c1"]
            return (
                200,
                {
                    "doctor_report": {
                        "report_id": "r-1",
                        "issues": [{"issue_id": "i1", "citation_ids": citation_ids}],
                        "citations": citations,
                    },
                    "patient_explain": {"summary": "ok", "sources_used": ["minzdrav"]},
                },
            )
        if path == "/api/patient/analyze":
            payload_body: dict[str, Any] = {"patient_explain": {"summary": "patient-ok"}}
            if self.leak_doctor_report:
                payload_body["doctor_report"] = {"report_id": "forbidden"}
            return 200, payload_body
        raise AssertionError(f"unexpected path: {path}")


def test_pack_structure_validation_requires_expected_members(tmp_path: Path) -> None:
    module = _load_module()
    zip_path = _build_zip(
        tmp_path,
        case_ids=["PDF-0001"],
        missing_members={"expected/PDF-0001.patient.json"},
    )

    with ZipFile(zip_path) as zf:
        root = module._resolve_pack_root(zf)
        entries = module._read_manifest(zf, root=root)
        with pytest.raises(RuntimeError, match="missing required members"):
            module._validate_pack_structure(zf, root=root, entries=entries)


def test_select_cases_pilot_mode_uses_fixed_deterministic_order(tmp_path: Path) -> None:
    module = _load_module()
    zip_path = _build_zip(tmp_path, case_ids=module.PILOT_CASE_IDS + ["PDF-9999"])

    with ZipFile(zip_path) as zf:
        root = module._resolve_pack_root(zf)
        entries = module._read_manifest(zf, root=root)

    selected = module._select_cases(entries=entries, sample_mode="pilot", case_list=[])
    assert [item.case_id for item in selected] == module.PILOT_CASE_IDS


def test_process_case_success(tmp_path: Path) -> None:
    module = _load_module()
    zip_path = _build_zip(tmp_path, case_ids=["PDF-0001"])

    with ZipFile(zip_path) as zf:
        root = module._resolve_pack_root(zf)
        entries = module._read_manifest(zf, root=root)
        module._validate_pack_structure(zf, root=root, entries=entries)
        case_result, expected_diff = module._process_case(
            entry=entries[0],
            zf=zf,
            root=root,
            client=_FakeClient(),
            schema_version="0.2",
        )

    assert case_result["passed"] is True
    assert case_result["gate_failures"] == []
    assert case_result["runtime"]["issues_count"] >= 1
    assert case_result["runtime"]["citations_count"] >= 1
    assert expected_diff["case_id"] == "PDF-0001"


def test_process_case_fails_on_quality_gate_breaches(tmp_path: Path) -> None:
    module = _load_module()
    zip_path = _build_zip(tmp_path, case_ids=["PDF-0001"])

    with ZipFile(zip_path) as zf:
        root = module._resolve_pack_root(zf)
        entries = module._read_manifest(zf, root=root)
        case_result, _ = module._process_case(
            entry=entries[0],
            zf=zf,
            root=root,
            client=_FakeClient(leak_doctor_report=True, zero_citations=True),
            schema_version="0.2",
        )

    assert case_result["passed"] is False
    failures = set(case_result["gate_failures"])
    assert "patient_endpoint_leaked_doctor_report" in failures
    assert any(item.startswith("citations_count_lt_1") for item in failures)


def test_validate_xlsx_report_requires_minimum_sheets(tmp_path: Path) -> None:
    module = _load_module()
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Summary"
    workbook.create_sheet("CaseList")
    xlsx_path = tmp_path / "report.xlsx"
    workbook.save(xlsx_path)

    with pytest.raises(RuntimeError, match="missing required sheets"):
        module._validate_xlsx_report(xlsx_path)
