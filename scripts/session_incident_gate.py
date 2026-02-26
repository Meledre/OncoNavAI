#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LEVEL_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _normalize_level(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    return value if value in LEVEL_ORDER else "none"


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _load_summary_from_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("summary_json must contain a JSON object")
    return data


def _fetch_summary(
    *,
    base_url: str,
    token: str,
    window_hours: int,
    from_ts: str,
    to_ts: str,
    timeout_sec: int,
) -> tuple[int, dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "window_hours": str(window_hours),
            "from_ts": from_ts.strip(),
            "to_ts": to_ts.strip(),
        }
    )
    url = f"{base_url.rstrip('/')}/session/audit/summary?{params}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "x-role": "admin",
            "x-demo-token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("summary response is not a JSON object")
            return int(response.status), payload
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8") if exc.fp else ""
        payload: dict[str, Any] = {}
        if text:
            try:
                decoded = json.loads(text)
                if isinstance(decoded, dict):
                    payload = decoded
            except json.JSONDecodeError:
                payload = {"raw": text}
        return int(exc.code), payload


def _evaluate(
    *,
    summary: dict[str, Any],
    fail_on_level: str,
    max_critical_alerts: int,
    max_warn_alerts: int,
) -> tuple[bool, list[str], dict[str, Any]]:
    incident_level = _normalize_level(summary.get("incident_level"))
    incident_score = _safe_int(summary.get("incident_score"), 0)
    alerts_raw = summary.get("alerts")
    alerts = alerts_raw if isinstance(alerts_raw, list) else []

    critical_alerts = sum(1 for item in alerts if isinstance(item, dict) and str(item.get("level") or "") == "critical")
    warn_alerts = sum(1 for item in alerts if isinstance(item, dict) and str(item.get("level") or "") == "warn")

    reasons: list[str] = []
    normalized_fail_level = _normalize_level(fail_on_level)
    if normalized_fail_level != "none" and fail_on_level != "off":
        if LEVEL_ORDER[incident_level] >= LEVEL_ORDER[normalized_fail_level]:
            reasons.append(
                f"incident_level={incident_level} >= fail_on_level={normalized_fail_level}"
            )

    if max_critical_alerts >= 0 and critical_alerts > max_critical_alerts:
        reasons.append(
            f"critical_alerts={critical_alerts} > max_critical_alerts={max_critical_alerts}"
        )
    if max_warn_alerts >= 0 and warn_alerts > max_warn_alerts:
        reasons.append(
            f"warn_alerts={warn_alerts} > max_warn_alerts={max_warn_alerts}"
        )

    details = {
        "incident_level": incident_level,
        "incident_score": incident_score,
        "critical_alerts": critical_alerts,
        "warn_alerts": warn_alerts,
        "total_alerts": len(alerts),
        "total_events": _safe_int(summary.get("total_events"), 0),
        "unique_users": _safe_int(summary.get("unique_users"), 0),
    }
    return len(reasons) == 0, reasons, details


def main() -> int:
    parser = argparse.ArgumentParser(description="OncoAI session incident gate")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--token", default="demo-token", help="Backend demo token")
    parser.add_argument("--window-hours", type=int, default=24, help="Summary window in hours")
    parser.add_argument("--from-ts", default="", help="Optional summary from timestamp (ISO)")
    parser.add_argument("--to-ts", default="", help="Optional summary to timestamp (ISO)")
    parser.add_argument(
        "--fail-on-level",
        default="high",
        choices=["off", "none", "low", "medium", "high"],
        help="Fail gate when incident_level >= this level (off disables level check)",
    )
    parser.add_argument(
        "--max-critical-alerts",
        type=int,
        default=-1,
        help="Fail when critical alert count is greater than this value (-1 disables)",
    )
    parser.add_argument(
        "--max-warn-alerts",
        type=int,
        default=-1,
        help="Fail when warn alert count is greater than this value (-1 disables)",
    )
    parser.add_argument(
        "--summary-json",
        default="",
        help="Optional path to summary JSON fixture (skips HTTP request)",
    )
    parser.add_argument(
        "--out",
        default="reports/security/session_incident_gate.json",
        help="Path to write gate report JSON",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=20,
        help="HTTP timeout in seconds for summary request",
    )
    args = parser.parse_args()

    summary_source = "http"
    status = 200
    summary_payload: dict[str, Any]
    if args.summary_json.strip():
        summary_source = "file"
        summary_payload = _load_summary_from_file(Path(args.summary_json.strip()))
    else:
        status, summary_payload = _fetch_summary(
            base_url=args.base_url,
            token=args.token,
            window_hours=max(1, min(int(args.window_hours), 24 * 7)),
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            timeout_sec=max(1, min(int(args.timeout_sec), 120)),
        )
        if status < 200 or status >= 300:
            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "ok": False,
                "source": summary_source,
                "http_status": status,
                "errors": [f"summary_http_status={status}"],
                "summary": summary_payload,
            }
            out_path = Path(args.out)
            _write_json(out_path, report)
            print(json.dumps(report, ensure_ascii=True))
            return 1

    ok, reasons, details = _evaluate(
        summary=summary_payload,
        fail_on_level=args.fail_on_level,
        max_critical_alerts=int(args.max_critical_alerts),
        max_warn_alerts=int(args.max_warn_alerts),
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "source": summary_source,
        "http_status": status,
        "policy": {
            "fail_on_level": args.fail_on_level,
            "max_critical_alerts": int(args.max_critical_alerts),
            "max_warn_alerts": int(args.max_warn_alerts),
        },
        "details": details,
        "errors": reasons,
        "summary": summary_payload,
    }
    out_path = Path(args.out)
    _write_json(out_path, report)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
