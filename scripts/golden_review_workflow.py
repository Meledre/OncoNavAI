#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_STATUSES = {"clinician_reviewed", "approved"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if not token:
            continue
        payload = json.loads(token)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def _normalize_filter(raw: str) -> set[str]:
    return {item.strip().lower() for item in str(raw or "").split(",") if item.strip()}


def _load_pair_ids(path: str) -> set[str]:
    normalized = str(path or "").strip()
    if not normalized:
        return set()
    input_path = Path(normalized)
    raw = input_path.read_text(encoding="utf-8").strip()
    if not raw:
        return set()
    if input_path.suffix.lower() == ".json":
        payload = json.loads(raw)
        if isinstance(payload, list):
            return {str(item).strip() for item in payload if str(item).strip()}
    return {line.strip() for line in raw.splitlines() if line.strip()}


def _has_reviewer_metadata(row: dict[str, Any]) -> bool:
    return (
        bool(str(row.get("reviewer_id") or "").strip())
        and bool(str(row.get("reviewed_at") or "").strip())
        and bool(str(row.get("review_notes") or "").strip())
    )


def _is_reviewed(row: dict[str, Any]) -> bool:
    status = str(row.get("approval_status") or "").strip().lower()
    if status not in REVIEW_STATUSES:
        return False
    return _has_reviewer_metadata(row)


def _load_nosology_rows(golden_root: Path, nosology_filter: set[str]) -> dict[str, tuple[Path, list[dict[str, Any]]]]:
    files = sorted(golden_root.glob("*/golden_pairs_v1_2.jsonl"))
    if nosology_filter:
        files = [path for path in files if path.parent.name.lower() in nosology_filter]
    by_nosology: dict[str, tuple[Path, list[dict[str, Any]]]] = {}
    for file_path in files:
        nosology = file_path.parent.name.lower()
        by_nosology[nosology] = (file_path, _read_jsonl(file_path))
    return by_nosology


def _select_updates(
    *,
    by_nosology: dict[str, tuple[Path, list[dict[str, Any]]]],
    pair_ids: set[str],
    all_draft: bool,
    min_per_nosology: int | None,
) -> tuple[dict[str, set[int]], dict[str, int], dict[str, dict[str, int]]]:
    selected: dict[str, set[int]] = {nosology: set() for nosology in by_nosology}
    coverage: dict[str, dict[str, int]] = {}

    for nosology, (_path, rows) in by_nosology.items():
        reviewed = sum(1 for row in rows if _is_reviewed(row))
        draft = sum(1 for row in rows if str(row.get("approval_status") or "").strip().lower() == "draft")
        coverage[nosology] = {"total": len(rows), "reviewed": reviewed, "draft": draft}

    if pair_ids:
        for nosology, (_path, rows) in by_nosology.items():
            for idx, row in enumerate(rows):
                pair_id = str(row.get("golden_pair_id") or "").strip()
                if not pair_id or pair_id not in pair_ids:
                    continue
                if str(row.get("approval_status") or "").strip().lower() == "draft":
                    selected[nosology].add(idx)

    if all_draft:
        for nosology, (_path, rows) in by_nosology.items():
            for idx, row in enumerate(rows):
                if str(row.get("approval_status") or "").strip().lower() == "draft":
                    selected[nosology].add(idx)

    if min_per_nosology is not None:
        min_required = max(0, int(min_per_nosology))
        for nosology, (_path, rows) in by_nosology.items():
            reviewed = int(coverage[nosology]["reviewed"])
            planned = len(selected[nosology])
            need = max(0, min_required - reviewed - planned)
            if need <= 0:
                continue
            candidate_indices = [
                idx
                for idx, row in enumerate(rows)
                if str(row.get("approval_status") or "").strip().lower() == "draft" and idx not in selected[nosology]
            ]
            for idx in candidate_indices[:need]:
                selected[nosology].add(idx)

    deficits: dict[str, int] = {}
    if min_per_nosology is not None:
        min_required = max(0, int(min_per_nosology))
        for nosology, (_path, rows) in by_nosology.items():
            reviewed = int(coverage[nosology]["reviewed"])
            planned = len(selected[nosology])
            remaining_draft = sum(
                1
                for idx, row in enumerate(rows)
                if str(row.get("approval_status") or "").strip().lower() == "draft" and idx not in selected[nosology]
            )
            after_plan = reviewed + planned
            # Deficit means minimum cannot be met even after current selection.
            deficit = max(0, min_required - after_plan)
            if deficit > remaining_draft:
                deficit = max(0, min_required - reviewed - planned - remaining_draft) + max(
                    0, min_required - (reviewed + planned + remaining_draft)
                )
            if deficit:
                deficits[nosology] = deficit
            else:
                deficits[nosology] = 0
    return selected, deficits, coverage


def _apply_updates(
    *,
    by_nosology: dict[str, tuple[Path, list[dict[str, Any]]]],
    selected: dict[str, set[int]],
    status: str,
    reviewer_id: str,
    review_notes: str,
    reviewed_at: str,
) -> tuple[int, dict[str, int]]:
    updated_total = 0
    updated_by_nosology: dict[str, int] = {}
    for nosology, (_path, rows) in by_nosology.items():
        indices = selected.get(nosology, set())
        updated_count = 0
        for idx in sorted(indices):
            if idx < 0 or idx >= len(rows):
                continue
            row = rows[idx]
            row["approval_status"] = status
            row["reviewer_id"] = reviewer_id
            row["reviewed_at"] = reviewed_at
            row["review_notes"] = review_notes
            row["updated_at"] = reviewed_at
            updated_count += 1
        updated_by_nosology[nosology] = updated_count
        updated_total += updated_count
    return updated_total, updated_by_nosology


def _rebuild_all_file(golden_root: Path, by_nosology: dict[str, tuple[Path, list[dict[str, Any]]]]) -> Path:
    merged: list[dict[str, Any]] = []
    for nosology in sorted(by_nosology.keys()):
        _path, rows = by_nosology[nosology]
        merged.extend(rows)
    all_path = golden_root / "golden_pairs_v1_2_all.jsonl"
    _write_jsonl(all_path, merged)
    return all_path


def _recompute_coverage(by_nosology: dict[str, tuple[Path, list[dict[str, Any]]]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for nosology, (_path, rows) in by_nosology.items():
        reviewed = sum(1 for row in rows if _is_reviewed(row))
        draft = sum(1 for row in rows if str(row.get("approval_status") or "").strip().lower() == "draft")
        out[nosology] = {"total": len(rows), "reviewed": reviewed, "draft": draft}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden clinical review workflow helper")
    parser.add_argument("--golden-root", default="data/golden_answers")
    parser.add_argument("--status", choices=["clinician_reviewed", "approved"], default="clinician_reviewed")
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument("--reviewed-at", default="")
    parser.add_argument("--nosology-filter", default="")
    parser.add_argument("--pair-ids-file", default="")
    parser.add_argument("--all-draft", action="store_true")
    parser.add_argument("--min-per-nosology", type=int, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fail-on-deficit", action="store_true")
    parser.add_argument("--skip-rebuild-all", action="store_true")
    args = parser.parse_args()

    golden_root = Path(args.golden_root).resolve()
    nosology_filter = _normalize_filter(args.nosology_filter)
    pair_ids = _load_pair_ids(args.pair_ids_file)
    reviewed_at = str(args.reviewed_at or "").strip() or datetime.now(timezone.utc).isoformat()

    by_nosology = _load_nosology_rows(golden_root=golden_root, nosology_filter=nosology_filter)
    if not by_nosology:
        print(json.dumps({"error": "no golden nosology files found", "golden_root": str(golden_root)}, ensure_ascii=False))
        raise SystemExit(1)

    selected, deficits, coverage_before = _select_updates(
        by_nosology=by_nosology,
        pair_ids=pair_ids,
        all_draft=bool(args.all_draft),
        min_per_nosology=args.min_per_nosology,
    )
    selected_by_nosology = {nosology: len(indices) for nosology, indices in selected.items()}
    selected_total = sum(selected_by_nosology.values())

    applied_total = 0
    applied_by_nosology: dict[str, int] = {nosology: 0 for nosology in by_nosology}
    if args.apply:
        applied_total, applied_by_nosology = _apply_updates(
            by_nosology=by_nosology,
            selected=selected,
            status=str(args.status).strip(),
            reviewer_id=str(args.reviewer_id).strip(),
            review_notes=str(args.review_notes).strip(),
            reviewed_at=reviewed_at,
        )
        for _nosology, (path, rows) in by_nosology.items():
            _write_jsonl(path, rows)

    rebuilt_file = ""
    if not args.skip_rebuild_all and args.apply:
        rebuilt_file = str(_rebuild_all_file(golden_root=golden_root, by_nosology=by_nosology))

    coverage_after = _recompute_coverage(by_nosology)
    coverage_projected: dict[str, dict[str, int]] = {}
    for nosology in sorted(by_nosology.keys()):
        before = coverage_before.get(nosology) or {"total": 0, "reviewed": 0, "draft": 0}
        after = coverage_after.get(nosology) or {"total": 0, "reviewed": 0, "draft": 0}
        if args.apply:
            projected_reviewed = int(after.get("reviewed") or 0)
        else:
            projected_reviewed = int(before.get("reviewed") or 0) + int(selected_by_nosology.get(nosology) or 0)
        projected_reviewed = min(projected_reviewed, int(before.get("total") or 0))
        coverage_projected[nosology] = {
            "total": int(before.get("total") or 0),
            "reviewed": projected_reviewed,
            "draft": max(0, int(before.get("total") or 0) - projected_reviewed),
        }
    if args.min_per_nosology is not None:
        min_required = max(0, int(args.min_per_nosology))
        deficits = {
            nosology: max(0, min_required - int(coverage_projected.get(nosology, {}).get("reviewed") or 0))
            for nosology in sorted(by_nosology.keys())
        }

    result = {
        "golden_root": str(golden_root),
        "status_target": str(args.status),
        "apply": bool(args.apply),
        "selected_updates_total": selected_total,
        "selected_updates_by_nosology": selected_by_nosology,
        "applied_updates_total": applied_total,
        "applied_updates_by_nosology": applied_by_nosology,
        "min_per_nosology": args.min_per_nosology,
        "coverage_before": coverage_before,
        "coverage_after": coverage_after,
        "coverage_projected": coverage_projected,
        "deficits": deficits,
        "rebuilt_all_file": rebuilt_file,
    }
    print(json.dumps(result, ensure_ascii=False))

    has_deficit = any(int(value or 0) > 0 for value in deficits.values()) if deficits else False
    if args.fail_on_deficit and has_deficit:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
