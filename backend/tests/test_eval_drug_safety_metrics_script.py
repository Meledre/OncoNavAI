from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_eval_drug_safety_metrics_script_passes_default_gates(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    out_json = tmp_path / "drug_safety_metrics.json"
    out_md = tmp_path / "drug_safety_metrics.md"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/eval_drug_safety_metrics.py",
            "--dataset",
            "data/synthetic_cases/drug_safety_cases_v1.json",
            "--out",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["gates"]["pass"] is True
    assert float(report["metrics"]["drug_extraction_precision"]) >= 0.9
    assert float(report["metrics"]["critical_interaction_recall"]) >= 0.9
    assert float(report["metrics"]["ru_text_quality_pass_rate"]) >= 0.95
    assert float(report["metrics"]["quality_score"]) >= 0.9
    assert out_md.exists()
