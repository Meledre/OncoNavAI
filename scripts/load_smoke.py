#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _default_http_timeout_sec() -> float:
    raw = str(os.environ.get("ONCO_LOAD_HTTP_TIMEOUT_SEC", "30")).strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    return max(1.0, min(value, 900.0))


def call_once(base_url: str, payload: dict, token: str, idx: int, timeout_sec: float) -> tuple[int, float]:
    request_payload = dict(payload)
    request_payload["request_id"] = f"load-smoke-{idx}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/analyze",
        method="POST",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-role": "clinician",
            "x-client-id": f"load-{idx}",
            "x-demo-token": token,
        },
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=float(timeout_sec)) as response:
            _ = response.read()
            latency = (time.perf_counter() - start) * 1000.0
            return response.status, latency
    except urllib.error.HTTPError as exc:
        _ = exc.read()
        latency = (time.perf_counter() - start) * 1000.0
        return int(exc.code), latency


def main() -> None:
    parser = argparse.ArgumentParser(description="Mini load smoke for /analyze")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", default="demo-token")
    parser.add_argument("--parallel", type=int, default=5)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--schema-version", choices=["0.1", "0.2"], default="0.1")
    parser.add_argument("--max-p95-ms", type=float, default=None)
    parser.add_argument("--http-timeout-sec", type=float, default=_default_http_timeout_sec())
    parser.add_argument("--require-all-ok", action="store_true")
    args = parser.parse_args()

    if args.schema_version == "0.2":
        payload = {
            "schema_version": "0.2",
            "request_id": "load-smoke-template",
            "query_type": "CHECK_LAST_TREATMENT",
            "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
            "language": "ru",
            "case": {
                "case_json": {
                    "schema_version": "1.0",
                    "case_id": "load-smoke-case",
                    "import_profile": "CUSTOM_TEMPLATE",
                    "patient": {"sex": "female", "birth_year": 1963},
                    "diagnoses": [
                        {
                            "diagnosis_id": "load-smoke-dx",
                            "disease_id": "load-smoke-dis",
                            "icd10": "C34",
                            "histology": "adenocarcinoma",
                            "stage": {"system": "TNM8", "stage_group": "IV"},
                            "biomarkers": [{"name": "EGFR", "value": "L858R"}],
                            "timeline": [],
                            "last_plan": {
                                "date": "2026-02-20",
                                "precision": "day",
                                "regimen": "Осимертиниб 80 мг ежедневно",
                                "line": 1,
                                "cycle": 1,
                            },
                        }
                    ],
                    "attachments": [],
                    "notes": "Синтетический кейс для load-smoke.",
                }
            },
            "options": {"strict_evidence": True, "max_chunks": 40, "max_citations": 40, "timeout_ms": 120000},
        }
    else:
        payload = {
            "schema_version": args.schema_version,
            "request_id": "load-smoke-template",
            "case": {"cancer_type": "nsclc_egfr", "language": "ru", "notes": "Синтетический кейс"},
            "treatment_plan": {"plan_text": "Системная терапия: осимертиниб"},
        }

    statuses = []
    latencies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = [
            executor.submit(call_once, args.base_url, payload, args.token, idx, args.http_timeout_sec)
            for idx in range(args.requests)
        ]
        for future in concurrent.futures.as_completed(futures):
            status, latency = future.result()
            statuses.append(status)
            latencies.append(latency)

    latencies.sort()
    p50 = latencies[int(0.5 * (len(latencies) - 1))] if latencies else 0
    p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else 0

    report = {
        "requests": args.requests,
        "parallel": args.parallel,
        "ok": sum(1 for status in statuses if status == 200),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
    }
    print(json.dumps(report, ensure_ascii=False))

    gate_failures: list[str] = []
    if args.require_all_ok and report["ok"] != args.requests:
        gate_failures.append(f"ok={report['ok']} != requests={args.requests}")
    if args.max_p95_ms is not None and report["p95_ms"] > args.max_p95_ms:
        gate_failures.append(f"p95_ms={report['p95_ms']} > {args.max_p95_ms}")

    if gate_failures:
        for failure in gate_failures:
            print(f"GATE_FAIL: {failure}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
