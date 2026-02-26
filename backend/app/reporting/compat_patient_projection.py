from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import uuid

try:
    from jsonschema import Draft202012Validator
except ModuleNotFoundError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[assignment]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _external_schema_path() -> Path:
    return _project_root() / "docs" / "contracts" / "external" / "patient_explain_v1_2_alt.schema.json"


@lru_cache(maxsize=1)
def _patient_schema_validator() -> Any | None:
    if Draft202012Validator is None:
        return None
    schema_path = _external_schema_path()
    if not schema_path.exists():
        return None
    schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _first_non_empty(items: list[str]) -> str:
    for item in items:
        value = str(item or "").strip()
        if value:
            return value
    return ""


def _normalize_uuid(value: str | None, *, seed_prefix: str) -> str:
    text = str(value or "").strip()
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"oncoai:{seed_prefix}:{text or 'empty'}"))


def _build_stage_explanation(doctor_report_v1_2: dict[str, Any]) -> str:
    disease_context = doctor_report_v1_2.get("disease_context") if isinstance(doctor_report_v1_2.get("disease_context"), dict) else {}
    stage_group = str(disease_context.get("stage_group") or "").strip()
    setting = str(disease_context.get("setting") or "").strip().lower()
    if stage_group:
        return f"В имеющихся данных указана стадия {stage_group}; её уточнение и значение нужно обсудить с лечащим врачом."
    if setting == "metastatic":
        return "В имеющихся данных отмечено распространение заболевания, поэтому важно обсуждать контроль болезни и качество жизни."
    if setting == "localized":
        return "В имеющихся данных заболевание описано как локализованное, что влияет на выбор тактики лечения."
    return "Для полной оценки важно уточнить стадию заболевания."


def _build_disease_explanation(
    patient_v1_2: dict[str, Any],
    doctor_report_v1_2: dict[str, Any],
) -> str:
    key_points = patient_v1_2.get("key_points") if isinstance(patient_v1_2.get("key_points"), list) else []
    first_key_point = _first_non_empty([str(item) for item in key_points if str(item).strip()])
    if first_key_point:
        return first_key_point
    summary = str(patient_v1_2.get("summary_plain") or "").strip()
    if summary:
        return summary
    consilium = str(doctor_report_v1_2.get("consilium_md") or "").strip()
    if consilium:
        return consilium.splitlines()[0].strip("# ").strip()
    return "Описание диагноза требует уточнения по данным лечащего врача."


def _build_treatment_strategy_explanation(
    patient_v1_2: dict[str, Any],
) -> str:
    checked = patient_v1_2.get("what_was_checked") if isinstance(patient_v1_2.get("what_was_checked"), list) else []
    candidate = _first_non_empty([str(item) for item in checked if str(item).strip()])
    if candidate:
        return candidate
    key_points = patient_v1_2.get("key_points") if isinstance(patient_v1_2.get("key_points"), list) else []
    candidate = _first_non_empty([str(item) for item in key_points if str(item).strip()])
    if candidate:
        return candidate
    return "Стратегия лечения определяется по клиническим данным и должна подтверждаться лечащим врачом."


def project_patient_explain_alt_profile(
    *,
    patient_v1_2: dict[str, Any],
    doctor_report_v1_2: dict[str, Any],
) -> dict[str, Any]:
    key_points = [str(item).strip() for item in (patient_v1_2.get("key_points") if isinstance(patient_v1_2.get("key_points"), list) else []) if str(item).strip()]
    questions = [
        str(item).strip()
        for item in (patient_v1_2.get("questions_for_doctor") if isinstance(patient_v1_2.get("questions_for_doctor"), list) else [])
        if str(item).strip()
    ]
    safety_notes = [
        str(item).strip()
        for item in (patient_v1_2.get("safety_notes") if isinstance(patient_v1_2.get("safety_notes"), list) else [])
        if str(item).strip()
    ]

    summary_plain = str(patient_v1_2.get("summary_plain") or "").strip()
    projection = {
        "schema_version": "1.2",
        "request_id": _normalize_uuid(str(patient_v1_2.get("request_id") or ""), seed_prefix="compat-patient-request"),
        "based_on_report_id": _normalize_uuid(
            str(doctor_report_v1_2.get("report_id") or ""),
            seed_prefix="compat-patient-report",
        ),
        "overall_interpretation": summary_plain,
        "disease_explanation": _build_disease_explanation(patient_v1_2, doctor_report_v1_2),
        "stage_explanation": _build_stage_explanation(doctor_report_v1_2),
        "treatment_strategy_explanation": _build_treatment_strategy_explanation(patient_v1_2),
        "key_points": key_points,
        "questions_for_doctor": questions,
        "safety_note": safety_notes[0] if safety_notes else "Этот текст носит информационный характер и не заменяет консультацию врача.",
        "generated_at": str(patient_v1_2.get("generated_at") or ""),
    }
    return projection


def validate_patient_projection_alt(payload: dict[str, Any]) -> list[str]:
    validator = _patient_schema_validator()
    if validator is None:
        return []
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    return [error.message for error in errors]
