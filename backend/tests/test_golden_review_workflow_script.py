from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token:
            payload = json.loads(token)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def test_golden_review_script_apply_updates_minimum_per_nosology(tmp_path: Path) -> None:
    golden_root = tmp_path / "data" / "golden_answers"
    _write_jsonl(
        golden_root / "lung" / "golden_pairs_v1_2.jsonl",
        [
            {"golden_pair_id": "g-lung-001", "nosology": "lung", "approval_status": "draft"},
            {"golden_pair_id": "g-lung-002", "nosology": "lung", "approval_status": "draft"},
        ],
    )
    _write_jsonl(
        golden_root / "breast" / "golden_pairs_v1_2.jsonl",
        [
            {"golden_pair_id": "g-breast-001", "nosology": "breast", "approval_status": "draft"},
            {"golden_pair_id": "g-breast-002", "nosology": "breast", "approval_status": "draft"},
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/golden_review_workflow.py",
            "--golden-root",
            str(golden_root),
            "--status",
            "clinician_reviewed",
            "--reviewer-id",
            "clinician-qa",
            "--review-notes",
            "Spot-check reviewed.",
            "--min-per-nosology",
            "1",
            "--apply",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    lung_rows = _read_jsonl(golden_root / "lung" / "golden_pairs_v1_2.jsonl")
    breast_rows = _read_jsonl(golden_root / "breast" / "golden_pairs_v1_2.jsonl")
    reviewed_lung = [row for row in lung_rows if row.get("approval_status") == "clinician_reviewed"]
    reviewed_breast = [row for row in breast_rows if row.get("approval_status") == "clinician_reviewed"]
    assert len(reviewed_lung) >= 1
    assert len(reviewed_breast) >= 1
    assert all(str(row.get("reviewer_id") or "").strip() for row in reviewed_lung + reviewed_breast)
    assert all(str(row.get("reviewed_at") or "").strip() for row in reviewed_lung + reviewed_breast)
    assert all(str(row.get("review_notes") or "").strip() for row in reviewed_lung + reviewed_breast)

    merged = _read_jsonl(golden_root / "golden_pairs_v1_2_all.jsonl")
    assert len(merged) == len(lung_rows) + len(breast_rows)


def test_golden_review_script_fail_on_deficit(tmp_path: Path) -> None:
    golden_root = tmp_path / "data" / "golden_answers"
    _write_jsonl(
        golden_root / "lung" / "golden_pairs_v1_2.jsonl",
        [{"golden_pair_id": "g-lung-001", "nosology": "lung", "approval_status": "draft"}],
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/golden_review_workflow.py",
            "--golden-root",
            str(golden_root),
            "--status",
            "clinician_reviewed",
            "--reviewer-id",
            "clinician-qa",
            "--review-notes",
            "Spot-check reviewed.",
            "--nosology-filter",
            "lung",
            "--min-per-nosology",
            "2",
            "--fail-on-deficit",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    deficits = payload.get("deficits")
    assert isinstance(deficits, dict)
    assert int(deficits.get("lung") or 0) >= 1
