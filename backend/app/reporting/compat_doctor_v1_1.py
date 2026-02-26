from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ModuleNotFoundError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[assignment]


_LINE_HINT_PATTERN = re.compile(r"(?:line|линия)\s*[:#-]?\s*(\d{1,2})", re.IGNORECASE)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _external_schema_path() -> Path:
    return _project_root() / "docs" / "contracts" / "external" / "doctor_report_v1_1.schema.json"


@lru_cache(maxsize=1)
def _doctor_schema_validator() -> Any | None:
    if Draft202012Validator is None:
        return None
    schema_path = _external_schema_path()
    if not schema_path.exists():
        return None
    schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _markdown_to_plain(value: str | None, max_length: int = 1200) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\-\*\u2022]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def _infer_cancer_type(
    *,
    disease_context: dict[str, Any],
    run_meta: dict[str, Any] | None,
) -> str:
    routing_meta = run_meta.get("routing_meta") if isinstance(run_meta, dict) else {}
    if isinstance(routing_meta, dict):
        routed = str(routing_meta.get("resolved_cancer_type") or "").strip()
        if routed:
            return routed
    for key in ("cancer_type", "disease_name", "disease_id"):
        value = str(disease_context.get(key) or "").strip()
        if value:
            return value
    icd10 = str(disease_context.get("icd10") or "").strip().upper()
    if icd10.startswith("C16"):
        return "gastric_cancer"
    return "unknown"


def _infer_line_of_therapy(
    *,
    disease_context: dict[str, Any],
    plan: list[dict[str, Any]],
    timeline: list[dict[str, Any] | str],
) -> int | None:
    line_value = disease_context.get("line")
    if isinstance(line_value, int) and line_value >= 0:
        return line_value

    for section in plan:
        if not isinstance(section, dict):
            continue
        steps = section.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "")
            match = _LINE_HINT_PATTERN.search(text)
            if match:
                try:
                    return max(0, int(match.group(1)))
                except ValueError:
                    pass

    for item in timeline:
        text = str(item if isinstance(item, str) else item.get("label") or item.get("details") or "")
        match = _LINE_HINT_PATTERN.search(text)
        if match:
            try:
                return max(0, int(match.group(1)))
            except ValueError:
                pass
    return None


def _build_treatment_history(
    *,
    timeline: list[dict[str, Any] | str],
    case_facts: dict[str, Any],
    line_of_therapy: int | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for event in timeline:
        if isinstance(event, str):
            text = event.strip()
            if not text:
                continue
            items.append({"type": "other", "description": text})
            continue
        if not isinstance(event, dict):
            continue
        raw_type = str(event.get("type") or "").strip().lower()
        mapped_type = "other"
        if raw_type in {"surgery"}:
            mapped_type = "surgery"
        elif raw_type in {"systemic_therapy", "chemotherapy", "targeted", "immunotherapy"}:
            mapped_type = "systemic_therapy"
        elif raw_type in {"radiation", "radiotherapy"}:
            mapped_type = "radiation"
        elif raw_type in {"chemoradiation"}:
            mapped_type = "chemoradiation"

        description = str(event.get("label") or event.get("details") or "").strip()
        if not description:
            continue
        item: dict[str, Any] = {
            "type": mapped_type,
            "description": description,
        }
        date = str(event.get("date") or "").strip()
        if date:
            item["period"] = date
        if line_of_therapy is not None and mapped_type == "systemic_therapy":
            item["line_of_therapy"] = line_of_therapy
        items.append(item)

    history_from_casefacts = case_facts.get("treatment_history")
    if isinstance(history_from_casefacts, list):
        for entry in history_from_casefacts:
            if not isinstance(entry, dict):
                continue
            description = str(entry.get("regimen") or entry.get("event") or entry.get("name") or "").strip()
            if not description:
                continue
            item = {
                "type": "systemic_therapy",
                "description": description,
            }
            line = entry.get("line")
            if isinstance(line, int) and line >= 0:
                item["line_of_therapy"] = line
            outcome = str(entry.get("status") or entry.get("outcome") or "").strip()
            if outcome:
                item["outcome"] = outcome
            items.append(item)

    unique: list[dict[str, Any]] = []
    seen = set()
    for item in items:
        key = (str(item.get("type") or ""), str(item.get("description") or ""), str(item.get("period") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:40]


def _build_current_plan(
    *,
    plan: list[dict[str, Any]],
    line_of_therapy: int | None,
) -> dict[str, Any]:
    treatment_step = ""
    for section in plan:
        if not isinstance(section, dict):
            continue
        if str(section.get("section") or "").strip() != "treatment":
            continue
        steps = section.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "").strip()
            if text:
                treatment_step = text
                break
        if treatment_step:
            break

    payload: dict[str, Any] = {
        "intent": "unknown",
        "description": treatment_step or "Текущий план требует уточнения по данным кейса.",
    }
    if line_of_therapy is not None:
        payload["line_of_therapy"] = line_of_therapy
    return payload


def project_doctor_report_v1_1(
    *,
    doctor_report_v1_2: dict[str, Any],
    run_meta: dict[str, Any] | None,
    insufficient_data: dict[str, Any] | None,
) -> dict[str, Any]:
    disease_context = doctor_report_v1_2.get("disease_context") if isinstance(doctor_report_v1_2.get("disease_context"), dict) else {}
    case_facts = doctor_report_v1_2.get("case_facts") if isinstance(doctor_report_v1_2.get("case_facts"), dict) else {}
    current_stage = case_facts.get("current_stage") if isinstance(case_facts.get("current_stage"), dict) else {}
    timeline = doctor_report_v1_2.get("timeline") if isinstance(doctor_report_v1_2.get("timeline"), list) else []
    plan = doctor_report_v1_2.get("plan") if isinstance(doctor_report_v1_2.get("plan"), list) else []
    issues = doctor_report_v1_2.get("issues") if isinstance(doctor_report_v1_2.get("issues"), list) else []

    line_of_therapy = _infer_line_of_therapy(
        disease_context=disease_context,
        plan=plan,
        timeline=timeline,
    )

    disease_payload: dict[str, Any] = {
        "cancer_type": _infer_cancer_type(disease_context=disease_context, run_meta=run_meta),
        "stage_group": str(disease_context.get("stage_group") or current_stage.get("stage_group") or "").strip() or None,
        "tnm": str(current_stage.get("tnm") or "").strip() or None,
        "setting": (
            str(disease_context.get("setting") or "").strip()
            if str(disease_context.get("setting") or "").strip() in {"localized", "locally_advanced", "metastatic", "recurrent", "unknown"}
            else "unknown"
        ),
        "line_of_therapy": line_of_therapy,
        "biomarkers": (
            disease_context.get("biomarkers")
            if isinstance(disease_context.get("biomarkers"), list)
            else []
        ),
    }
    disease_payload = {key: value for key, value in disease_payload.items() if value is not None}

    compat_issues: list[dict[str, Any]] = []
    missing_data: list[dict[str, str]] = []
    critical = False
    warning = False
    for item in issues:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "info").strip().lower()
        if severity == "critical":
            critical = True
        if severity == "warning":
            warning = True
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        compat_issues.append(
            {
                "issue_id": str(item.get("issue_id") or ""),
                "severity": severity if severity in {"critical", "warning", "info"} else "info",
                "category": str(item.get("kind") or "other").strip() or "other",
                "summary": summary,
                "details": str(item.get("details") or "").strip(),
                "citation_ids": [str(cid) for cid in (item.get("citation_ids") if isinstance(item.get("citation_ids"), list) else [])],
            }
        )
        if str(item.get("kind") or "").strip() == "missing_data":
            missing_data.append(
                {
                    "field": str(item.get("field_path") or "unknown_field"),
                    "reason": str(item.get("details") or summary),
                }
            )

    if isinstance(insufficient_data, dict) and bool(insufficient_data.get("status")):
        missing_data.append(
            {
                "field": "clinical_completeness",
                "reason": str(insufficient_data.get("reason") or "Недостаточно данных для полной оценки."),
            }
        )

    overall_assessment = "compliant"
    if critical:
        overall_assessment = "non_compliant"
    elif warning:
        overall_assessment = "partially_compliant"
    elif missing_data:
        overall_assessment = "cannot_assess"

    projection = {
        "schema_version": "1.1",
        "report_id": str(doctor_report_v1_2.get("report_id") or ""),
        "request_id": str(doctor_report_v1_2.get("request_id") or ""),
        "kb_version": str((run_meta or {}).get("kb_version") or "kb_unknown"),
        "clinical_summary": _markdown_to_plain(doctor_report_v1_2.get("consilium_md")),
        "disease_context": disease_payload,
        "comorbidities": [],
        "treatment_history": _build_treatment_history(
            timeline=timeline,
            case_facts=case_facts,
            line_of_therapy=line_of_therapy,
        ),
        "current_plan": _build_current_plan(
            plan=plan,
            line_of_therapy=line_of_therapy,
        ),
        "overall_assessment": overall_assessment,
        "issues": compat_issues,
        "missing_data": missing_data,
        "run_meta": run_meta or {},
    }
    return projection


def validate_doctor_projection_v1_1(payload: dict[str, Any]) -> list[str]:
    validator = _doctor_schema_validator()
    if validator is None:
        return []
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    return [error.message for error in errors]
