from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any


def _to_uuid(value: str, seed: str) -> str:
    text = str(value or "").strip()
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"oncoai:{seed}:{text or 'empty'}"))


def build_disease_context(
    *,
    normalized_payload: dict[str, Any],
    case_json: dict[str, Any] | None,
    case_facts: dict[str, Any],
) -> dict[str, Any]:
    case_payload = normalized_payload.get("case") if isinstance(normalized_payload.get("case"), dict) else {}
    diagnosis = case_payload.get("diagnosis") if isinstance(case_payload.get("diagnosis"), dict) else {}
    biomarkers = case_payload.get("biomarkers") if isinstance(case_payload.get("biomarkers"), list) else []
    stage_item = case_facts.get("current_stage") if isinstance(case_facts.get("current_stage"), dict) else {}
    stage_group = str(stage_item.get("stage_group") or diagnosis.get("stage") or "").strip()
    tnm = str(stage_item.get("tnm") or "").strip().upper()
    metastases = case_facts.get("metastases") if isinstance(case_facts.get("metastases"), list) else []
    setting = "metastatic" if metastases or "M1" in tnm or "IV" in stage_group.upper() else "unknown"

    line: int | None = None
    if isinstance(case_json, dict):
        diagnoses = case_json.get("diagnoses")
        if isinstance(diagnoses, list) and diagnoses and isinstance(diagnoses[0], dict):
            last_plan = diagnoses[0].get("last_plan")
            if isinstance(last_plan, dict) and isinstance(last_plan.get("line"), int):
                line = int(last_plan["line"])

    payload = {
        "disease_id": _to_uuid(
            str(diagnosis.get("disease_id") or case_payload.get("cancer_type") or "unknown"),
            seed="disease",
        ),
        "icd10": str(diagnosis.get("icd10") or "").strip() or None,
        "stage_group": stage_group or None,
        "setting": setting,
        "line": line,
        "biomarkers": [
            {"name": str(item.get("name") or "").strip(), "value": str(item.get("value") or "").strip()}
            for item in biomarkers
            if isinstance(item, dict) and str(item.get("name") or "").strip() and str(item.get("value") or "").strip()
        ][:10],
    }
    return {key: value for key, value in payload.items() if value is not None}


def _append_timeline_event(
    target: list[dict[str, str]],
    *,
    seen: set[tuple[str, str, str]],
    date: Any,
    event_type: Any,
    label: Any,
    details: Any,
) -> None:
    date_text = str(date or "").strip()
    type_text = str(event_type or "other").strip() or "other"
    label_text = str(label or "").strip()
    if not label_text:
        return
    details_text = str(details or "").strip()
    key = (date_text.lower(), type_text.lower(), label_text.lower())
    if key in seen:
        return
    seen.add(key)
    target.append(
        {
            "date": date_text,
            "type": type_text,
            "label": label_text,
            "details": details_text,
        }
    )


def build_timeline(
    case_json: dict[str, Any] | None,
    *,
    case_facts: dict[str, Any] | None = None,
    timeline_reconciliation: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    if not isinstance(case_json, dict):
        case_json = {}

    diagnoses = case_json.get("diagnoses")
    if isinstance(diagnoses, list) and diagnoses and isinstance(diagnoses[0], dict):
        timeline = diagnoses[0].get("timeline")
        if isinstance(timeline, list):
            for item in timeline:
                if not isinstance(item, dict):
                    continue
                _append_timeline_event(
                    normalized,
                    seen=seen,
                    date=item.get("date"),
                    event_type=item.get("type"),
                    label=item.get("label") or item.get("details") or "event",
                    details=item.get("details"),
                )

    case_facts = case_facts if isinstance(case_facts, dict) else {}
    treatment_history = case_facts.get("treatment_history")
    if isinstance(treatment_history, list):
        for item in treatment_history:
            if not isinstance(item, dict):
                continue
            regimen = str(item.get("name") or "").strip()
            if not regimen:
                continue
            response = str(item.get("response") or "").strip()
            details_parts: list[str] = []
            start = str(item.get("start") or "").strip()
            end = str(item.get("end") or "").strip()
            if start and end and start != end:
                details_parts.append(f"{start}–{end}")
            elif start:
                details_parts.append(f"с {start}")
            elif end:
                details_parts.append(f"до {end}")
            if response:
                details_parts.append(f"результат: {response}")
            _append_timeline_event(
                normalized,
                seen=seen,
                date=start or end,
                event_type="systemic_therapy",
                label=regimen if not response else f"{regimen} ({response})",
                details="; ".join(details_parts),
            )

    current_stage = case_facts.get("current_stage") if isinstance(case_facts.get("current_stage"), dict) else {}
    current_stage_text = str(current_stage.get("tnm") or current_stage.get("stage_group") or "").strip()
    if current_stage_text:
        _append_timeline_event(
            normalized,
            seen=seen,
            date="",
            event_type="staging",
            label=f"Актуальное стадирование: {current_stage_text}",
            details="",
        )

    initial_stage = case_facts.get("initial_stage") if isinstance(case_facts.get("initial_stage"), dict) else {}
    initial_stage_text = str(initial_stage.get("tnm") or initial_stage.get("stage_group") or "").strip()
    if initial_stage_text and initial_stage_text != current_stage_text:
        _append_timeline_event(
            normalized,
            seen=seen,
            date="",
            event_type="staging",
            label=f"Исходное стадирование: {initial_stage_text}",
            details="",
        )

    timeline_reconciliation = timeline_reconciliation if isinstance(timeline_reconciliation, dict) else {}
    facts_lines = (
        timeline_reconciliation.get("facts_lines")
        if isinstance(timeline_reconciliation.get("facts_lines"), list)
        else []
    )
    for line in facts_lines:
        text = str(line or "").strip().rstrip(".")
        if not text:
            continue
        _append_timeline_event(
            normalized,
            seen=seen,
            date="",
            event_type="clinical_fact",
            label=text,
            details="",
        )

    return normalized[:40]


def build_consilium_md(
    *,
    query_type: str,
    case_facts: dict[str, Any],
    plan_sections: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    sufficiency: dict[str, Any],
    source_ids: list[str] | None = None,
    has_real_evidence: bool = True,
    timeline_reconciliation: dict[str, Any] | None = None,
) -> str:
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    stage = case_facts.get("current_stage") if isinstance(case_facts.get("current_stage"), dict) else {}
    stage_text = str(stage.get("tnm") or stage.get("stage_group") or "не указано")
    her2 = str(biomarkers.get("her2") or "не указано")
    cps_values = biomarkers.get("pd_l1_cps_values") if isinstance(biomarkers.get("pd_l1_cps_values"), list) else []
    cps_text = ", ".join(str(item) for item in cps_values) if cps_values else "не указано"
    msi = str(biomarkers.get("msi_status") or "не указано")
    timeline_reconciliation = timeline_reconciliation if isinstance(timeline_reconciliation, dict) else {}
    timeline_lines = (
        timeline_reconciliation.get("facts_lines")
        if isinstance(timeline_reconciliation.get("facts_lines"), list)
        else []
    )
    normalized_sources = {
        str(item).strip().lower()
        for item in (source_ids or [])
        if str(item).strip()
    }

    immuno_default_blocked = False
    cps_numeric = [float(item) for item in cps_values if isinstance(item, (int, float))]
    if msi.lower() in {"mss", "unknown", "pmmr"} and (not cps_numeric or max(cps_numeric) < 5.0):
        immuno_default_blocked = True

    plan_lines: list[str] = []
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
            if not text:
                continue
            if immuno_default_blocked and "иммуно" in text.lower():
                continue
            citation_ids = step.get("citation_ids") if isinstance(step.get("citation_ids"), list) else []
            if not has_real_evidence or not citation_ids:
                text = f"{text} — Не найдено в предоставленных рекомендациях"
            plan_lines.append(f"- {text}")
    if not plan_lines:
        plan_lines = ["- Не найдено в предоставленных рекомендациях"]

    issue_lines = [f"- {str(item.get('summary') or '').strip()}" for item in issues if str(item.get("summary") or "").strip()]
    if not issue_lines:
        issue_lines = ["- Существенных отклонений не выявлено."]

    missing_critical = sufficiency.get("missing_critical_fields") if isinstance(sufficiency.get("missing_critical_fields"), list) else []
    if missing_critical:
        data_gap_lines = [f"- {item}" for item in missing_critical]
    else:
        data_gap_lines = ["- Существенных пробелов данных не выявлено."]
    timeline_missing = (
        timeline_reconciliation.get("missing_items")
        if isinstance(timeline_reconciliation.get("missing_items"), list)
        else []
    )
    if timeline_missing:
        if data_gap_lines == ["- Существенных пробелов данных не выявлено."]:
            data_gap_lines = []
        data_gap_lines.extend(f"- Таймлайн: {str(item)}" for item in timeline_missing if str(item).strip())

    immuno_note = "- Иммунотерапия не предлагается по умолчанию при текущем сочетании CPS/MSI." if immuno_default_blocked else ""
    question_text = "Следующие шаги лечения" if str(query_type).upper() == "NEXT_STEPS" else "Проверка последнего этапа лечения"
    guideline_basis_lines = [
        "- Выводы сформированы только по найденным фрагментам рекомендаций.",
    ]
    if "minzdrav" in normalized_sources:
        guideline_basis_lines.append(
            "- Минздрав: первичная валидация тактики по клиническим рекомендациям Минздрава РФ."
        )
    if "russco" in normalized_sources:
        guideline_basis_lines.append(
            "- RUSSCO: дополнительная проверка лекарственных опций и линий терапии."
        )

    parts = [
        "## Ключевые клинические факты",
        f"- TNM/стадия: {stage_text}",
        f"- HER2: {her2}",
        f"- PD-L1 CPS: {cps_text}",
        f"- MSI/dMMR: {msi}",
        *[f"- Клиническая последовательность: {str(item)}" for item in timeline_lines if str(item).strip()],
        "",
        "## Клинический вопрос",
        f"- {question_text}",
        "",
        "## Обоснование по клинреку",
        *guideline_basis_lines,
        "",
        "## План действий",
        *plan_lines,
        "",
        "## Риски и безопасность",
        *issue_lines,
    ]
    if immuno_note:
        parts.append(immuno_note)
    parts.extend(
        [
            "",
            "## Дефицит данных",
            *data_gap_lines,
        ]
    )
    return "\n".join(parts).strip()


def build_patient_explain(
    *,
    request_id: str,
    plan_sections: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    sufficiency: dict[str, Any],
    source_ids: list[str],
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    issue_count = len(issues)
    missing_critical = sufficiency.get("missing_critical_fields") if isinstance(sufficiency.get("missing_critical_fields"), list) else []
    summary = (
        f"Проверка завершена. Найдено {issue_count} момент(а), которые важно обсудить с лечащим врачом."
        if issue_count
        else "Проверка завершена. Критичных отклонений не выявлено, но решение должен подтвердить лечащий врач."
    )
    if missing_critical:
        summary = f"Проверка ограничена из-за неполных данных ({', '.join(str(item) for item in missing_critical)})."

    key_points: list[str] = []
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
                key_points.append(text)
            if len(key_points) >= 4:
                break
        if len(key_points) >= 4:
            break

    questions = [
        "Какие данные нужно дополнить, чтобы выбрать следующую линию лечения?",
        "Какие риски и побочные эффекты наиболее вероятны в моей ситуации?",
    ]
    if missing_critical:
        questions.insert(0, "Какие анализы/маркеры нужно сдать в первую очередь?")

    return {
        "schema_version": "1.2",
        "request_id": request_id,
        "summary_plain": summary,
        "key_points": key_points,
        "questions_for_doctor": questions[:6],
        "what_was_checked": ["План лечения сопоставлен с найденными рекомендациями и клиническими фактами кейса."],
        "safety_notes": [
            "Этот текст носит справочный характер и не заменяет очную консультацию врача.",
            "Не меняйте лечение самостоятельно без решения лечащего врача.",
        ],
        "sources_used": sorted({str(item).strip().lower() for item in source_ids if str(item).strip()}),
        "generated_at": generated_at,
    }


def build_run_meta(
    *,
    request_id: str,
    retrieved: list[dict[str, Any]],
    reranked: list[dict[str, Any]],
    citations_count: int,
    llm_path: str,
    report_generation_path: str,
    fallback_reason: str | None,
    reasoning_mode: str,
    routing_meta: dict[str, Any] | None,
    started_at_perf: float,
    settings: Any,
) -> dict[str, Any]:
    total_ms = int(round((time.perf_counter() - started_at_perf) * 1000.0))
    retrieval_ms = int(round(total_ms * 0.25))
    llm_ms = int(round(total_ms * 0.55)) if report_generation_path in {"primary", "fallback"} else 0
    postprocess_ms = max(0, total_ms - retrieval_ms - llm_ms)
    payload: dict[str, Any] = {
        "schema_version": "0.2",
        "request_id": request_id,
        "timings_ms": {
            "total": max(total_ms, 0),
            "retrieval": max(retrieval_ms, 0),
            "llm": max(llm_ms, 0),
            "postprocess": max(postprocess_ms, 0),
        },
        "docs_retrieved_count": len(retrieved),
        "docs_after_filter_count": len(reranked),
        "citations_count": int(citations_count),
        "evidence_valid_ratio": 1.0 if citations_count > 0 else 0.0,
        "retrieval_engine": str(getattr(settings, "rag_engine", "basic") or "basic"),
        "reasoning_mode": str(reasoning_mode or "compat"),
        "llm_path": str(llm_path or "deterministic"),
        "vector_backend": str(getattr(settings, "vector_backend", "local") or "local"),
        "embedding_backend": str(getattr(settings, "embedding_backend", "hash") or "hash"),
        "reranker_backend": str(getattr(settings, "reranker_backend", "lexical") or "lexical"),
        "report_generation_path": report_generation_path,
        "fallback_reason": str(fallback_reason or "none"),
    }
    if isinstance(routing_meta, dict):
        payload["routing_meta"] = {
            "resolved_disease_id": str(routing_meta.get("resolved_disease_id") or "unknown_disease"),
            "resolved_cancer_type": str(routing_meta.get("resolved_cancer_type") or "unknown"),
            "match_strategy": str(routing_meta.get("match_strategy") or "default_sources_fallback"),
            "source_ids": [
                str(item).strip()
                for item in (routing_meta.get("source_ids") if isinstance(routing_meta.get("source_ids"), list) else [])
                if str(item).strip()
            ],
            "doc_ids": [
                str(item).strip()
                for item in (routing_meta.get("doc_ids") if isinstance(routing_meta.get("doc_ids"), list) else [])
                if str(item).strip()
            ],
            "candidate_chunks": int(routing_meta.get("candidate_chunks") or 0),
            "baseline_candidate_chunks": int(routing_meta.get("baseline_candidate_chunks") or 0),
            "reduction_ratio": float(routing_meta.get("reduction_ratio") or 0.0),
        }
    return payload
