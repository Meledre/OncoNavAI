from __future__ import annotations

from typing import Any

import pytest

from backend.app.llm.generate_patient_explain import (
    build_patient_explain_strict,
    build_patient_explain_with_fallback,
    map_strict_to_pack_patient_v1_2,
)


def _doctor_report() -> dict[str, Any]:
    return {
        "report_id": "rep-1",
        "kb_version": "kb-1",
        "summary": "demo",
        "issues": [],
        "missing_data": [],
    }


def _doctor_report_v1_2() -> dict[str, Any]:
    return {
        "schema_version": "1.2",
        "report_id": "rep-v1-2",
        "request_id": "req-v1-2",
        "query_type": "NEXT_STEPS",
        "disease_context": {
            "icd10": "C16",
            "stage_group": "III",
            "setting": "locally_advanced",
            "line": 2,
            "biomarkers": [
                {"name": "HER2", "value": "1+"},
                {"name": "PD-L1 CPS", "value": "8/3"},
                {"name": "MSI", "value": "MSS"},
            ],
        },
        "case_facts": {
            "current_stage": {"tnm": "pT3N2M0", "stage_group": "III"},
            "biomarkers": {
                "her2": "1+",
                "pd_l1_cps_values": [8, 3],
                "msi_status": "MSS",
            },
        },
        "timeline": [
            {"label": "Прогрессирование после рамуцирумаб + паклитаксел"},
        ],
        "plan": [
            {
                "title": "Лечение",
                "section": "treatment",
                "steps": [
                    {"text": "Рассмотреть иринотекан после подтверждения прогрессирования", "citation_ids": ["c-1"]}
                ],
            }
        ],
        "issues": [
            {
                "severity": "warning",
                "kind": "missing_data",
                "summary": "Нужно уточнить объём лимфодиссекции D2",
                "details": "Для полной оценки тактики необходимо подтверждение этапа D2.",
            }
        ],
        "citations": [
            {"source_id": "russco", "doc_id": "russco_2025_1_1_13"},
        ],
    }


class _FallbackOnlyRouterNoCall:
    primary = None
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("generate_json should be called for fallback-only patient explain")


class _FallbackOnlyRouterInvalid:
    primary = None
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return {"summary": ""}, "fallback"


class _FallbackOnlyRouterRawText:
    primary = None
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return {
            "_raw_text": (
                "Обсудите результаты обследований с лечащим врачом.\n"
                "Важно уточнить недостающие маркеры перед выбором терапии."
            )
        }, "fallback"


class _FallbackOnlyRouterOk:
    primary = None
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return (
            {
                "summary": "LLM patient summary",
                "key_points": ["k1"],
                "questions_to_ask_doctor": ["q1"],
                "safety_disclaimer": "d1",
            },
            "fallback",
        )


class _CapturePromptRouter:
    primary = object()
    fallback = None

    def __init__(self) -> None:
        self.last_prompt = ""

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.last_prompt = str(kwargs.get("prompt") or (args[0] if args else ""))
        return (
            {
                "summary": "Данные по лечению и рискам собраны, ключевые вопросы стоит обсудить с лечащим врачом.",
                "key_points": ["После прогрессирования важно уточнить следующий этап лечения."],
                "questions_to_ask_doctor": ["Какие данные ещё нужны для выбора следующей линии?"],
                "safety_disclaimer": "Этот текст носит справочный характер и не заменяет консультацию врача.",
            },
            "primary",
        )


class _FallbackDeterministicThenRawTextRouter:
    primary = None

    class _FallbackEndpoint:
        url = "http://ollama:11434"

    fallback = _FallbackEndpoint()

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        if self.calls == 1:
            return None, "deterministic"
        return {
            "_raw_text": (
                "По текущим данным есть вопросы, которые стоит обсудить с лечащим врачом.\n"
                "Важно уточнить недостающие параметры перед выбором следующей линии."
            )
        }, "fallback"


class _FallbackNoSummaryRouter:
    primary = None
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return (
            {
                "key_points": ["Нужно подтвердить полноту биомаркеров перед окончательным выбором шага."],
                "questions_to_ask_doctor": ["Какие данные нужно дополнить в первую очередь?"],
                "safety_disclaimer": "Этот текст носит справочный характер и не заменяет консультацию врача.",
            },
            "fallback",
        )


class _FallbackRawJsonLinesRouter:
    primary = None
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return (
            {
                "_raw_text": (
                    "{\n"
                    "\"summary\": \"Выявлено 1 замечание\",\n"
                    "\"key_points\": [\"Нужно уточнить биомаркеры\"],\n"
                    "\"questions_to_ask_doctor\": [\"Что делать дальше?\"]\n"
                    "}\n"
                    "Обсудите результаты с лечащим врачом на очном приеме.\n"
                )
            },
            "fallback",
        )


class _PrimaryStrictPatientRouter:
    primary = object()
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return (
            {
                "summary": "Строгое объяснение для пациента.",
                "key_points": ["Ключевой пункт 1"],
                "questions_to_ask_doctor": ["Вопрос 1"],
                "safety_disclaimer": "Этот текст носит справочный характер и не заменяет консультацию врача.",
            },
            "primary",
        )


class _PrimaryInvalidPatientRouter:
    primary = object()
    fallback = object()

    def generate_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return (
            {
                "summary": "",
                "key_points": [],
                "questions_to_ask_doctor": [],
                "safety_disclaimer": "",
            },
            "primary",
        )


def test_patient_explain_fallback_only_defaults_to_deterministic(monkeypatch):
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report(),
        llm_router=_FallbackOnlyRouterOk(),  # type: ignore[arg-type]
    )
    assert path == "llm"
    assert payload["summary"]
    assert payload["summary"] != "LLM patient summary"
    assert payload["key_points"] != ["k1"]
    assert payload["questions_to_ask_doctor"] != ["q1"]


def test_patient_explain_fallback_only_can_be_enabled(monkeypatch):
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report(),
        llm_router=_FallbackOnlyRouterInvalid(),  # type: ignore[arg-type]
    )
    assert path == "llm"
    assert payload["schema_version"] in {"0.1", "0.2"}


def test_map_strict_patient_to_pack_v1_2_fields() -> None:
    strict_payload = {
        "schema_version": "0.2",
        "kb_version": "kb-1",
        "based_on_report_id": "rep-1",
        "summary": "Кратко для пациента",
        "key_points": ["Пункт 1", "Пункт 2"],
        "questions_to_ask_doctor": ["Вопрос 1"],
        "safety_disclaimer": "Справочно, не является назначением.",
    }
    mapped = map_strict_to_pack_patient_v1_2(
        strict_payload=strict_payload,  # type: ignore[arg-type]
        request_id="r1",
        source_ids=["minzdrav", "russco"],
    )
    assert mapped["schema_version"] == "1.2"
    assert mapped["request_id"] == "r1"
    assert mapped["summary_plain"] == "Кратко для пациента"
    assert mapped["questions_for_doctor"] == ["Вопрос 1"]
    assert mapped["safety_notes"]
    assert mapped["drug_safety"]["status"] in {"ok", "partial", "unavailable"}
    assert sorted(mapped["sources_used"]) == ["minzdrav", "russco"]


def test_patient_explain_coerces_raw_text_payload_to_llm_result() -> None:
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report(),
        llm_router=_FallbackOnlyRouterRawText(),  # type: ignore[arg-type]
    )
    assert path == "llm"
    assert payload["summary"]
    assert payload["key_points"]


def test_patient_fallback_builder_supports_v1_2_doctor_report_shape() -> None:
    payload = build_patient_explain_strict(_doctor_report_v1_2())
    assert payload["schema_version"] in {"0.1", "0.2"}
    assert payload["kb_version"]
    assert "стад" in payload["summary"].lower()
    assert any("иринотекан" in item.lower() for item in payload["key_points"])


def test_patient_prompt_contains_v1_2_case_context() -> None:
    router = _CapturePromptRouter()
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report_v1_2(),
        llm_router=router,  # type: ignore[arg-type]
    )
    assert path == "llm"
    assert payload["summary"]
    prompt = router.last_prompt
    assert "pT3N2M0" in prompt
    assert "PD-L1" in prompt
    assert "MSI" in prompt
    assert "рамуцирумаб" in prompt
    assert "иринотекан" in prompt.lower()


def test_patient_local_retries_with_rescue_prompt() -> None:
    router = _FallbackDeterministicThenRawTextRouter()
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report_v1_2(),
        llm_router=router,  # type: ignore[arg-type]
    )
    assert router.calls >= 2
    assert path == "llm"
    assert payload["summary"]


def test_patient_coerce_uses_fallback_summary_when_summary_is_missing() -> None:
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report_v1_2(),
        llm_router=_FallbackNoSummaryRouter(),  # type: ignore[arg-type]
    )
    assert path == "llm"
    assert payload["summary"]
    assert payload["key_points"]


def test_patient_raw_json_lines_do_not_leak_schema_keys_into_summary() -> None:
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report_v1_2(),
        llm_router=_FallbackRawJsonLinesRouter(),  # type: ignore[arg-type]
    )
    assert path == "llm"
    assert payload["summary"]
    assert not str(payload["summary"]).strip().startswith('"summary"')


def test_patient_strict_llm_only_requires_primary_provider() -> None:
    with pytest.raises(RuntimeError, match="primary LLM provider"):
        build_patient_explain_with_fallback(
            doctor_report=_doctor_report_v1_2(),
            llm_router=_FallbackOnlyRouterOk(),  # type: ignore[arg-type]
            strict_llm_only=True,
        )


def test_patient_strict_llm_only_rejects_invalid_primary_payload() -> None:
    with pytest.raises(RuntimeError, match="invalid response"):
        build_patient_explain_with_fallback(
            doctor_report=_doctor_report_v1_2(),
            llm_router=_PrimaryInvalidPatientRouter(),  # type: ignore[arg-type]
            strict_llm_only=True,
        )


def test_patient_strict_llm_only_returns_primary_llm_path() -> None:
    payload, path = build_patient_explain_with_fallback(
        doctor_report=_doctor_report_v1_2(),
        llm_router=_PrimaryStrictPatientRouter(),  # type: ignore[arg-type]
        strict_llm_only=True,
    )
    assert path == "llm"
    assert payload["summary"] == "Строгое объяснение для пациента."
