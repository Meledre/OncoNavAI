#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def _is_ru_text_compatible(text: str, *, max_latin_without_cyr: int = 10) -> bool:
    value = str(text or "")
    cyr = len(re.findall(r"[А-Яа-яЁё]", value))
    lat = len(re.findall(r"[A-Za-z]", value))
    if cyr >= 2:
        return True
    return lat <= max_latin_without_cyr


def _safe_div(num: float, den: float, *, default: float = 0.0) -> float:
    if den <= 0:
        return default
    return num / den


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    cases: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            cases.append(item)
    return cases


def _build_service(project_root: Path, *, offline_profiles: bool):
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from backend.app.config import Settings
    from backend.app.drugs.safety_provider import DrugSafetyFetchResult
    from backend.app.service import OncoService

    tmp_ctx = TemporaryDirectory()
    data = Path(tmp_ctx.name) / "data"
    settings = Settings(
        project_root=project_root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=100000,
        llm_primary_url="",
        llm_primary_model="",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="",
        llm_fallback_api_key="",
        oncoai_drug_safety_enabled=True,
    )
    service = OncoService(settings)
    if offline_profiles:
        service.drug_safety_provider.get_profiles = lambda inns: DrugSafetyFetchResult(  # type: ignore[assignment]
            status="unavailable",
            profiles=[],
            warnings=[],
        )
    return service, tmp_ctx


def evaluate_case(service: Any, case: dict[str, Any]) -> dict[str, Any]:
    from backend.app.drugs.models import build_patient_drug_safety

    case_id = str(case.get("id") or "").strip() or "unknown"
    case_text = str(case.get("text") or "").strip()
    expected_inn = sorted({str(item).strip().lower() for item in (case.get("expected_inn") or []) if str(item).strip()})
    expected_contra = bool(case.get("expected_contra_signal"))

    doctor_safety = service._build_drug_safety(case_text=case_text, case_json=None)
    patient_safety = build_patient_drug_safety(doctor_safety)

    extracted_inn = sorted({str(item.inn or "").strip().lower() for item in doctor_safety.extracted_inn if str(item.inn or "").strip()})
    extracted_set = set(extracted_inn)
    expected_set = set(expected_inn)
    tp = sorted(extracted_set.intersection(expected_set))
    fp = sorted(extracted_set.difference(expected_set))
    fn = sorted(expected_set.difference(extracted_set))

    has_contra = any(str(item.kind or "").strip().lower() == "contraindication" for item in doctor_safety.signals)
    ru_texts: list[str] = []
    for signal in doctor_safety.signals:
        if str(signal.summary or "").strip():
            ru_texts.append(str(signal.summary))
        if str(signal.details or "").strip():
            ru_texts.append(str(signal.details))
    ru_texts.extend(patient_safety.important_risks)
    ru_texts.extend(patient_safety.questions_for_doctor)
    ru_ok = all(_is_ru_text_compatible(item) for item in ru_texts)

    return {
        "id": case_id,
        "expected_inn": expected_inn,
        "extracted_inn": extracted_inn,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "expected_contra_signal": expected_contra,
        "predicted_contra_signal": has_contra,
        "status": doctor_safety.status,
        "signals": [asdict(item) for item in doctor_safety.signals],
        "warnings": [asdict(item) for item in doctor_safety.warnings],
        "patient": patient_safety.model_dump(),
        "ru_text_ok": ru_ok,
    }


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp_total = sum(len(item.get("tp") or []) for item in rows)
    fp_total = sum(len(item.get("fp") or []) for item in rows)
    fn_total = sum(len(item.get("fn") or []) for item in rows)

    extraction_precision = round(_safe_div(tp_total, tp_total + fp_total, default=1.0), 4)
    extraction_recall = round(_safe_div(tp_total, tp_total + fn_total, default=1.0), 4)

    positives = [item for item in rows if bool(item.get("expected_contra_signal"))]
    positive_hits = [item for item in positives if bool(item.get("predicted_contra_signal"))]
    critical_interaction_recall = round(_safe_div(len(positive_hits), len(positives), default=1.0), 4)

    predicted_positive = [item for item in rows if bool(item.get("predicted_contra_signal"))]
    predicted_true_positive = [item for item in predicted_positive if bool(item.get("expected_contra_signal"))]
    critical_interaction_precision = round(
        _safe_div(len(predicted_true_positive), len(predicted_positive), default=1.0),
        4,
    )

    ru_pass_count = sum(1 for item in rows if bool(item.get("ru_text_ok")))
    ru_text_quality_pass_rate = round(_safe_div(ru_pass_count, len(rows), default=1.0), 4)

    quality_score = round(
        (
            extraction_precision
            + critical_interaction_recall
            + ru_text_quality_pass_rate
        )
        / 3.0,
        4,
    )

    worst_rows = [
        item
        for item in rows
        if item.get("fp") or item.get("fn") or (bool(item.get("expected_contra_signal")) != bool(item.get("predicted_contra_signal"))) or not bool(item.get("ru_text_ok"))
    ]

    return {
        "cases_total": len(rows),
        "drug_extraction_precision": extraction_precision,
        "drug_extraction_recall": extraction_recall,
        "critical_interaction_recall": critical_interaction_recall,
        "critical_interaction_precision": critical_interaction_precision,
        "ru_text_quality_pass_rate": ru_text_quality_pass_rate,
        "quality_score": quality_score,
        "worst_cases": worst_rows[:10],
    }


def build_markdown_report(*, report: dict[str, Any], source_path: Path, thresholds: dict[str, float]) -> str:
    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
    gates = report.get("gates", {}) if isinstance(report.get("gates"), dict) else {}
    lines = [
        "# OncoAI Drug Safety Quality Report",
        "",
        f"- Dataset: `{source_path}`",
        f"- Cases: `{metrics.get('cases_total', 0)}`",
        "",
        "## Metrics",
        "",
        f"- `drug_extraction_precision`: **{metrics.get('drug_extraction_precision')}** (threshold `{thresholds['min_extraction_precision']}`)",
        f"- `critical_interaction_recall`: **{metrics.get('critical_interaction_recall')}** (threshold `{thresholds['min_critical_interaction_recall']}`)",
        f"- `ru_text_quality_pass_rate`: **{metrics.get('ru_text_quality_pass_rate')}** (threshold `{thresholds['min_ru_text_quality']}`)",
        f"- `quality_score`: **{metrics.get('quality_score')}** (threshold `{thresholds['min_quality_score']}`)",
        "",
        "## Gates",
        "",
        f"- `pass`: **{bool(gates.get('pass'))}**",
    ]
    failures = gates.get("failures") if isinstance(gates.get("failures"), list) else []
    if failures:
        lines.append("- `failures`:")
        for item in failures:
            lines.append(f"  - {item}")
    worst = metrics.get("worst_cases") if isinstance(metrics.get("worst_cases"), list) else []
    if worst:
        lines.extend(
            [
                "",
                "## Worst Cases",
                "",
            ]
        )
        for item in worst[:5]:
            case_id = str(item.get("id") or "unknown")
            fp = ", ".join(item.get("fp") or []) if isinstance(item.get("fp"), list) else ""
            fn = ", ".join(item.get("fn") or []) if isinstance(item.get("fn"), list) else ""
            mismatch = bool(item.get("expected_contra_signal")) != bool(item.get("predicted_contra_signal"))
            lines.append(f"- `{case_id}`: fp=[{fp}] fn=[{fn}] contra_mismatch={mismatch} ru_ok={bool(item.get('ru_text_ok'))}")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate drug safety quality metrics on synthetic cases.")
    parser.add_argument(
        "--dataset",
        default="data/synthetic_cases/drug_safety_cases_v1.json",
        help="Path to synthetic drug safety dataset JSON",
    )
    parser.add_argument("--out", default="docs/qa/drug_safety_quality_metrics_2026-02-23.json")
    parser.add_argument("--out-md", default="docs/qa/drug_safety_quality_report_2026-02-23.md")
    parser.add_argument("--offline-profiles", action="store_true", default=True)
    parser.add_argument("--min-extraction-precision", type=float, default=0.90)
    parser.add_argument("--min-critical-interaction-recall", type=float, default=0.90)
    parser.add_argument("--min-ru-text-quality", type=float, default=0.95)
    parser.add_argument("--min-quality-score", type=float, default=0.90)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = (project_root / dataset_path).resolve()
    cases = _load_cases(dataset_path)

    service, tmp_ctx = _build_service(project_root, offline_profiles=bool(args.offline_profiles))
    try:
        rows = [evaluate_case(service, item) for item in cases]
    finally:
        tmp_ctx.cleanup()

    metrics = compute_metrics(rows)
    thresholds = {
        "min_extraction_precision": float(args.min_extraction_precision),
        "min_critical_interaction_recall": float(args.min_critical_interaction_recall),
        "min_ru_text_quality": float(args.min_ru_text_quality),
        "min_quality_score": float(args.min_quality_score),
    }
    failures: list[str] = []
    if float(metrics["drug_extraction_precision"]) < thresholds["min_extraction_precision"]:
        failures.append(
            f"drug_extraction_precision={metrics['drug_extraction_precision']} < {thresholds['min_extraction_precision']}"
        )
    if float(metrics["critical_interaction_recall"]) < thresholds["min_critical_interaction_recall"]:
        failures.append(
            "critical_interaction_recall="
            f"{metrics['critical_interaction_recall']} < {thresholds['min_critical_interaction_recall']}"
        )
    if float(metrics["ru_text_quality_pass_rate"]) < thresholds["min_ru_text_quality"]:
        failures.append(
            f"ru_text_quality_pass_rate={metrics['ru_text_quality_pass_rate']} < {thresholds['min_ru_text_quality']}"
        )
    if float(metrics["quality_score"]) < thresholds["min_quality_score"]:
        failures.append(f"quality_score={metrics['quality_score']} < {thresholds['min_quality_score']}")

    report = {
        "schema_version": "1.0",
        "dataset": str(dataset_path),
        "metrics": metrics,
        "thresholds": thresholds,
        "gates": {
            "pass": len(failures) == 0,
            "failures": failures,
        },
        "cases": rows,
    }

    out_json_path = Path(args.out)
    if not out_json_path.is_absolute():
        out_json_path = (project_root / out_json_path).resolve()
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    out_md_path = Path(args.out_md)
    if not out_md_path.is_absolute():
        out_md_path = (project_root / out_md_path).resolve()
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.write_text(
        build_markdown_report(report=report, source_path=dataset_path, thresholds=thresholds),
        encoding="utf-8",
    )

    print(json.dumps({"out": str(out_json_path), "out_md": str(out_md_path), "pass": len(failures) == 0}, ensure_ascii=False))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
