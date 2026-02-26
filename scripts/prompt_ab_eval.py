#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from backend.app.config import load_settings
from backend.app.service import OncoService


ALLOWED_ABBR = {
    "msi",
    "mss",
    "her2",
    "pd",
    "l1",
    "cps",
    "ecog",
    "ct",
    "pet",
    "ctcae",
    "tnm",
    "icd",
    "xelox",
    "capox",
    "folfox",
    "dmmr",
    "paclitaxel",
    "ramucirumab",
    "trastuzumab",
}


def _quality_metrics(response: dict[str, Any]) -> dict[str, Any]:
    doctor_report = response.get("doctor_report") if isinstance(response.get("doctor_report"), dict) else {}
    patient_explain = response.get("patient_explain") if isinstance(response.get("patient_explain"), dict) else {}
    run_meta = response.get("run_meta") if isinstance(response.get("run_meta"), dict) else {}

    summary = str(doctor_report.get("summary") or "")
    consilium = str(doctor_report.get("consilium_md") or "")
    issues = doctor_report.get("issues") if isinstance(doctor_report.get("issues"), list) else []
    plan = doctor_report.get("plan") if isinstance(doctor_report.get("plan"), list) else []

    issue_texts: list[str] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        issue_texts.append(str(item.get("summary") or ""))
        issue_texts.append(str(item.get("details") or ""))
    merged = "\n".join([summary, consilium, *issue_texts]).strip()

    english_tokens = re.findall(r"\b[a-zA-Z]{4,}\b", merged)
    english_noise = [token for token in english_tokens if token.lower() not in ALLOWED_ABBR]
    cyrillic_chars = len(re.findall(r"[А-Яа-яЁё]", merged))
    latin_chars = len(re.findall(r"[A-Za-z]", merged))
    ru_ratio = round(cyrillic_chars / max(1, cyrillic_chars + latin_chars), 4)

    plan_steps = 0
    plan_steps_with_citations = 0
    for section in plan:
        if not isinstance(section, dict):
            continue
        steps = section.get("steps") if isinstance(section.get("steps"), list) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            plan_steps += 1
            citation_ids = step.get("citation_ids") if isinstance(step.get("citation_ids"), list) else []
            if any(str(item).strip() for item in citation_ids):
                plan_steps_with_citations += 1

    detail_lengths = [len(str(item.get("details") or "")) for item in issues if isinstance(item, dict)]
    avg_issue_detail_len = round(sum(detail_lengths) / len(detail_lengths), 1) if detail_lengths else 0.0

    patient_summary = str(patient_explain.get("summary_plain") or patient_explain.get("summary") or "")

    return {
        "doctor_schema_version": doctor_report.get("schema_version"),
        "patient_schema_version": patient_explain.get("schema_version"),
        "report_generation_path": run_meta.get("report_generation_path"),
        "patient_generation_path": run_meta.get("patient_generation_path"),
        "llm_path": run_meta.get("llm_path"),
        "fallback_reason": run_meta.get("fallback_reason"),
        "docs_retrieved_count": run_meta.get("docs_retrieved_count"),
        "docs_after_filter_count": run_meta.get("docs_after_filter_count"),
        "citations_count": run_meta.get("citations_count"),
        "ru_ratio": ru_ratio,
        "english_noise_count": len(english_noise),
        "english_noise_tokens": sorted(set(english_noise))[:80],
        "doctor_summary_len": len(summary),
        "consilium_len": len(consilium),
        "issues_count": len([item for item in issues if isinstance(item, dict)]),
        "avg_issue_detail_len": avg_issue_detail_len,
        "plan_steps": plan_steps,
        "plan_steps_with_citations": plan_steps_with_citations,
        "patient_summary_len": len(patient_summary),
    }


def _run_profile(case_id: str, profile_name: str, profile_env: dict[str, str]) -> dict[str, Any]:
    tracked_env = {
        "LLM_GENERATION_ENABLED",
        "ONCOAI_PROMPT_REGISTRY_DIR",
        "ONCOAI_PROMPT_SCHEMA_STRICT",
        "LLM_PRIMARY_URL",
        "LLM_PRIMARY_MODEL",
        "LLM_PRIMARY_API_KEY",
        "LLM_FALLBACK_URL",
        "LLM_FALLBACK_MODEL",
        "LLM_FALLBACK_API_KEY",
        "LLM_FALLBACK_MAX_TOKENS",
    }
    original = {key: os.environ.get(key) for key in tracked_env}
    try:
        for key, value in profile_env.items():
            os.environ[key] = value
        try:
            settings = load_settings()
            service = OncoService(settings)
            response = service.analyze(
                payload={
                    "schema_version": "0.2",
                    "request_id": str(uuid.uuid4()),
                    "query_type": "NEXT_STEPS",
                    "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
                    "language": "ru",
                    "case": {"case_id": case_id},
                },
                role="clinician",
                client_id=f"prompt-ab-{profile_name}",
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "profile": profile_name,
                "env": profile_env,
                "error": str(exc),
            }
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    return {
        "profile": profile_name,
        "env": profile_env,
        "metrics": _quality_metrics(response),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run prompt effectiveness A/B on a single case.")
    parser.add_argument("--case-id", required=True, help="Case ID stored in DB")
    parser.add_argument("--out", default="/tmp/onco_prompt_ab_eval.json", help="Output JSON path")
    parser.add_argument("--local-fallback-url", default="", help="Local fallback URL (e.g. http://ollama:11434)")
    parser.add_argument("--local-fallback-model", default="qwen2.5:0.5b", help="Local fallback model")
    parser.add_argument("--include-api", action="store_true", help="Include one API profile (economy mode)")
    parser.add_argument("--api-url", default="https://api.openai.com", help="API base URL")
    parser.add_argument("--api-model", default="gpt-4o-mini", help="API model")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Env var name for API key")
    args = parser.parse_args()

    Path("/tmp/onco_empty_prompts").mkdir(parents=True, exist_ok=True)
    prompt_dir_default = "/app/docs/prompts" if Path("/app/docs/prompts").exists() else str((Path.cwd() / "docs" / "prompts").resolve())

    profiles: list[tuple[str, dict[str, str]]] = [(
        "deterministic_baseline",
        {
            "LLM_GENERATION_ENABLED": "0",
            "ONCOAI_PROMPT_REGISTRY_DIR": prompt_dir_default,
            "ONCOAI_PROMPT_SCHEMA_STRICT": "0",
            "LLM_PRIMARY_URL": "",
            "LLM_PRIMARY_MODEL": "",
            "LLM_PRIMARY_API_KEY": "",
            "LLM_FALLBACK_URL": "",
            "LLM_FALLBACK_MODEL": "",
            "LLM_FALLBACK_API_KEY": "",
        },
    )]
    if args.local_fallback_url:
        profiles.extend(
            [
                (
                    "llm_local_no_prompt_files",
                    {
                        "LLM_GENERATION_ENABLED": "1",
                        "ONCOAI_PROMPT_REGISTRY_DIR": "/tmp/onco_empty_prompts",
                        "ONCOAI_PROMPT_SCHEMA_STRICT": "0",
                        "LLM_PRIMARY_URL": "",
                        "LLM_PRIMARY_MODEL": "",
                        "LLM_PRIMARY_API_KEY": "",
                        "LLM_FALLBACK_URL": args.local_fallback_url,
                        "LLM_FALLBACK_MODEL": args.local_fallback_model,
                        "LLM_FALLBACK_API_KEY": "",
                    },
                ),
                (
                    "llm_local_with_prompt_files",
                    {
                        "LLM_GENERATION_ENABLED": "1",
                        "ONCOAI_PROMPT_REGISTRY_DIR": prompt_dir_default,
                        "ONCOAI_PROMPT_SCHEMA_STRICT": "0",
                        "LLM_PRIMARY_URL": "",
                        "LLM_PRIMARY_MODEL": "",
                        "LLM_PRIMARY_API_KEY": "",
                        "LLM_FALLBACK_URL": args.local_fallback_url,
                        "LLM_FALLBACK_MODEL": args.local_fallback_model,
                        "LLM_FALLBACK_API_KEY": "",
                    },
                ),
            ]
        )
    if args.include_api:
        api_key = str(os.getenv(args.api_key_env) or "").strip()
        if api_key:
            profiles.append(
                (
                    "llm_api_with_prompt_files",
                    {
                        "LLM_GENERATION_ENABLED": "1",
                        "ONCOAI_PROMPT_REGISTRY_DIR": prompt_dir_default,
                        "ONCOAI_PROMPT_SCHEMA_STRICT": "0",
                        "LLM_PRIMARY_URL": args.api_url,
                        "LLM_PRIMARY_MODEL": args.api_model,
                        "LLM_PRIMARY_API_KEY": api_key,
                        "LLM_FALLBACK_URL": "",
                        "LLM_FALLBACK_MODEL": "",
                        "LLM_FALLBACK_API_KEY": "",
                    },
                )
            )
        else:
            profiles.append(("llm_api_with_prompt_files_skipped", {"reason": f"missing_env:{args.api_key_env}"}))

    results: list[dict[str, Any]] = []
    for name, env in profiles:
        if name.endswith("_skipped"):
            results.append({"profile": name, "env": env, "skipped": True})
            continue
        results.append(_run_profile(args.case_id, name, env))
    payload = {"case_id": args.case_id, "results": results}

    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
