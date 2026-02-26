from __future__ import annotations

from typing import Any


def _collect_plan_steps(plan_sections: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    out: list[str] = []
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
                out.append(text)
            if len(out) >= limit:
                return out
    return out


def _collect_timeline_lines(timeline: list[dict[str, Any]], *, limit: int = 4) -> list[str]:
    out: list[str] = []
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


def _collect_sources(citations: list[dict[str, Any]]) -> tuple[bool, bool, list[str]]:
    has_minzdrav = False
    has_russco = False
    lines: list[str] = []
    seen: set[str] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_id") or "").strip().lower()
        doc_id = str(item.get("doc_id") or item.get("document_id") or "").strip()
        page = item.get("page_start")
        if source == "minzdrav":
            has_minzdrav = True
        if source == "russco":
            has_russco = True
        marker = f"{source}:{doc_id}:{page}"
        if not source or not doc_id or marker in seen:
            continue
        seen.add(marker)
        if isinstance(page, int):
            lines.append(f"- {source}: {doc_id}, стр. {page}")
        else:
            lines.append(f"- {source}: {doc_id}")
    return has_minzdrav, has_russco, lines


def build_guided_report(
    *,
    query_type: str,
    disease_context: dict[str, Any],
    case_facts: dict[str, Any],
    timeline: list[dict[str, Any]],
    plan_sections: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    insufficient_data: dict[str, Any],
) -> dict[str, Any]:
    stage = (
        str((case_facts.get("current_stage") or {}).get("tnm") or (case_facts.get("current_stage") or {}).get("stage_group") or "")
        if isinstance(case_facts.get("current_stage"), dict)
        else ""
    )
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    her2 = str(biomarkers.get("her2") or "не указано")
    msi = str(biomarkers.get("msi_status") or "не указано")
    cps_values = biomarkers.get("pd_l1_cps_values") if isinstance(biomarkers.get("pd_l1_cps_values"), list) else []
    cps_text = ", ".join(str(item) for item in cps_values[:3]) if cps_values else "не указано"

    v2 = case_facts.get("case_facts_v2") if isinstance(case_facts.get("case_facts_v2"), dict) else {}
    labs = v2.get("labs") if isinstance(v2.get("labs"), list) else []
    meds = v2.get("current_medications") if isinstance(v2.get("current_medications"), list) else []
    comorbidities = v2.get("comorbidities") if isinstance(v2.get("comorbidities"), list) else []

    plan_steps = _collect_plan_steps(plan_sections, limit=6)
    timeline_lines = _collect_timeline_lines(timeline, limit=4)
    issue_lines = [
        str(item.get("summary") or "").strip()
        for item in issues
        if isinstance(item, dict) and str(item.get("summary") or "").strip()
    ][:5]
    has_minzdrav, has_russco, source_lines = _collect_sources(citations)

    input_lines = [
        f"- ICD-10: {str(disease_context.get('icd10') or 'не указано')}",
        f"- Стадия/TNM: {stage or str(disease_context.get('stage_group') or 'не указано')}",
        f"- HER2: {her2}; PD-L1 CPS: {cps_text}; MSI: {msi}",
    ]
    if timeline_lines:
        input_lines.extend(f"- Таймлайн: {line}" for line in timeline_lines)

    minzdrav_lines = [
        "- Первичная валидация тактики выполнена по клиническим рекомендациям Минздрава РФ."
        if has_minzdrav
        else "- В этом прогоне нет подтверждённых фрагментов Минздрава.",
    ]
    russco_lines = [
        "- Дополнительная проверка лекарственных опций выполнена по RUSSCO."
        if has_russco
        else "- В этом прогоне нет подтверждённых фрагментов RUSSCO.",
    ]

    labs_line = ", ".join(
        f"{str(item.get('name') or '')}={str(item.get('value') or '').strip()}"
        for item in labs[:5]
        if isinstance(item, dict)
    )
    meds_line = ", ".join(
        str(item.get("name") or "").strip()
        for item in meds[:5]
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    )
    comorb_line = ", ".join(
        str(item.get("name") or "").strip()
        for item in comorbidities[:5]
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    )

    insuff_status = bool(insufficient_data.get("status"))
    insuff_reason = str(insufficient_data.get("reason") or "").strip()

    doctor_summary_plain = (
        "Клиническая проверка сформирована: тактика сопоставлена с Минздравом и RUSSCO, выделены ключевые риски."
    )
    if insuff_status:
        doctor_summary_plain = f"Клиническая проверка ограничена неполнотой данных: {insuff_reason or 'нужны дополнительные сведения.'}"

    patient_summary_plain = (
        "Подготовлен план обсуждения с лечащим врачом на основе загруженных данных и клинических рекомендаций."
    )
    if insuff_status:
        patient_summary_plain = (
            "Пока данных недостаточно для окончательного выбора лечения. Обсудите с врачом, какие анализы нужно дополнить."
        )

    query_label = "Следующие шаги лечения" if str(query_type).upper() == "NEXT_STEPS" else "Проверка последнего этапа лечения"
    sections = [
        "## Входные данные",
        *input_lines,
        "",
        "## Проверка по Минздраву",
        *minzdrav_lines,
        "",
        "## Проверка по RUSSCO",
        *russco_lines,
        "",
        "## Дозировки и безопасность",
        f"- Вопрос запроса: {query_label}.",
        f"- Лабораторные данные: {labs_line or 'не структурированы'}",
        "",
        "## Взаимодействия и коморбидности",
        f"- Текущие препараты: {meds_line or 'не указаны'}",
        f"- Сопутствующие заболевания: {comorb_line or 'не указаны'}",
        "",
        "## Резюме для врача",
        f"- {doctor_summary_plain}",
        *([f"- Клинические замечания: {'; '.join(issue_lines)}"] if issue_lines else ["- Клинические замечания не выявлены."]),
        *([f"- Ключевые шаги: {'; '.join(plan_steps)}"] if plan_steps else ["- Ключевые шаги не сформированы."]),
        "",
        "## Резюме для пациента",
        f"- {patient_summary_plain}",
        "",
        "## Источники",
        *(source_lines or ["- Подтверждённые источники не найдены в текущем прогоне."]),
    ]

    patient_key_points = plan_steps[:4] if plan_steps else issue_lines[:4]
    return {
        "doctor_summary_md": "\n".join(sections).strip(),
        "doctor_summary_plain": doctor_summary_plain,
        "patient_summary_plain": patient_summary_plain,
        "patient_key_points": patient_key_points,
    }
