#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _validate_contains(path: Path, required: list[str]) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing_file:{path.as_posix()}"]
    text = path.read_text(encoding="utf-8")
    for token in required:
        if token not in text:
            errors.append(f"missing_token:{path.as_posix()}::{token}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate release-readiness docs and artifacts")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--out",
        default="reports/release/readiness_report.json",
        help="Path to write readiness report JSON",
    )
    parser.add_argument(
        "--require-quality-artifacts",
        action="store_true",
        help="Also validate metrics quality artifact presence and required keys",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    runbook = repo_root / "docs" / "deploy" / "release_readiness_runbook.md"
    checklist = repo_root / "docs" / "qa" / "regression_checklist.md"
    freeze = repo_root / "docs" / "cap" / "v0_4_bridge_freeze_summary.md"
    traceability_md = repo_root / "docs" / "cap" / "requirements_traceability_2026-02-23.md"
    traceability_json = repo_root / "reports" / "metrics" / "requirements_traceability_2026-02-23.json"
    latest_metrics = repo_root / "reports" / "metrics" / "latest.json"

    errors: list[str] = []
    errors.extend(
        _validate_contains(
            runbook,
            [
                "# OncoAI Release Readiness Runbook",
                "## Rollback Plan",
                "## SLO and Alert Checklist",
                "./onco preflight",
                "./onco incident-check",
                "./onco security-check",
                "./onco release-readiness",
            ],
        )
    )
    errors.extend(
        _validate_contains(
            checklist,
            [
                "security-check",
                "release-readiness",
            ],
        )
    )
    errors.extend(
        _validate_contains(
            freeze,
            [
                "release readiness",
                "D73",
                "D74",
            ],
        )
    )
    errors.extend(
        _validate_contains(
            traceability_md,
            [
                "# Requirements Traceability (OncoAI)",
                "CR matrix",
                "DF matrix",
            ],
        )
    )
    if not traceability_json.exists():
        errors.append(f"missing_file:{traceability_json.as_posix()}")
    else:
        try:
            payload = json.loads(traceability_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append(f"invalid_json:{traceability_json.as_posix()}")
        else:
            if not isinstance(payload, dict):
                errors.append(f"invalid_payload:{traceability_json.as_posix()}")
            else:
                for required_key in ("cr", "df", "new_metrics"):
                    if required_key not in payload:
                        errors.append(f"missing_key:{traceability_json.as_posix()}::{required_key}")

    if args.require_quality_artifacts:
        if not latest_metrics.exists():
            errors.append(f"missing_file:{latest_metrics.as_posix()}")
        else:
            try:
                metrics_payload = json.loads(latest_metrics.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                errors.append(f"invalid_json:{latest_metrics.as_posix()}")
            else:
                if not isinstance(metrics_payload, dict):
                    errors.append(f"invalid_payload:{latest_metrics.as_posix()}")
                else:
                    for required_key in (
                        "recall_like",
                        "precision",
                        "f1",
                        "top3_acceptance_rate",
                        "sus_score",
                        "clinical_decision_quality",
                    ):
                        if required_key not in metrics_payload:
                            errors.append(f"missing_key:{latest_metrics.as_posix()}::{required_key}")
                    decision_quality = (
                        metrics_payload.get("clinical_decision_quality")
                        if isinstance(metrics_payload.get("clinical_decision_quality"), dict)
                        else {}
                    )
                    for required_key in ("approved_ratio", "rewrite_required_rate", "per_nosology"):
                        if required_key not in decision_quality:
                            errors.append(
                                f"missing_key:{latest_metrics.as_posix()}::clinical_decision_quality.{required_key}"
                            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": not errors,
        "errors": errors,
        "files": {
            "runbook": runbook.as_posix(),
            "regression_checklist": checklist.as_posix(),
            "freeze_summary": freeze.as_posix(),
            "traceability_markdown": traceability_md.as_posix(),
            "traceability_json": traceability_json.as_posix(),
            "latest_metrics": latest_metrics.as_posix(),
        },
    }

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    if errors:
        print(json.dumps(report, ensure_ascii=True))
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
