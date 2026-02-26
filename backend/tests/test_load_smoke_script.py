from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_load_smoke_supports_gate_thresholds_without_network_calls() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/load_smoke.py",
            "--requests",
            "0",
            "--parallel",
            "1",
            "--max-p95-ms",
            "1",
            "--require-all-ok",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_load_smoke_fails_on_threshold_breach() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/load_smoke.py",
            "--requests",
            "0",
            "--parallel",
            "1",
            "--max-p95-ms",
            "-1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_load_smoke_accepts_http_timeout_argument() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/load_smoke.py",
            "--requests",
            "0",
            "--parallel",
            "1",
            "--http-timeout-sec",
            "45",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
