#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
import statistics
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib import error, request

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9+./-]{2,}")

RU_STOPWORDS = {
    "и",
    "в",
    "во",
    "на",
    "по",
    "для",
    "что",
    "как",
    "при",
    "или",
    "это",
    "без",
    "под",
    "над",
    "не",
    "с",
    "со",
    "из",
    "к",
    "до",
    "от",
    "же",
    "ли",
    "мы",
    "вы",
    "он",
    "она",
    "они",
    "его",
    "ее",
    "их",
    "данные",
    "данных",
    "пациент",
    "пациента",
    "пациентке",
    "пациенту",
    "лечение",
    "терапия",
    "терапии",
    "назначено",
    "назначить",
    "рекомендация",
    "рекомендации",
    "врач",
    "врача",
    "должно",
    "нужно",
    "сделать",
}


@dataclass(frozen=True)
class CaseGroup:
    key: str
    title: str
    zip_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate synthetic gastric DOCX cases against local OncoAI API")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--positive-zip", required=True)
    parser.add_argument("--negative-zip", required=True)
    parser.add_argument("--insufficient-zip", required=True)
    parser.add_argument("--out-dir", default="/tmp/oncoai_qa")
    parser.add_argument("--demo-token", default="demo-token")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--sleep-ms", type=int, default=20)
    return parser.parse_args()


def post_json(
    *,
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout: int,
    demo_token: str,
    client_id: str | None = None,
) -> tuple[int, dict[str, Any], str | None]:
    headers = {
        "Content-Type": "application/json",
        "x-role": "clinician",
        "x-demo-token": demo_token,
    }
    if client_id:
        headers["x-client-id"] = client_id

    req = request.Request(
        url=f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return int(resp.status), parsed if isinstance(parsed, dict) else {"raw": parsed}, None
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            parsed = {"raw": raw[:2000]}
        return int(exc.code), parsed if isinstance(parsed, dict) else {"raw": str(parsed)}, f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return 0, {}, f"network_error:{exc}"


def extract_docx_paragraphs(docx_payload: bytes) -> list[str]:
    with zipfile.ZipFile(BytesIO(docx_payload)) as archive:
        xml_payload = archive.read("word/document.xml")
    root = ET.fromstring(xml_payload)
    paragraphs: list[str] = []
    for node in root.iter(f"{WORD_NS}p"):
        chunks: list[str] = []
        for text_node in node.iter(f"{WORD_NS}t"):
            if text_node.text:
                chunks.append(text_node.text)
        line = "".join(chunks).strip()
        if line:
            paragraphs.append(line)
    return paragraphs


def extract_expected_section(paragraphs: list[str]) -> tuple[str, str, list[str]]:
    lowered = [item.lower() for item in paragraphs]
    start_idx = next((idx for idx, line in enumerate(lowered) if "рекомендация ai-помощника" in line), -1)
    section = paragraphs[start_idx:] if start_idx >= 0 else paragraphs[max(0, len(paragraphs) - 40) :]
    section_lowered = [item.lower() for item in section]

    doctor_start = next((idx for idx, line in enumerate(section_lowered) if "для врача" in line), 0)
    patient_start = next((idx for idx, line in enumerate(section_lowered) if "для пациента" in line), len(section))
    doctor_block = section[doctor_start:patient_start]

    actions: list[str] = []
    doctor_lowered = [item.lower() for item in doctor_block]
    actions_start = next((idx for idx, line in enumerate(doctor_lowered) if "что нужно сделать" in line), -1)
    if actions_start >= 0:
        for line in doctor_block[actions_start + 1 :]:
            normalized = line.lower().strip()
            if normalized.startswith("для пациента"):
                break
            if normalized:
                actions.append(line.strip())

    return "\n".join(section), "\n".join(doctor_block), actions


def tokenize(text: str) -> list[str]:
    return [match.lower() for match in TOKEN_RE.findall(text)]


def keep_keyword(token: str) -> bool:
    if len(token) < 4:
        return False
    if token in RU_STOPWORDS:
        return False
    if token.isdigit():
        return False
    return True


def build_expected_keywords(expected_doctor_text: str, expected_actions: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for token in tokenize("\n".join(expected_actions)):
        if not keep_keyword(token) or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    for token in tokenize(expected_doctor_text):
        if not keep_keyword(token) or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered[:30]


def describe_behavior(
    *,
    group_key: str,
    issue_kinds: set[str],
    issue_severities: set[str],
    plan_steps_count: int,
    citations_count: int,
    insufficient_status: bool,
    consilium_md: str,
) -> tuple[bool, str]:
    consilium_lower = consilium_md.lower()
    has_missing_signal = (
        insufficient_status
        or ("missing_data" in issue_kinds)
        or ("не найдено в предоставленных рекомендациях" in consilium_lower)
        or ("дефицит данных" in consilium_lower)
    )

    if group_key == "positive":
        ok = plan_steps_count > 0 and citations_count > 0 and "critical" not in issue_severities
        reason = (
            "ожидаемо: структурный план + цитаты без критических флагов"
            if ok
            else "неожиданно: нет плана/цитат или есть критические флаги"
        )
        return ok, reason

    if group_key == "negative":
        has_concern_signal = bool(
            issue_kinds.intersection({"deviation", "contraindication", "inconsistency", "missing_data"})
            or issue_severities.intersection({"critical", "warning"})
        )
        reason = (
            "ожидаемо: система подняла флаги по несоответствию"
            if has_concern_signal
            else "неожиданно: система не выявила явные несоответствия"
        )
        return has_concern_signal, reason

    # insufficient
    reason = (
        "ожидаемо: система обозначила недостаточность данных/ограничение доказательств"
        if has_missing_signal
        else "неожиданно: нет явного сигнала о недостаточности данных"
    )
    return has_missing_signal, reason


def evaluate_case(
    *,
    base_url: str,
    demo_token: str,
    timeout: int,
    group: CaseGroup,
    file_name: str,
    file_payload: bytes,
    sleep_ms: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    paragraphs = extract_docx_paragraphs(file_payload)
    expected_tail, expected_doctor_text, expected_actions = extract_expected_section(paragraphs)
    expected_keywords = build_expected_keywords(expected_doctor_text, expected_actions)

    import_payload = {
        "filename": Path(file_name).name,
        "content_base64": base64.b64encode(file_payload).decode("ascii"),
    }
    import_status, import_response, import_error = post_json(
        base_url=base_url,
        path="/case/import-file-base64",
        payload=import_payload,
        timeout=timeout,
        demo_token=demo_token,
    )
    case_id = str(import_response.get("case_id") or "")
    import_ok = import_status == 200 and bool(case_id)

    analyze_status = 0
    analyze_error: str | None = None
    analyze_response: dict[str, Any] = {}
    if import_ok:
        analyze_payload = {
            "schema_version": "0.2",
            "request_id": str(uuid.uuid4()),
            "query_type": "NEXT_STEPS",
            "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
            "language": "ru",
            "case": {"case_id": case_id},
        }
        analyze_status, analyze_response, analyze_error = post_json(
            base_url=base_url,
            path="/analyze",
            payload=analyze_payload,
            timeout=timeout,
            demo_token=demo_token,
            client_id=f"synthetic-eval-{uuid.uuid4()}",
        )
        if sleep_ms > 0:
            time.sleep(float(sleep_ms) / 1000.0)

    doctor_report = analyze_response.get("doctor_report") if isinstance(analyze_response, dict) else {}
    doctor_report = doctor_report if isinstance(doctor_report, dict) else {}
    issues = doctor_report.get("issues") if isinstance(doctor_report.get("issues"), list) else []
    issue_kinds = {str(item.get("kind") or "") for item in issues if isinstance(item, dict)}
    issue_severities = {str(item.get("severity") or "") for item in issues if isinstance(item, dict)}
    consilium_md = str(doctor_report.get("consilium_md") or "")
    plan_sections = doctor_report.get("plan") if isinstance(doctor_report.get("plan"), list) else []
    plan_steps: list[str] = []
    for section in plan_sections:
        if not isinstance(section, dict):
            continue
        steps = section.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "").strip()
            if text:
                plan_steps.append(text)
    citations_count = len(doctor_report.get("citations") or []) if isinstance(doctor_report.get("citations"), list) else 0
    insufficient = analyze_response.get("insufficient_data") if isinstance(analyze_response, dict) else {}
    insufficient_status = bool(insufficient.get("status")) if isinstance(insufficient, dict) else False
    issue_lines = [
        str(item.get("summary") or "")
        for item in issues
        if isinstance(item, dict) and str(item.get("summary") or "").strip()
    ]
    actual_text = "\n".join([consilium_md, *plan_steps, *issue_lines]).strip()

    actual_tokens = set(tokenize(actual_text))
    matched_keywords = [token for token in expected_keywords if token in actual_tokens]
    keyword_coverage = (len(matched_keywords) / len(expected_keywords)) if expected_keywords else 0.0

    behavior_ok, behavior_reason = describe_behavior(
        group_key=group.key,
        issue_kinds=issue_kinds,
        issue_severities=issue_severities,
        plan_steps_count=len(plan_steps),
        citations_count=citations_count,
        insufficient_status=insufficient_status,
        consilium_md=consilium_md,
    )
    semantic_ok = keyword_coverage >= 0.08 or len(matched_keywords) >= 3 or len(expected_keywords) < 6
    overall_ok = import_ok and (analyze_status == 200) and behavior_ok and semantic_ok

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return {
        "group": group.key,
        "group_title": group.title,
        "file_name": file_name,
        "paragraphs_count": len(paragraphs),
        "expected_tail_present": "рекомендация ai-помощника" in expected_tail.lower(),
        "expected_actions_count": len(expected_actions),
        "expected_keywords": expected_keywords,
        "matched_keywords": matched_keywords,
        "keyword_coverage": round(keyword_coverage, 4),
        "import_status_code": import_status,
        "import_status": str(import_response.get("status") or ""),
        "import_error": import_error,
        "analyze_status_code": analyze_status,
        "analyze_error": analyze_error,
        "doctor_schema_version": str(doctor_report.get("schema_version") or ""),
        "issues_count": len(issues),
        "issue_kinds": sorted([kind for kind in issue_kinds if kind]),
        "issue_severities": sorted([sev for sev in issue_severities if sev]),
        "plan_steps_count": len(plan_steps),
        "citations_count": citations_count,
        "insufficient_data_status": insufficient_status,
        "behavior_ok": behavior_ok,
        "behavior_reason": behavior_reason,
        "semantic_ok": semantic_ok,
        "overall_ok": overall_ok,
        "elapsed_ms": elapsed_ms,
        "expected_tail_excerpt": expected_tail[:1500],
        "actual_excerpt": actual_text[:1500],
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_group[str(row.get("group") or "unknown")].append(row)

    summary_groups: dict[str, Any] = {}
    for group_key, group_rows in by_group.items():
        coverages = [float(item.get("keyword_coverage") or 0.0) for item in group_rows]
        summary_groups[group_key] = {
            "total": len(group_rows),
            "import_ok": sum(1 for item in group_rows if int(item.get("import_status_code") or 0) == 200),
            "analyze_ok": sum(1 for item in group_rows if int(item.get("analyze_status_code") or 0) == 200),
            "behavior_ok": sum(1 for item in group_rows if bool(item.get("behavior_ok"))),
            "semantic_ok": sum(1 for item in group_rows if bool(item.get("semantic_ok"))),
            "overall_ok": sum(1 for item in group_rows if bool(item.get("overall_ok"))),
            "coverage_avg": round(sum(coverages) / len(coverages), 4) if coverages else 0.0,
            "coverage_median": round(statistics.median(coverages), 4) if coverages else 0.0,
            "elapsed_ms_avg": round(sum(float(item.get("elapsed_ms") or 0.0) for item in group_rows) / len(group_rows), 2),
        }

    coverages_all = [float(item.get("keyword_coverage") or 0.0) for item in rows]
    return {
        "total_cases": len(rows),
        "import_ok": sum(1 for item in rows if int(item.get("import_status_code") or 0) == 200),
        "analyze_ok": sum(1 for item in rows if int(item.get("analyze_status_code") or 0) == 200),
        "behavior_ok": sum(1 for item in rows if bool(item.get("behavior_ok"))),
        "semantic_ok": sum(1 for item in rows if bool(item.get("semantic_ok"))),
        "overall_ok": sum(1 for item in rows if bool(item.get("overall_ok"))),
        "coverage_avg": round(sum(coverages_all) / len(coverages_all), 4) if coverages_all else 0.0,
        "coverage_median": round(statistics.median(coverages_all), 4) if coverages_all else 0.0,
        "groups": summary_groups,
    }


def write_markdown_report(
    *,
    out_path: Path,
    started_at: str,
    finished_at: str,
    base_url: str,
    groups: list[CaseGroup],
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    lines.append("# Отчёт по синтетическим историям болезни (рак желудка)")
    lines.append("")
    lines.append(f"- Время запуска: `{started_at}`")
    lines.append(f"- Время завершения: `{finished_at}`")
    lines.append(f"- API база: `{base_url}`")
    lines.append("- Режим: импорт файла (`/case/import-file-base64`) + анализ (`/analyze`).")
    lines.append("")
    lines.append("## Набор данных")
    for group in groups:
        lines.append(f"- `{group.title}`: `{group.zip_path}`")
    lines.append("")
    lines.append("## Сводка")
    lines.append("")
    lines.append("| Метрика | Значение |")
    lines.append("|---|---:|")
    lines.append(f"| Total cases | {summary['total_cases']} |")
    lines.append(f"| Import OK | {summary['import_ok']} |")
    lines.append(f"| Analyze OK | {summary['analyze_ok']} |")
    lines.append(f"| Behavior OK | {summary['behavior_ok']} |")
    lines.append(f"| Semantic OK | {summary['semantic_ok']} |")
    lines.append(f"| Overall OK | {summary['overall_ok']} |")
    lines.append(f"| Avg keyword coverage | {summary['coverage_avg']:.4f} |")
    lines.append(f"| Median keyword coverage | {summary['coverage_median']:.4f} |")
    lines.append("")
    lines.append("## По группам")
    lines.append("")
    lines.append("| Группа | Total | Import OK | Analyze OK | Behavior OK | Semantic OK | Overall OK | Avg coverage | Median coverage | Avg latency ms |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("positive", "negative", "insufficient"):
        group_summary = summary["groups"].get(key, {})
        lines.append(
            "| {key} | {total} | {import_ok} | {analyze_ok} | {behavior_ok} | {semantic_ok} | {overall_ok} | {cov_avg:.4f} | {cov_med:.4f} | {lat:.2f} |".format(
                key=key,
                total=int(group_summary.get("total", 0)),
                import_ok=int(group_summary.get("import_ok", 0)),
                analyze_ok=int(group_summary.get("analyze_ok", 0)),
                behavior_ok=int(group_summary.get("behavior_ok", 0)),
                semantic_ok=int(group_summary.get("semantic_ok", 0)),
                overall_ok=int(group_summary.get("overall_ok", 0)),
                cov_avg=float(group_summary.get("coverage_avg", 0.0)),
                cov_med=float(group_summary.get("coverage_median", 0.0)),
                lat=float(group_summary.get("elapsed_ms_avg", 0.0)),
            )
        )
    lines.append("")

    failures = sorted(
        [row for row in rows if not bool(row.get("overall_ok"))],
        key=lambda item: (int(item.get("analyze_status_code") != 200), float(item.get("keyword_coverage") or 0.0)),
    )
    lines.append("## Примеры кейсов с наибольшим расхождением")
    if not failures:
        lines.append("")
        lines.append("Существенных провалов не зафиксировано.")
    else:
        for idx, row in enumerate(failures[:12], start=1):
            lines.append("")
            lines.append(f"### {idx}. `{row['group']}` / `{row['file_name']}`")
            lines.append(f"- Import status: `{row['import_status_code']}` `{row['import_status']}`")
            lines.append(f"- Analyze status: `{row['analyze_status_code']}`")
            lines.append(f"- Behavior OK: `{row['behavior_ok']}` ({row['behavior_reason']})")
            lines.append(f"- Semantic OK: `{row['semantic_ok']}`; coverage=`{row['keyword_coverage']}`")
            lines.append(f"- Issue kinds: `{', '.join(row.get('issue_kinds', []))}`")
            lines.append("")
            lines.append("Ожидаемый фрагмент:")
            lines.append("```text")
            lines.append(str(row.get("expected_tail_excerpt") or "")[:900])
            lines.append("```")
            lines.append("Фактический фрагмент:")
            lines.append("```text")
            lines.append(str(row.get("actual_excerpt") or "")[:900])
            lines.append("```")

    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    started_at = datetime.now(timezone.utc).isoformat()

    groups = [
        CaseGroup("positive", "Положительные", Path(args.positive_zip)),
        CaseGroup("negative", "Отрицательные", Path(args.negative_zip)),
        CaseGroup("insufficient", "Недостаточность информации", Path(args.insufficient_zip)),
    ]
    for group in groups:
        if not group.zip_path.exists():
            raise SystemExit(f"Missing zip: {group.zip_path}")

    all_rows: list[dict[str, Any]] = []
    for group in groups:
        with zipfile.ZipFile(group.zip_path) as archive:
            names = sorted([name for name in archive.namelist() if name.lower().endswith(".docx")])
            for name in names:
                payload = archive.read(name)
                row = evaluate_case(
                    base_url=args.base_url,
                    demo_token=args.demo_token,
                    timeout=args.timeout,
                    group=group,
                    file_name=name,
                    file_payload=payload,
                    sleep_ms=max(0, int(args.sleep_ms)),
                )
                all_rows.append(row)

    summary = aggregate(all_rows)
    finished_at = datetime.now(timezone.utc).isoformat()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"gastric_synthetic_eval_{stamp}.json"
    md_path = out_dir / f"gastric_synthetic_eval_{stamp}.md"

    payload = {
        "started_at": started_at,
        "finished_at": finished_at,
        "base_url": args.base_url,
        "inputs": {group.key: str(group.zip_path) for group in groups},
        "summary": summary,
        "cases": all_rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(
        out_path=md_path,
        started_at=started_at,
        finished_at=finished_at,
        base_url=args.base_url,
        groups=groups,
        summary=summary,
        rows=all_rows,
    )

    print(json.dumps({"json_report": str(json_path), "md_report": str(md_path), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
