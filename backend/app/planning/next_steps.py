from __future__ import annotations

import uuid
from typing import Any


_PLAN_NAMESPACE = uuid.UUID("03d3f79d-9d6b-4f5a-9456-26025b4fce6e")


def _step_id(seed: str) -> str:
    return str(uuid.uuid5(_PLAN_NAMESPACE, seed))


def _has_progression_after_ramu_pacli(case_facts: dict[str, Any]) -> bool:
    history = case_facts.get("treatment_history")
    if not isinstance(history, list):
        return False
    for item in history:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").lower()
        response = str(item.get("response") or "").lower()
        if ("рамуцирумаб" in name or "ramucirumab" in name) and ("паклитаксел" in name or "paclitaxel" in name):
            if "progress" in response or "прогресс" in response:
                return True
    return False


def _has_biomarker(case_facts: dict[str, Any], key: str) -> bool:
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    value = biomarkers.get(key)
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return True
    return bool(str(value or "").strip()) and str(value).strip().lower() != "unknown"


def build_next_steps_plan_sections(
    *,
    query_type: str,
    case_facts: dict[str, Any],
    disease_context: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized_query = str(query_type or "").strip().upper()
    if normalized_query == "CHECK_LAST_TREATMENT":
        return [
            {
                "section": "treatment",
                "title": "Проверка текущего лечения",
                "steps": [
                    {
                        "step_id": _step_id("check-current-therapy"),
                        "text": "Сверить последнюю линию терапии с критериями назначения и актуальными противопоказаниями.",
                        "priority": "high",
                        "rationale": "Для CHECK_LAST_TREATMENT оценивается корректность уже назначенного этапа.",
                        "step_type": "systemic_therapy",
                    }
                ],
            }
        ]

    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    her2_positive = str(biomarkers.get("her2_interpretation") or "").strip().lower() == "positive"
    msi_status = str(biomarkers.get("msi_status") or "").strip()
    has_cps = _has_biomarker(case_facts, "pd_l1_cps_values")
    has_cldn = _has_biomarker(case_facts, "cldn18_2_percent") or (
        str(biomarkers.get("cldn18_2_interpretation") or "").strip().lower() == "positive"
    )

    treatment_steps: list[dict[str, Any]] = [
        {
            "step_id": _step_id("treatment-branch-by-biomarkers"),
            "text": "Сформировать ветвистое решение: если HER2+, рассмотреть добавление trastuzumab к химиотерапии 1-й линии.",
            "priority": "high",
            "rationale": "HER2 влияет на выбор первой линии терапии при метастатическом процессе.",
            "step_type": "systemic_therapy",
        },
        {
            "step_id": _step_id("treatment-line-clarification"),
            "text": "Уточнить текущую линию лечения и факт прогрессирования перед сменой системной терапии.",
            "priority": "high",
            "rationale": "Номер линии определяет допустимые опции и уровень доказательности.",
            "step_type": "systemic_therapy",
        },
    ]

    if not her2_positive:
        treatment_steps.append(
            {
                "step_id": _step_id("treatment-her2-negative-path"),
                "text": "Если HER2- и есть клинические показания, выбрать системную опцию по линии и переносимости (без иммунотерапии по умолчанию).",
                "priority": "medium",
                "rationale": "Иммунотерапия и таргетные опции зависят от CPS/MSI и предшествующей терапии.",
                "step_type": "systemic_therapy",
            }
        )

    if has_cldn:
        treatment_steps.append(
            {
                "step_id": _step_id("treatment-cldn182-option"),
                "text": "При CLDN18.2-позитивном HER2- варианте рассмотреть zolbetuximab-содержащую схему, если доступно по показаниям.",
                "priority": "medium",
                "rationale": "CLDN18.2-позитивность формирует отдельную лечебную ветку.",
                "step_type": "systemic_therapy",
            }
        )

    if _has_progression_after_ramu_pacli(case_facts):
        treatment_steps.append(
            {
                "step_id": _step_id("post-progression-after-ramu-pacli"),
                "text": "После прогрессирования на ramucirumab+paclitaxel рассмотреть иринотекан-содержащую опцию и иммунотерапию при наличии показаний.",
                "priority": "high",
                "rationale": "Факт прогрессирования на предыдущей линии требует отдельного выбора следующего шага.",
                "step_type": "systemic_therapy",
            }
        )

    diagnostics_steps = [
        {
            "step_id": _step_id("diagnostics-pathology-review"),
            "text": "Провести ревизию морфологии/патологии и верифицировать гистологический вариант опухоли.",
            "priority": "high",
            "rationale": "Перед выбором следующего этапа важно подтвердить исходные морфологические данные.",
            "step_type": "diagnostic_confirmation",
        },
        {
            "step_id": _step_id("diagnostics-biomarker-panel"),
            "text": "Дозапросить/подтвердить критические биомаркеры: HER2, PD-L1 CPS, MSI/dMMR, при доступности CLDN18.2.",
            "priority": "high",
            "rationale": "Биомаркеры определяют лечебные развилки.",
            "step_type": "diagnostic_confirmation",
        },
    ]

    if not has_cps or msi_status.lower() in {"unknown", ""}:
        diagnostics_steps.append(
            {
                "step_id": _step_id("diagnostics-missing-predictive-markers"),
                "text": "При нехватке предиктивных маркеров отложить окончательное решение по иммунотерапии до получения результатов.",
                "priority": "high",
                "rationale": "Решение без CPS/MSI повышает риск неверной эскалации терапии.",
                "step_type": "diagnostic_confirmation",
            }
        )

    staging_steps = [
        {
            "step_id": _step_id("staging-ct"),
            "text": "Выполнить контрольное стадирование (КТ грудной клетки/брюшной полости/таза) перед изменением линии лечения.",
            "priority": "high",
            "rationale": "Нужно подтвердить распространенность процесса и динамику заболевания.",
            "step_type": "staging",
        },
        {
            "step_id": _step_id("staging-resectability"),
            "text": "Оценить резектабельность и статус метастазов на консилиуме с хирургом и радиологом.",
            "priority": "medium",
            "rationale": "Тактика лечения зависит от резектабельности и локализации метастазов.",
            "step_type": "staging",
        },
    ]

    supportive_steps = [
        {
            "step_id": _step_id("supportive-ps-toxicity"),
            "text": "Переоценить ECOG/PS и токсичность предыдущей терапии (нейропатия, нутритивный статус, коагуляция).",
            "priority": "medium",
            "rationale": "Токсичность и функциональный статус ограничивают выбор режима.",
            "step_type": "supportive",
        }
    ]

    follow_up_steps = [
        {
            "step_id": _step_id("follow-up-mdt"),
            "text": "Зафиксировать решение мультидисциплинарного консилиума и дату контрольной оценки эффекта.",
            "priority": "medium",
            "rationale": "Решение должно быть формализовано с чёткой точкой переоценки.",
            "step_type": "follow_up",
        }
    ]

    return [
        {"section": "diagnostics", "title": "Диагностика", "steps": diagnostics_steps},
        {"section": "staging", "title": "Стадирование", "steps": staging_steps},
        {"section": "treatment", "title": "Лечение", "steps": treatment_steps},
        {"section": "supportive", "title": "Сопроводительная тактика", "steps": supportive_steps},
        {"section": "follow_up", "title": "Наблюдение", "steps": follow_up_steps},
    ]


def flatten_plan_for_diff(plan_sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    flattened: list[dict[str, str]] = []
    for section in plan_sections:
        if not isinstance(section, dict):
            continue
        for step in section.get("steps", []):
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "").strip()
            step_type = str(step.get("step_type") or section.get("section") or "").strip().lower()
            if not text:
                continue
            flattened.append({"step_type": step_type, "name": text})
    return flattened
