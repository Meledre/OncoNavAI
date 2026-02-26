from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_summary(path: Path, *, level: str, alerts: list[dict[str, object]]) -> None:
    payload = {
        "window_hours": 24,
        "from_ts": "2026-02-20T00:00:00+00:00",
        "to_ts": "2026-02-20T23:59:59+00:00",
        "total_events": 100,
        "unique_users": 5,
        "outcome_counts": {"allow": 90, "deny": 8, "info": 1, "error": 1},
        "reason_group_counts": {"auth": 10},
        "top_reasons": [],
        "top_events": [],
        "incident_level": level,
        "incident_score": 80 if level == "high" else 10,
        "incident_signals": {
            "deny_rate": 0.08,
            "error_count": 1,
            "replay_detected_count": 0,
            "config_error_count": 0,
            "min_events_for_deny_rate_alert": 10,
        },
        "alerts": alerts,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_session_incident_gate_script_passes_when_level_below_threshold(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    out_path = tmp_path / "report.json"
    _write_summary(summary_path, level="none", alerts=[])

    result = subprocess.run(
        [
            sys.executable,
            "scripts/session_incident_gate.py",
            "--summary-json",
            str(summary_path),
            "--fail-on-level",
            "high",
            "--out",
            str(out_path),
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["details"]["incident_level"] == "none"


def test_session_incident_gate_script_fails_when_level_reaches_threshold(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    out_path = tmp_path / "report.json"
    _write_summary(summary_path, level="high", alerts=[{"code": "deny_rate_exceeded", "level": "critical"}])

    result = subprocess.run(
        [
            sys.executable,
            "scripts/session_incident_gate.py",
            "--summary-json",
            str(summary_path),
            "--fail-on-level",
            "high",
            "--out",
            str(out_path),
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert any("incident_level=high" in error for error in report["errors"])


def test_session_incident_gate_script_fails_on_critical_alert_budget(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    out_path = tmp_path / "report.json"
    _write_summary(
        summary_path,
        level="low",
        alerts=[
            {"code": "deny_rate_exceeded", "level": "warn"},
            {"code": "replay_detected_count_exceeded", "level": "critical"},
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/session_incident_gate.py",
            "--summary-json",
            str(summary_path),
            "--fail-on-level",
            "off",
            "--max-critical-alerts",
            "0",
            "--out",
            str(out_path),
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert any("critical_alerts=1 > max_critical_alerts=0" == error for error in report["errors"])
