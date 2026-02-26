from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.app.llm.provider_router import LLMProviderRouter
from backend.app.llm.prompt_registry import PromptRegistry
from backend.app.llm.prompt_schema_guard import guard_and_normalize_system_prompt
from backend.app.llm.schemas_strict import PatientExplainLLMStrict


SAFETY_DISCLAIMER = (
    "Этот текст носит справочный характер и не заменяет консультацию врача. "
    "Он не является назначением или изменением лечения."
)

PATIENT_EXPLAIN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "questions_to_ask_doctor": {"type": "array", "items": {"type": "string"}},
        "safety_disclaimer": {"type": "string"},
    },
    "required": ["summary", "key_points", "questions_to_ask_doctor", "safety_disclaimer"],
    "additionalProperties": False,
}


def _text_char_profile(value: str) -> tuple[int, int]:
    text = str(value or "")
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return cyrillic, latin


def _is_ru_text_compatible(value: str, *, max_latin_without_cyr: int = 8) -> bool:
    cyrillic, latin = _text_char_profile(value)
    if cyrillic >= 2:
        return True
    return latin <= max_latin_without_cyr


def _is_ollama_fallback_only_router(llm_router: LLMProviderRouter) -> bool:
    fallback_url = str(getattr(llm_router.fallback, "url", "") or "").lower()
    return (
        llm_router.primary is None
        and llm_router.fallback is not None
        and ("ollama" in fallback_url or ":11434" in fallback_url)
    )


def _collect_plan_steps(doctor_report: dict[str, Any], *, limit: int = 5) -> list[str]:
    out: list[str] = []
    plan = doctor_report.get("plan")
    if isinstance(plan, list):
        for section in plan:
            if not isinstance(section, dict):
                continue
            steps = section.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                text = str(step.get("text") or "").strip()
                if not text:
                    continue
                out.append(text)
                if len(out) >= limit:
                    return out

    current_plan = doctor_report.get("current_plan")
    if isinstance(current_plan, list):
        for item in current_plan:
            if not isinstance(item, dict):
                continue
            text = str(item.get("name") or item.get("step") or item.get("text") or "").strip()
            if not text:
                continue
            out.append(text)
            if len(out) >= limit:
                return out
    return out


def _collect_timeline_lines(doctor_report: dict[str, Any], *, limit: int = 4) -> list[str]:
    out: list[str] = []
    timeline = doctor_report.get("timeline")
    if not isinstance(timeline, list):
        return out
    for item in timeline:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("details") or "").strip()
        if not label:
            continue
        date = str(item.get("date") or "").strip()
        out.append(f"{date}: {label}" if date else label)
        if len(out) >= limit:
            break
    return out


def _collect_biomarker_summary(doctor_report: dict[str, Any]) -> str:
    disease_context = doctor_report.get("disease_context") if isinstance(doctor_report.get("disease_context"), dict) else {}
    case_facts = doctor_report.get("case_facts") if isinstance(doctor_report.get("case_facts"), dict) else {}
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    parts: list[str] = []

    her2 = str(biomarkers.get("her2") or "").strip()
    if her2:
        parts.append(f"HER2 {her2}")

    cps_values = biomarkers.get("pd_l1_cps_values") if isinstance(biomarkers.get("pd_l1_cps_values"), list) else []
    cps_text = ", ".join(str(item) for item in cps_values if str(item).strip())
    if cps_text:
        parts.append(f"PD-L1 CPS {cps_text}")

    msi = str(biomarkers.get("msi_status") or "").strip()
    if msi:
        parts.append(f"MSI {msi}")

    if not parts and isinstance(disease_context.get("biomarkers"), list):
        for item in disease_context.get("biomarkers", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "").strip()
            if name and value:
                parts.append(f"{name} {value}")
            if len(parts) >= 3:
                break

    return "; ".join(parts)


def _collect_sources_and_docs(doctor_report: dict[str, Any]) -> tuple[list[str], list[str]]:
    source_set: set[str] = set()
    doc_set: set[str] = set()

    citations = doctor_report.get("citations")
    if isinstance(citations, list):
        for item in citations:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source_id") or item.get("source_set") or "").strip().lower()
            doc_id = str(item.get("document_id") or item.get("doc_id") or "").strip()
            if source:
                source_set.add(source)
            if doc_id:
                doc_set.add(doc_id)

    issues = doctor_report.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            for evidence in issue.get("evidence", []):
                if not isinstance(evidence, dict):
                    continue
                source = str(evidence.get("source_set") or evidence.get("source_id") or "").strip().lower()
                doc_id = str(evidence.get("doc_id") or evidence.get("document_id") or "").strip()
                if source:
                    source_set.add(source)
                if doc_id:
                    doc_set.add(doc_id)

    return sorted(source_set), sorted(doc_set)


def _stage_text(doctor_report: dict[str, Any]) -> str:
    disease_context = doctor_report.get("disease_context") if isinstance(doctor_report.get("disease_context"), dict) else {}
    case_facts = doctor_report.get("case_facts") if isinstance(doctor_report.get("case_facts"), dict) else {}
    stage_group = str(disease_context.get("stage_group") or "").strip()
    current_stage = case_facts.get("current_stage") if isinstance(case_facts.get("current_stage"), dict) else {}
    tnm = str(current_stage.get("tnm") or "").strip()
    if stage_group and tnm:
        return f"{stage_group} ({tnm})"
    return tnm or stage_group


def build_patient_explain_strict(doctor_report: dict[str, Any]) -> PatientExplainLLMStrict:
    issues = doctor_report.get("issues") if isinstance(doctor_report.get("issues"), list) else []
    issue_count = len([item for item in issues if isinstance(item, dict)])
    critical_count = len(
        [
            item
            for item in issues
            if isinstance(item, dict) and str(item.get("severity") or "").strip().lower() in {"critical", "error", "fail"}
        ]
    )
    warning_count = len(
        [
            item
            for item in issues
            if isinstance(item, dict) and str(item.get("severity") or "").strip().lower() in {"warning", "warn", "important"}
        ]
    )
    missing_data = len(
        [
            item
            for item in issues
            if isinstance(item, dict) and str(item.get("kind") or "").strip().lower() == "missing_data"
        ]
    )

    stage_text = _stage_text(doctor_report)
    biomarker_summary = _collect_biomarker_summary(doctor_report)
    plan_steps = _collect_plan_steps(doctor_report, limit=4)

    summary_parts: list[str] = []
    if stage_text:
        summary_parts.append(f"По загруженным данным заболевание соответствует стадии {stage_text}.")
    else:
        summary_parts.append("По загруженным данным стадия заболевания требует уточнения.")
    if critical_count > 0:
        summary_parts.append(
            f"Выявлено {critical_count} клинически значимый(ых) вопрос(ов), который важно обсудить с лечащим врачом в ближайшее время."
        )
    elif warning_count > 0:
        summary_parts.append(
            f"Выявлено {warning_count} момент(а), которые желательно дополнительно обсудить с лечащим врачом."
        )
    elif issue_count > 0:
        summary_parts.append(
            f"Система отметила {issue_count} пункт(а) для обсуждения с лечащим врачом."
        )
    else:
        summary_parts.append("Критических расхождений в текущем разборе не выявлено.")
    if missing_data > 0:
        summary_parts.append("Для окончательного выбора следующего этапа лечения нужно дополнить часть клинических данных.")
    if biomarker_summary:
        summary_parts.append(f"Ключевые биомаркеры в кейсе: {biomarker_summary}.")
    summary_parts.append("Окончательное решение по лечению принимает лечащий врач на очной консультации.")
    summary = " ".join(summary_parts)

    key_points: list[str] = []
    for step in plan_steps[:3]:
        key_points.append(f"К обсуждению на приёме: {step}.")
    if biomarker_summary:
        key_points.append(f"В анализе учтены биомаркеры: {biomarker_summary}.")
    first_issue = next(
        (
            str(item.get("summary") or "").strip()
            for item in issues
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ),
        "",
    )
    if first_issue:
        key_points.append(f"Требует уточнения: {first_issue}.")
    if not key_points:
        key_points = [
            "Проверка выполнена по клиническим рекомендациям, доступным в базе знаний.",
            "Результат учитывает полноту введенных данных, поэтому точность зависит от деталей случая.",
        ]

    questions = [
        "Какие данные нужно дополнить, чтобы окончательно выбрать следующий этап лечения?",
        "Какие риски и побочные эффекты наиболее важны в моей текущей ситуации?",
    ]
    if plan_steps:
        questions.append("Какой следующий шаг лечения приоритетен и почему?")
    if missing_data > 0:
        questions.insert(0, "Какие анализы и обследования нужно выполнить в первую очередь?")

    return {
        "schema_version": "0.2",
        "kb_version": str(doctor_report.get("kb_version") or doctor_report.get("schema_version") or "unknown"),
        "based_on_report_id": str(doctor_report.get("report_id") or doctor_report.get("request_id") or "unknown_report"),
        "summary": summary,
        "key_points": key_points[:6],
        "questions_to_ask_doctor": questions[:6],
        "safety_disclaimer": SAFETY_DISCLAIMER,
    }


def _build_prompt(doctor_report: dict[str, Any]) -> str:
    stage_text = _stage_text(doctor_report)
    biomarker_summary = _collect_biomarker_summary(doctor_report)
    plan_steps = _collect_plan_steps(doctor_report, limit=6)
    timeline_lines = _collect_timeline_lines(doctor_report, limit=5)
    issues = doctor_report.get("issues") if isinstance(doctor_report.get("issues"), list) else []
    compact_issues = [
        {
            "severity": str(item.get("severity") or "").strip(),
            "kind": str(item.get("kind") or "").strip(),
            "summary": str(item.get("summary") or item.get("title") or "").strip(),
            "details": str(item.get("details") or item.get("description") or "").strip(),
        }
        for item in issues
        if isinstance(item, dict)
    ][:8]
    sources_used, docs_used = _collect_sources_and_docs(doctor_report)

    disease_context = doctor_report.get("disease_context") if isinstance(doctor_report.get("disease_context"), dict) else {}
    case_facts = doctor_report.get("case_facts") if isinstance(doctor_report.get("case_facts"), dict) else {}
    current_stage = case_facts.get("current_stage") if isinstance(case_facts.get("current_stage"), dict) else {}
    insufficient_data = (
        doctor_report.get("insufficient_data")
        if isinstance(doctor_report.get("insufficient_data"), dict)
        else {}
    )
    compact_report = {
        "report_id": doctor_report.get("report_id"),
        "request_id": doctor_report.get("request_id"),
        "query_type": doctor_report.get("query_type"),
        "kb_version": doctor_report.get("kb_version"),
        "summary": doctor_report.get("summary"),
        "stage_text": stage_text,
        "biomarker_summary": biomarker_summary,
        "disease_context": {
            "icd10": disease_context.get("icd10"),
            "setting": disease_context.get("setting"),
            "line": disease_context.get("line"),
        },
        "case_facts": {
            "current_stage_tnm": current_stage.get("tnm"),
            "current_stage_group": current_stage.get("stage_group"),
        },
        "plan_steps": plan_steps,
        "timeline": timeline_lines,
        "issues": compact_issues,
        "issue_count": len(compact_issues),
        "drug_safety": doctor_report.get("drug_safety") if isinstance(doctor_report.get("drug_safety"), dict) else {},
        "missing_data": doctor_report.get("missing_data", []),
        "insufficient_data": {
            "status": bool(insufficient_data.get("status")),
            "reason": str(insufficient_data.get("reason") or "").strip(),
        },
        "sources_used": sources_used,
        "docs_used": docs_used,
    }
    return (
        "Сформируй patient-safe объяснение строго в формате JSON на русском языке.\n"
        "Не добавляй фактов, которых нет во входных данных. Не предлагай назначения и не давай прогноз.\n"
        "Верни только объект с ключами:\n"
        "summary, key_points(array), questions_to_ask_doctor(array), safety_disclaimer.\n"
        "Требования: summary = 4-8 предложений, связный русский текст; английские аббревиатуры допустимы только для медицинских маркеров.\n"
        "Если данных недостаточно — явно и спокойно укажи, какие данные нужно уточнить до окончательного решения.\n"
        f"doctor_report_compact={json.dumps(compact_report, ensure_ascii=False)}\n"
    )


def _build_local_rescue_prompt(doctor_report: dict[str, Any]) -> str:
    stage_text = _stage_text(doctor_report)
    biomarker_summary = _collect_biomarker_summary(doctor_report)
    plan_steps = _collect_plan_steps(doctor_report, limit=3)
    timeline_lines = _collect_timeline_lines(doctor_report, limit=3)
    issues = doctor_report.get("issues") if isinstance(doctor_report.get("issues"), list) else []
    issue_lines = [
        str(item.get("summary") or item.get("title") or "").strip()
        for item in issues
        if isinstance(item, dict) and str(item.get("summary") or item.get("title") or "").strip()
    ][:3]
    compact = {
        "report_id": doctor_report.get("report_id"),
        "stage": stage_text,
        "biomarkers": biomarker_summary,
        "plan_steps": plan_steps,
        "timeline": timeline_lines,
        "issues": issue_lines,
    }
    return (
        "Верни только JSON без markdown.\n"
        "Ключи: summary, key_points, questions_to_ask_doctor, safety_disclaimer.\n"
        "Текст на русском, связный, patient-safe, без назначений.\n"
        f"doctor_report_compact={json.dumps(compact, ensure_ascii=False)}\n"
    )


def _coerce_llm_payload(
    payload: dict[str, Any] | None,
    fallback: PatientExplainLLMStrict,
    doctor_report: dict[str, Any],
) -> PatientExplainLLMStrict | None:
    if not isinstance(payload, dict):
        return None
    raw_text = str(payload.get("_raw_text") or "").strip()
    if raw_text and len(raw_text) >= 20:
        lines = [line.strip(" -\t") for line in raw_text.splitlines() if line.strip()]
        def _is_human_summary_line(line: str) -> bool:
            candidate = line.strip()
            if len(candidate) < 24:
                return False
            if candidate[0] in {'{', '[', '"', "'", "}"}:
                return False
            lowered = candidate.lower()
            if lowered.startswith(
                (
                    "summary",
                    "key_points",
                    "questions_to_ask_doctor",
                    "questions_for_doctor",
                    "safety_disclaimer",
                    "schema_version",
                    "kb_version",
                    "based_on_report_id",
                )
            ):
                return False
            return True

        summary_candidate = next((line for line in lines if _is_human_summary_line(line)), "")
        if summary_candidate and not _is_ru_text_compatible(summary_candidate, max_latin_without_cyr=8):
            summary_candidate = ""
        key_points_from_raw = [
            line
            for line in lines
            if len(line) >= 12
            and not line.startswith(("{", "[", "]", "}"))
            and not re.match(r"^[\"']?[A-Za-z_]+[\"']?\s*:", line)
            and _is_ru_text_compatible(line, max_latin_without_cyr=14)
        ][:3]
        payload = {
            "summary": summary_candidate or fallback["summary"],
            "key_points": key_points_from_raw or fallback["key_points"],
            "questions_to_ask_doctor": fallback["questions_to_ask_doctor"],
            "safety_disclaimer": fallback["safety_disclaimer"],
        }

    summary = str(payload.get("summary") or payload.get("summary_plain") or "").strip()
    if not summary:
        key_points_candidate = payload.get("key_points")
        if isinstance(key_points_candidate, list):
            summary = next(
                (
                    str(item).strip()
                    for item in key_points_candidate
                    if str(item).strip() and len(str(item).strip()) >= 12
                ),
                "",
            )
    if not summary:
        summary = fallback["summary"]
    if not _is_ru_text_compatible(summary, max_latin_without_cyr=8):
        summary = fallback["summary"]
    raw_key_points = payload.get("key_points")
    raw_questions = payload.get("questions_to_ask_doctor")
    if raw_questions is None:
        raw_questions = payload.get("questions_for_doctor")

    if isinstance(raw_key_points, str):
        raw_key_points = [raw_key_points]
    if isinstance(raw_questions, str):
        raw_questions = [raw_questions]
    if not isinstance(raw_key_points, list):
        raw_key_points = fallback["key_points"]
    if not isinstance(raw_questions, list):
        raw_questions = fallback["questions_to_ask_doctor"]

    key_points = [
        str(item).strip()
        for item in raw_key_points
        if str(item).strip()
        and len(str(item).strip()) >= 6
        and _is_ru_text_compatible(str(item).strip(), max_latin_without_cyr=14)
    ]
    questions = [
        str(item).strip()
        for item in raw_questions
        if str(item).strip()
        and len(str(item).strip()) >= 6
        and _is_ru_text_compatible(str(item).strip(), max_latin_without_cyr=14)
    ]
    if not key_points or not questions:
        key_points = key_points or fallback["key_points"]
        questions = questions or fallback["questions_to_ask_doctor"]

    safety_disclaimer = str(
        payload.get("safety_disclaimer")
        or payload.get("safety_note")
        or payload.get("disclaimer")
        or ""
    ).strip() or fallback["safety_disclaimer"]
    if not _is_ru_text_compatible(safety_disclaimer, max_latin_without_cyr=20):
        safety_disclaimer = fallback["safety_disclaimer"]
    return {
        "schema_version": "0.2",
        "kb_version": str(doctor_report.get("kb_version", fallback["kb_version"])),
        "based_on_report_id": str(doctor_report.get("report_id", fallback["based_on_report_id"])),
        "summary": summary,
        "key_points": key_points[:6],
        "questions_to_ask_doctor": questions[:6],
        "safety_disclaimer": safety_disclaimer,
    }


def _validate_llm_payload_without_coercion(
    payload: dict[str, Any] | None,
    *,
    doctor_report: dict[str, Any],
    fallback: PatientExplainLLMStrict,
) -> PatientExplainLLMStrict | None:
    if not isinstance(payload, dict):
        return None
    summary = str(payload.get("summary") or "").strip()
    raw_key_points = payload.get("key_points")
    raw_questions = payload.get("questions_to_ask_doctor")
    safety_disclaimer = str(payload.get("safety_disclaimer") or "").strip()
    if not summary or not safety_disclaimer:
        return None
    if not isinstance(raw_key_points, list) or not isinstance(raw_questions, list):
        return None

    key_points = [str(item).strip() for item in raw_key_points if str(item).strip()]
    questions = [str(item).strip() for item in raw_questions if str(item).strip()]
    if not key_points or not questions:
        return None

    return {
        "schema_version": "0.2",
        "kb_version": str(doctor_report.get("kb_version", fallback["kb_version"])),
        "based_on_report_id": str(doctor_report.get("report_id", fallback["based_on_report_id"])),
        "summary": summary,
        "key_points": key_points[:6],
        "questions_to_ask_doctor": questions[:6],
        "safety_disclaimer": safety_disclaimer,
    }


def _resolve_system_prompt(
    *,
    prompt_registry: PromptRegistry | None,
    prompt_schema_strict: bool,
) -> str | None:
    if prompt_registry is None:
        return None
    prompt_key = "patient_explain_v1_1_system_prompt"
    if prompt_schema_strict:
        prompt_text = prompt_registry.load(prompt_key)
    else:
        prompt_text = prompt_registry.load_optional(prompt_key)
        if not prompt_text:
            return None
    return guard_and_normalize_system_prompt(
        prompt_key=prompt_key,
        prompt_text=prompt_text,
        output_schema=PATIENT_EXPLAIN_OUTPUT_SCHEMA,
        strict_mode=prompt_schema_strict,
    )


def build_patient_explain_with_fallback(
    doctor_report: dict[str, Any],
    llm_router: LLMProviderRouter,
    prompt_registry: PromptRegistry | None = None,
    prompt_schema_strict: bool = False,
    *,
    strict_llm_only: bool = False,
) -> tuple[PatientExplainLLMStrict, str]:
    fallback = build_patient_explain_strict(doctor_report)
    if not (llm_router.primary or llm_router.fallback):
        if strict_llm_only:
            raise RuntimeError("llm_rag_only requires primary LLM provider")
        return fallback, "deterministic"
    effective_router = llm_router
    if strict_llm_only:
        if llm_router.primary is None:
            raise RuntimeError("llm_rag_only requires primary LLM provider")
        if isinstance(llm_router, LLMProviderRouter):
            effective_router = LLMProviderRouter(primary=llm_router.primary, fallback=None)
    is_ollama_fallback_only = _is_ollama_fallback_only_router(effective_router)
    system_prompt = _resolve_system_prompt(
        prompt_registry=prompt_registry,
        prompt_schema_strict=prompt_schema_strict,
    )
    if is_ollama_fallback_only and system_prompt and len(system_prompt) > 1200:
        # Keep local prompt compact to reduce timeout risk on CPU fallback models.
        system_prompt = system_prompt[:1200]
    prompt = _build_prompt(doctor_report)
    if system_prompt:
        try:
            payload, _path = effective_router.generate_json(
                prompt=prompt,
                output_schema=PATIENT_EXPLAIN_OUTPUT_SCHEMA,
                schema_name="patient_explain_v2",
                system_prompt=system_prompt,
            )
        except TypeError:
            payload, _path = effective_router.generate_json(
                prompt=prompt,
                output_schema=PATIENT_EXPLAIN_OUTPUT_SCHEMA,
                schema_name="patient_explain_v2",
            )
    else:
        payload, _path = effective_router.generate_json(
            prompt=prompt,
            output_schema=PATIENT_EXPLAIN_OUTPUT_SCHEMA,
            schema_name="patient_explain_v2",
        )
    if payload is None and str(_path or "").strip().lower() == "deterministic" and is_ollama_fallback_only:
        rescue_prompt = _build_local_rescue_prompt(doctor_report)
        payload, _path = effective_router.generate_json(
            prompt=rescue_prompt,
            output_schema=PATIENT_EXPLAIN_OUTPUT_SCHEMA,
            schema_name="patient_explain_v2",
        )
    if strict_llm_only:
        strict = _validate_llm_payload_without_coercion(
            payload,
            doctor_report=doctor_report,
            fallback=fallback,
        )
        if strict is None:
            raise RuntimeError("LLM patient explain returned invalid response in strict llm_rag_only mode")
        if str(_path or "").strip().lower() != "primary":
            raise RuntimeError("llm_rag_only forbids fallback/deterministic patient explain generation path")
        return strict, "llm"

    strict = _coerce_llm_payload(payload, fallback=fallback, doctor_report=doctor_report)
    return (strict, "llm") if strict is not None else (fallback, "deterministic")


def map_strict_to_public_patient(strict_payload: PatientExplainLLMStrict) -> dict[str, Any]:
    return dict(strict_payload)


def map_strict_to_pack_patient_v1_2(
    strict_payload: PatientExplainLLMStrict,
    *,
    request_id: str,
    source_ids: list[str],
    what_was_checked: list[str] | None = None,
    drug_safety: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary_plain = str(strict_payload.get("summary") or "").strip()
    if not summary_plain:
        summary_plain = "Проверка завершена. Обсудите результат с лечащим врачом."

    key_points = [
        str(item).strip()
        for item in (strict_payload.get("key_points") if isinstance(strict_payload.get("key_points"), list) else [])
        if str(item).strip()
    ][:6]
    if not key_points:
        key_points = ["Рекомендации требуют очного подтверждения лечащим врачом."]

    questions_for_doctor = [
        str(item).strip()
        for item in (
            strict_payload.get("questions_to_ask_doctor")
            if isinstance(strict_payload.get("questions_to_ask_doctor"), list)
            else []
        )
        if str(item).strip()
    ][:6]
    if not questions_for_doctor:
        questions_for_doctor = [
            "Какие данные нужно дополнить, чтобы подтвердить следующий шаг лечения?",
        ]

    disclaimer = str(strict_payload.get("safety_disclaimer") or "").strip() or SAFETY_DISCLAIMER
    safety_notes = [disclaimer]
    extra_safety = "Не меняйте лечение самостоятельно без решения лечащего врача."
    if extra_safety.lower() not in disclaimer.lower():
        safety_notes.append(extra_safety)

    checked_lines = [str(item).strip() for item in (what_was_checked or []) if str(item).strip()]
    if not checked_lines:
        checked_lines = [
            "Ответ сформирован на основе отчёта для врача и найденных клинических рекомендаций.",
        ]

    sources_used = sorted({str(item).strip().lower() for item in source_ids if str(item).strip()})
    normalized_drug_safety = drug_safety if isinstance(drug_safety, dict) else {}
    patient_drug_safety = {
        "status": (
            str(normalized_drug_safety.get("status") or "").strip().lower()
            if str(normalized_drug_safety.get("status") or "").strip().lower() in {"ok", "partial", "unavailable"}
            else "unavailable"
        ),
        "important_risks": [
            str(item).strip()
            for item in (
                normalized_drug_safety.get("important_risks")
                if isinstance(normalized_drug_safety.get("important_risks"), list)
                else []
            )
            if str(item).strip()
        ][:8],
        "questions_for_doctor": [
            str(item).strip()
            for item in (
                normalized_drug_safety.get("questions_for_doctor")
                if isinstance(normalized_drug_safety.get("questions_for_doctor"), list)
                else []
            )
            if str(item).strip()
        ][:6],
    }
    return {
        "schema_version": "1.2",
        "request_id": request_id,
        "summary_plain": summary_plain,
        "key_points": key_points,
        "questions_for_doctor": questions_for_doctor,
        "what_was_checked": checked_lines,
        "safety_notes": safety_notes,
        "drug_safety": patient_drug_safety,
        "sources_used": sources_used,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
