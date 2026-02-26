#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_DIR = ROOT_DIR / "reports" / "release"
DEFAULT_TRACEABILITY_JSON = ROOT_DIR / "reports" / "metrics" / "requirements_traceability_2026-02-23.json"
DEFAULT_READINESS_JSON = ROOT_DIR / "reports" / "release" / "readiness_report.json"
DEFAULT_LATEST_METRICS_JSON = ROOT_DIR / "reports" / "metrics" / "latest.json"
DEFAULT_PDF_PACK_ZIP = Path("/Users/meledre/Downloads/synthetic_pdf_cases_200_v8_smooth.zip")
DEFAULT_PDF_PACK_XLSX = Path("/Users/meledre/Downloads/v8_smooth_analysis_report.xlsx")

DEFAULT_BAKEOFF_CASE_IDS: list[str] = [
    "PDF-0049",
    "PDF-0086",
    "PDF-0130",
    "PDF-0012",
    "PDF-0003",
    "PDF-0007",
    "PDF-0014",
    "PDF-0002",
    "PDF-0010",
    "PDF-0017",
]


@dataclass(frozen=True)
class RouteConfig:
    name: str
    chat_url: str
    embeddings_url: str
    api_key: str
    chat_model: str
    embedding_model: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"json payload must be an object: {path}")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _slugify_model(model: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", model.strip().lower()).strip("-")
    return clean or "model"


def _parse_case_ids(case_list: str, *, default_ids: list[str]) -> list[str]:
    value = str(case_list or "").strip()
    if not value:
        return list(default_ids)

    as_path = Path(value).expanduser()
    raw_items: list[str]
    if as_path.exists() and as_path.is_file():
        raw_items = [line.strip() for line in as_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        raw_items = [item.strip() for item in value.split(",") if item.strip()]

    deduped: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    if not deduped:
        return list(default_ids)
    return deduped


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    bounded_pct = max(0.0, min(float(pct), 100.0))
    position = (len(ordered) - 1) * (bounded_pct / 100.0)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return round(ordered[low], 3)
    fraction = position - low
    interpolated = ordered[low] + (ordered[high] - ordered[low]) * fraction
    return round(interpolated, 3)


def _latency_stats_ms(case_rows: list[dict[str, Any]]) -> dict[str, float | int]:
    durations_ms: list[float] = []
    for row in case_rows:
        runtime = row.get("runtime") if isinstance(row.get("runtime"), dict) else {}
        duration_sec = float(runtime.get("duration_sec") or 0.0)
        if duration_sec > 0:
            durations_ms.append(round(duration_sec * 1000.0, 3))
    if not durations_ms:
        return {
            "count": 0,
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p90_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
        }

    avg_ms = round(sum(durations_ms) / len(durations_ms), 3)
    return {
        "count": len(durations_ms),
        "avg_ms": avg_ms,
        "p50_ms": _percentile(durations_ms, 50),
        "p90_ms": _percentile(durations_ms, 90),
        "p95_ms": _percentile(durations_ms, 95),
        "max_ms": round(max(durations_ms), 3),
    }


def _quality_ok(profile: dict[str, Any]) -> bool:
    return int(profile.get("cases_failed") or 0) == 0


def _sla_ok(profile: dict[str, Any], *, sla_ms: float) -> bool:
    latency = profile.get("latency") if isinstance(profile.get("latency"), dict) else {}
    p95 = float(latency.get("p95_ms") or 0.0)
    return p95 <= float(sla_ms)


def _select_model_profile(results: list[dict[str, Any]], *, sla_ms: float) -> dict[str, Any]:
    for profile in results:
        if _quality_ok(profile) and _sla_ok(profile, sla_ms=sla_ms):
            picked = dict(profile)
            picked["decision"] = "sla_pass"
            return picked

    quality_profiles = [item for item in results if _quality_ok(item)]
    if quality_profiles:
        picked_quality = min(
            quality_profiles,
            key=lambda item: float((item.get("latency") or {}).get("p95_ms") or float("inf")),
        )
        picked = dict(picked_quality)
        picked["decision"] = "no_sla_pass_best_quality"
        return picked

    picked_any = min(
        results,
        key=lambda item: float((item.get("latency") or {}).get("p95_ms") or float("inf")),
    )
    picked = dict(picked_any)
    picked["decision"] = "no_quality_pass_fastest_available"
    return picked


def _build_model_decision_markdown(report: dict[str, Any]) -> str:
    selected = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    selected_model = str(selected.get("model") or "")
    selected_decision = str(selected.get("decision") or "")
    selected_p95 = (
        selected.get("latency", {}).get("p95_ms")
        if isinstance(selected.get("latency"), dict)
        else None
    )
    lines: list[str] = [
        "# Model Decision (Strict Full Demo)",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- SLA (p95, full doctor+patient chain): `{report.get('sla_ms')} ms`",
        f"- Selected model: `{selected_model}`",
        f"- Decision: `{selected_decision}`",
        f"- Selected p95: `{selected_p95}`",
        "",
        "## Profiles",
        "",
    ]
    profiles = report.get("profiles") if isinstance(report.get("profiles"), list) else []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        model = str(profile.get("model") or "")
        failed = int(profile.get("cases_failed") or 0)
        latency = profile.get("latency") if isinstance(profile.get("latency"), dict) else {}
        lines.append(
            "- "
            f"`{model}`: p95={latency.get('p95_ms')} ms, "
            f"cases_failed={failed}, gate_ok={failed == 0}"
        )
    lines.append("")
    return "\n".join(lines)


def _collect_yellow(traceability: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = traceability.get(key)
    if not isinstance(values, list):
        return []
    result: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").upper() == "YELLOW":
            result.append(item)
    return result


def _build_demo_waiver_markdown(
    *,
    traceability: dict[str, Any],
    generated_at: str,
    remediation_deadline: str,
    mitigation: str,
) -> str:
    cr_yellow = _collect_yellow(traceability, "cr")
    df_yellow = _collect_yellow(traceability, "df")

    lines: list[str] = [
        "# Demo Waiver (Strict Full)",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Remediation deadline: `{remediation_deadline}`",
        f"- Compensating controls: `{mitigation}`",
        "",
        "## CR YELLOW",
        "",
    ]
    if not cr_yellow:
        lines.append("- None")
    else:
        for item in cr_yellow:
            lines.append(
                "- "
                f"`{item.get('id')}` owner=`{item.get('owner', 'n/a')}` eta=`{item.get('eta', 'n/a')}`"
            )

    lines.extend(["", "## DF YELLOW", ""])
    if not df_yellow:
        lines.append("- None")
    else:
        for item in df_yellow:
            lines.append(
                "- "
                f"`{item.get('id')}` owner=`{item.get('owner', 'n/a')}` eta=`{item.get('eta', 'n/a')}`"
            )

    lines.extend(
        [
            "",
            "## Decision",
            "",
            "Demo release is allowed with formal waiver for listed YELLOW items, under strict_full fail-closed policy.",
            "",
        ]
    )
    return "\n".join(lines)


def _default_chat_url(base: str) -> str:
    value = str(base or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/v1/chat/completions"):
        return value
    if value.endswith("/v1"):
        return f"{value}/chat/completions"
    return f"{value}/v1/chat/completions"


def _default_embeddings_url(base: str) -> str:
    value = str(base or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/v1/embeddings"):
        return value
    if value.endswith("/v1"):
        return f"{value}/embeddings"
    return f"{value}/v1/embeddings"


def _request_json(
    *,
    url: str,
    payload: dict[str, Any],
    timeout_sec: int,
    api_key: str,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            **({"authorization": f"Bearer {api_key}"} if api_key else {}),
        },
    )
    started = time.monotonic()
    status = 0
    text = ""
    error = ""
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            status = int(response.status)
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    latency_ms = round((time.monotonic() - started) * 1000.0, 3)
    ok = 200 <= status < 300 and not error

    response_preview = ""
    if text:
        response_preview = text[:300]

    return {
        "ok": ok,
        "status": status,
        "latency_ms": latency_ms,
        "error": error,
        "response_preview": response_preview,
    }


def _probe_route(
    *,
    route: RouteConfig,
    timeout_sec: int,
    attempts: int,
    sleep_between_sec: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        chat_check = _request_json(
            url=route.chat_url,
            payload={
                "model": route.chat_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout_sec=timeout_sec,
            api_key=route.api_key,
        )
        embeddings_check = _request_json(
            url=route.embeddings_url,
            payload={"model": route.embedding_model, "input": "ping"},
            timeout_sec=timeout_sec,
            api_key=route.api_key,
        )
        attempt_ok = bool(chat_check.get("ok")) and bool(embeddings_check.get("ok"))
        checks.append(
            {
                "attempt": attempt,
                "ok": attempt_ok,
                "chat": chat_check,
                "embeddings": embeddings_check,
            }
        )
        if attempt < attempts and sleep_between_sec > 0:
            time.sleep(sleep_between_sec)

    stable = all(bool(item.get("ok")) for item in checks)
    return {
        "name": route.name,
        "chat_url": route.chat_url,
        "embeddings_url": route.embeddings_url,
        "chat_model": route.chat_model,
        "embedding_model": route.embedding_model,
        "stable": stable,
        "attempts": checks,
    }


def _pick_route(*, native: dict[str, Any] | None, provider: dict[str, Any] | None) -> str:
    if native and bool(native.get("stable")):
        return "native"
    if provider and bool(provider.get("stable")):
        return "provider"
    return ""


def _run_command(cmd: list[str], *, timeout_sec: int = 0) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "text": True,
        "capture_output": True,
        "check": False,
        "cwd": str(ROOT_DIR),
    }
    if timeout_sec > 0:
        kwargs["timeout"] = timeout_sec
    result = subprocess.run(cmd, **kwargs)
    return result


def _run_shell_command(command: str, *, timeout_sec: int = 0) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "text": True,
        "capture_output": True,
        "check": False,
        "cwd": str(ROOT_DIR),
        "shell": True,
    }
    if timeout_sec > 0:
        kwargs["timeout"] = timeout_sec
    return subprocess.run(command, **kwargs)


def _latest_release_artifact(prefix: str) -> str:
    if not DEFAULT_RELEASE_DIR.exists():
        return ""
    candidates = sorted(DEFAULT_RELEASE_DIR.glob(f"{prefix}_*.json"))
    if not candidates:
        return ""
    return str(candidates[-1])


def cmd_connectivity(args: argparse.Namespace) -> int:
    out_dir = _ensure_dir(Path(args.out_dir).expanduser().resolve())
    routes: dict[str, dict[str, Any]] = {}

    native_route: dict[str, Any] | None = None
    if args.native_chat_url and args.native_embeddings_url:
        native_route = _probe_route(
            route=RouteConfig(
                name="native",
                chat_url=args.native_chat_url,
                embeddings_url=args.native_embeddings_url,
                api_key=args.native_api_key,
                chat_model=args.chat_model,
                embedding_model=args.embedding_model,
            ),
            timeout_sec=args.timeout_sec,
            attempts=args.attempts,
            sleep_between_sec=args.sleep_between_sec,
        )
        routes["native"] = native_route

    provider_route: dict[str, Any] | None = None
    if args.provider_chat_url and args.provider_embeddings_url:
        provider_route = _probe_route(
            route=RouteConfig(
                name="provider",
                chat_url=args.provider_chat_url,
                embeddings_url=args.provider_embeddings_url,
                api_key=args.provider_api_key,
                chat_model=args.chat_model,
                embedding_model=args.embedding_model,
            ),
            timeout_sec=args.timeout_sec,
            attempts=args.attempts,
            sleep_between_sec=args.sleep_between_sec,
        )
        routes["provider"] = provider_route

    selected_route = _pick_route(native=native_route, provider=provider_route)
    report = {
        "generated_at": _utc_now().isoformat(),
        "policy": "prefer_native_else_provider_full_egress",
        "selected_route": selected_route,
        "routes": routes,
    }
    out_path = out_dir / f"prod_connectivity_report_{_timestamp()}.json"
    _write_json(out_path, report)
    print(json.dumps({"selected_route": selected_route, "report": str(out_path)}, ensure_ascii=True))
    return 0 if selected_route else 1


def _run_bakeoff_profile(
    *,
    model: str,
    case_ids: list[str],
    args: argparse.Namespace,
    out_dir: Path,
) -> dict[str, Any]:
    model_slug = _slugify_model(model)
    profile_out_dir = out_dir / f"profile_{model_slug}"

    switch_stdout = ""
    switch_stderr = ""
    if args.model_switch_cmd_template:
        switch_cmd = args.model_switch_cmd_template.format(model=model)
        switch_result = _run_shell_command(switch_cmd, timeout_sec=max(60, args.switch_timeout_sec))
        switch_stdout = switch_result.stdout
        switch_stderr = switch_result.stderr
        if switch_result.returncode != 0:
            raise RuntimeError(
                "model switch command failed: "
                f"model={model}, cmd={switch_cmd!r}, rc={switch_result.returncode}, "
                f"stderr={switch_stderr.strip()!r}"
            )

    eval_cmd = [
        sys.executable,
        str(Path(args.eval_script).expanduser().resolve()),
        "--zip",
        str(Path(args.zip).expanduser().resolve()),
        "--base-url",
        args.base_url,
        "--auth-mode",
        args.auth_mode,
        "--schema-version",
        args.schema_version,
        "--sample-mode",
        "pilot",
        "--case-list",
        ",".join(case_ids),
        "--out-dir",
        str(profile_out_dir),
        "--http-timeout",
        str(args.http_timeout),
        "--workers",
        str(args.workers),
    ]
    if args.xlsx and Path(args.xlsx).expanduser().exists():
        eval_cmd.extend(["--xlsx", str(Path(args.xlsx).expanduser().resolve())])

    eval_result = _run_command(eval_cmd, timeout_sec=max(300, args.eval_timeout_sec))
    summary_path = profile_out_dir / "summary.json"
    per_case_path = profile_out_dir / "per_case.jsonl"
    if not summary_path.exists() or not per_case_path.exists():
        raise RuntimeError(
            "eval_pdf_pack did not produce expected artifacts: "
            f"model={model}, rc={eval_result.returncode}, stdout={eval_result.stdout[-800:]!r}, stderr={eval_result.stderr[-800:]!r}"
        )

    summary_payload = _load_json_file(summary_path)
    per_case_rows = _load_jsonl(per_case_path)
    latency = _latency_stats_ms(per_case_rows)
    cases_failed = int(summary_payload.get("cases_failed") or 0)
    cases_total = int(summary_payload.get("cases_total") or len(per_case_rows))
    cases_passed = int(summary_payload.get("cases_passed") or max(0, cases_total - cases_failed))

    return {
        "model": model,
        "cases_total": cases_total,
        "cases_passed": cases_passed,
        "cases_failed": cases_failed,
        "latency": latency,
        "artifacts_dir": str(profile_out_dir),
        "switch_stdout_tail": switch_stdout[-600:],
        "switch_stderr_tail": switch_stderr[-600:],
        "eval_stdout_tail": eval_result.stdout[-1200:],
        "eval_stderr_tail": eval_result.stderr[-1200:],
        "eval_rc": int(eval_result.returncode),
    }


def cmd_bakeoff(args: argparse.Namespace) -> int:
    models = [item.strip() for item in str(args.models).split(",") if item.strip()]
    if not models:
        raise RuntimeError("at least one model must be provided")
    if len(models) > 1 and not args.model_switch_cmd_template:
        raise RuntimeError(
            "multiple models require --model-switch-cmd-template to apply profile before each run; "
            "example: 'LLM_PRIMARY_MODEL={model} ./onco up --full'"
        )

    case_ids = _parse_case_ids(args.case_ids, default_ids=DEFAULT_BAKEOFF_CASE_IDS)
    out_root = _ensure_dir(Path(args.out_dir).expanduser().resolve())
    run_dir = _ensure_dir(out_root / f"model_bakeoff_run_{_timestamp()}")

    profile_results: list[dict[str, Any]] = []
    for model in models:
        profile = _run_bakeoff_profile(model=model, case_ids=case_ids, args=args, out_dir=run_dir)
        profile_results.append(profile)

    selected = _select_model_profile(profile_results, sla_ms=float(args.sla_ms))
    report = {
        "generated_at": _utc_now().isoformat(),
        "sla_ms": float(args.sla_ms),
        "models_chain": models,
        "selected": selected,
        "profiles": profile_results,
        "case_ids": case_ids,
        "base_url": args.base_url,
        "auth_mode": args.auth_mode,
        "schema_version": args.schema_version,
        "zip": str(Path(args.zip).expanduser().resolve()),
        "xlsx": str(Path(args.xlsx).expanduser().resolve()) if args.xlsx else "",
    }

    report_path = out_root / f"model_bakeoff_{_timestamp()}.json"
    decision_path = out_root / f"model_decision_{_timestamp()}.md"
    _write_json(report_path, report)
    _write_text(decision_path, _build_model_decision_markdown(report))

    print(
        json.dumps(
            {
                "selected_model": selected.get("model"),
                "decision": selected.get("decision"),
                "report": str(report_path),
                "decision_markdown": str(decision_path),
            },
            ensure_ascii=True,
        )
    )

    return 0 if str(selected.get("decision") or "") == "sla_pass" else 1


def cmd_waiver(args: argparse.Namespace) -> int:
    traceability_path = Path(args.traceability_json).expanduser().resolve()
    if not traceability_path.exists():
        raise RuntimeError(f"traceability json not found: {traceability_path}")
    traceability = _load_json_file(traceability_path)
    markdown = _build_demo_waiver_markdown(
        traceability=traceability,
        generated_at=_utc_now().isoformat(),
        remediation_deadline=args.remediation_deadline,
        mitigation=args.mitigation,
    )

    out_dir = _ensure_dir(Path(args.out_dir).expanduser().resolve())
    out_path = out_dir / f"demo_waiver_{_timestamp()}.md"
    _write_text(out_path, markdown)
    print(json.dumps({"waiver": str(out_path)}, ensure_ascii=True))
    return 0


def cmd_go_live_report(args: argparse.Namespace) -> int:
    out_dir = _ensure_dir(Path(args.out_dir).expanduser().resolve())

    readiness_path = Path(args.readiness_report).expanduser().resolve()
    metrics_path = Path(args.latest_metrics).expanduser().resolve()
    bakeoff_path = (
        Path(args.model_bakeoff_report).expanduser().resolve()
        if str(args.model_bakeoff_report or "").strip()
        else None
    )
    connectivity_path = (
        Path(args.connectivity_report).expanduser().resolve()
        if str(args.connectivity_report or "").strip()
        else None
    )

    readiness_payload = _load_json_file(readiness_path) if readiness_path.exists() else {}
    metrics_payload = _load_json_file(metrics_path) if metrics_path.exists() else {}
    bakeoff_payload = (
        _load_json_file(bakeoff_path) if bakeoff_path and bakeoff_path.exists() and bakeoff_path.is_file() else {}
    )
    connectivity_payload = (
        _load_json_file(connectivity_path)
        if connectivity_path and connectivity_path.exists() and connectivity_path.is_file()
        else {}
    )

    selected = bakeoff_payload.get("selected") if isinstance(bakeoff_payload.get("selected"), dict) else {}
    readiness_ok = bool(readiness_payload.get("ok"))
    bakeoff_ok = str(selected.get("decision") or "") == "sla_pass"
    selected_route = str(connectivity_payload.get("selected_route") or "").strip()
    connectivity_ok = bool(selected_route)
    waiver_path_raw = str(args.waiver_path or "").strip()
    waiver_path = Path(waiver_path_raw).expanduser().resolve() if waiver_path_raw else None
    waiver_exists = bool(waiver_path and waiver_path.exists() and waiver_path.is_file())
    waiver_accepted = waiver_exists and str(selected.get("decision") or "") in {
        "no_sla_pass_best_quality",
        "no_quality_pass_fastest_available",
    }

    report = {
        "generated_at": _utc_now().isoformat(),
        "strict_profile": {
            "ONCOAI_RELEASE_PROFILE": os.environ.get("ONCOAI_RELEASE_PROFILE", ""),
            "LLM_GENERATION_ENABLED": os.environ.get("LLM_GENERATION_ENABLED", ""),
            "VECTOR_BACKEND": os.environ.get("VECTOR_BACKEND", ""),
            "EMBEDDING_BACKEND": os.environ.get("EMBEDDING_BACKEND", ""),
            "RERANKER_BACKEND": os.environ.get("RERANKER_BACKEND", ""),
            "SESSION_AUTH_MODE": os.environ.get("SESSION_AUTH_MODE", ""),
            "CASE_IMPORT_ALLOW_FULL_MODE": os.environ.get("CASE_IMPORT_ALLOW_FULL_MODE", ""),
        },
        "readiness": {"path": str(readiness_path), "ok": readiness_ok},
        "latest_metrics": {
            "path": str(metrics_path),
            "p95_ms": metrics_payload.get("latency_p95_ms"),
            "passed_cases": metrics_payload.get("passed_cases"),
        },
        "connectivity": {
            "path": str(connectivity_path) if connectivity_path else "",
            "selected_route": selected_route,
            "ok": connectivity_ok,
        },
        "model_selection": {
            "path": str(bakeoff_path) if bakeoff_path else "",
            "model": selected.get("model"),
            "decision": selected.get("decision"),
            "p95_ms": selected.get("latency", {}).get("p95_ms") if isinstance(selected.get("latency"), dict) else None,
        },
        "waiver_path": str(waiver_path) if waiver_path else "",
        "waiver": {"exists": waiver_exists, "accepted": waiver_accepted},
        "go_live_ready": readiness_ok and connectivity_ok and (bakeoff_ok or waiver_accepted),
    }

    out_path = out_dir / f"prod_go_live_report_{_timestamp()}.json"
    _write_json(out_path, report)
    print(json.dumps({"go_live_ready": report["go_live_ready"], "report": str(out_path)}, ensure_ascii=True))
    return 0 if report["go_live_ready"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OncoAI production release orchestration helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    connectivity = subparsers.add_parser("connectivity", help="Probe native/provider chat+embeddings endpoints")
    connectivity.add_argument(
        "--native-chat-url",
        default=os.environ.get("ONCOAI_NATIVE_CHAT_URL") or _default_chat_url(os.environ.get("LLM_PRIMARY_URL", "")),
    )
    connectivity.add_argument(
        "--native-embeddings-url",
        default=os.environ.get("ONCOAI_NATIVE_EMBEDDINGS_URL")
        or _default_embeddings_url(os.environ.get("EMBEDDING_URL", "")),
    )
    connectivity.add_argument(
        "--native-api-key",
        default=os.environ.get("ONCOAI_NATIVE_API_KEY")
        or os.environ.get("LLM_PRIMARY_API_KEY")
        or os.environ.get("OPENAI_API_KEY", ""),
    )
    connectivity.add_argument(
        "--provider-chat-url",
        default=os.environ.get("ONCOAI_PROVIDER_CHAT_URL", ""),
    )
    connectivity.add_argument(
        "--provider-embeddings-url",
        default=os.environ.get("ONCOAI_PROVIDER_EMBEDDINGS_URL", ""),
    )
    connectivity.add_argument(
        "--provider-api-key",
        default=os.environ.get("ONCOAI_PROVIDER_API_KEY", ""),
    )
    connectivity.add_argument("--chat-model", default=os.environ.get("LLM_PRIMARY_MODEL", "gpt-5.2"))
    connectivity.add_argument("--embedding-model", default=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large"))
    connectivity.add_argument("--timeout-sec", type=int, default=12)
    connectivity.add_argument("--attempts", type=int, default=2)
    connectivity.add_argument("--sleep-between-sec", type=float, default=1.0)
    connectivity.add_argument("--out-dir", default=str(DEFAULT_RELEASE_DIR))

    bakeoff = subparsers.add_parser("bakeoff", help="Run model bakeoff using eval_pdf_pack on pilot cases")
    bakeoff.add_argument("--models", default="gpt-5.2,gpt-4.1,gpt-4.1-mini")
    bakeoff.add_argument("--sla-ms", type=float, default=60000.0)
    bakeoff.add_argument("--zip", default=str(DEFAULT_PDF_PACK_ZIP))
    bakeoff.add_argument("--xlsx", default=str(DEFAULT_PDF_PACK_XLSX))
    bakeoff.add_argument("--base-url", default="http://localhost:3000")
    bakeoff.add_argument("--auth-mode", choices=["auto", "demo", "credentials"], default="demo")
    bakeoff.add_argument("--schema-version", choices=["0.2"], default="0.2")
    bakeoff.add_argument("--case-ids", default="")
    bakeoff.add_argument("--workers", type=int, default=1)
    bakeoff.add_argument("--http-timeout", type=int, default=180)
    bakeoff.add_argument("--eval-timeout-sec", type=int, default=3600)
    bakeoff.add_argument("--switch-timeout-sec", type=int, default=1200)
    bakeoff.add_argument("--eval-script", default=str(ROOT_DIR / "scripts" / "eval_pdf_pack.py"))
    bakeoff.add_argument(
        "--model-switch-cmd-template",
        default="",
        help="Shell command executed before each profile; use {model} placeholder",
    )
    bakeoff.add_argument("--out-dir", default=str(DEFAULT_RELEASE_DIR))

    waiver = subparsers.add_parser("waiver", help="Generate demo waiver from traceability JSON")
    waiver.add_argument("--traceability-json", default=str(DEFAULT_TRACEABILITY_JSON))
    waiver.add_argument("--remediation-deadline", required=True)
    waiver.add_argument(
        "--mitigation",
        default="strict_full fail-closed + credentials auth + DEID-only + manual oncologist review",
    )
    waiver.add_argument("--out-dir", default=str(DEFAULT_RELEASE_DIR))

    go_live = subparsers.add_parser("go-live-report", help="Generate production go-live report")
    go_live.add_argument("--readiness-report", default=str(DEFAULT_READINESS_JSON))
    go_live.add_argument("--latest-metrics", default=str(DEFAULT_LATEST_METRICS_JSON))
    go_live.add_argument("--model-bakeoff-report", default=_latest_release_artifact("model_bakeoff"))
    go_live.add_argument("--connectivity-report", default=_latest_release_artifact("prod_connectivity_report"))
    go_live.add_argument("--waiver-path", default="")
    go_live.add_argument("--out-dir", default=str(DEFAULT_RELEASE_DIR))

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "connectivity":
        return cmd_connectivity(args)
    if args.command == "bakeoff":
        return cmd_bakeoff(args)
    if args.command == "waiver":
        return cmd_waiver(args)
    if args.command == "go-live-report":
        return cmd_go_live_report(args)
    raise RuntimeError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
