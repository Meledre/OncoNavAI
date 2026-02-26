from __future__ import annotations

from typing import Any

import pytest

from backend.app.llm.generate_doctor_report import DOCTOR_REPORT_OUTPUT_SCHEMA, build_doctor_report_with_fallback


def _retrieved_chunk() -> dict[str, Any]:
    return {
        "chunk_id": "c1",
        "doc_id": "guideline_nsclc",
        "doc_version": "2025-11",
        "source_set": "mvp_guidelines_ru_2025",
        "cancer_type": "nsclc_egfr",
        "language": "ru",
        "pdf_page_index": 0,
        "page_label": "1",
        "section_title": "Systemic therapy",
        "text": "osimertinib guidance fragment",
    }


class _FakeRouterPrimaryOk:
    primary = object()
    fallback = None

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        prompt: str,  # noqa: ARG002
        output_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
    ) -> tuple[dict[str, Any] | None, str]:
        self.calls.append({"output_schema": output_schema, "schema_name": schema_name})
        return (
            {
                "summary": "LLM summary",
                "issues": [
                    {
                        "severity": "important",
                        "category": "other",
                        "title": "Potential mismatch",
                        "description": "Needs clinician review.",
                        "confidence": 0.81,
                        "chunk_ids": ["c1"],
                    }
                ],
                "missing_data": [{"field": "performance_status", "reason": "Required for confidence."}],
                "notes": "Clinical review required.",
            },
            "primary",
        )


class _FakeRouterPrimaryInvalid:
    primary = object()
    fallback = None

    def generate_json(
        self,
        prompt: str,  # noqa: ARG002
        output_schema: dict[str, Any] | None = None,  # noqa: ARG002
        schema_name: str = "response",  # noqa: ARG002
    ) -> tuple[dict[str, Any] | None, str]:
        return {"summary": "bad", "issues": "not-array"}, "primary"


class _FakeRouterPrimaryStrictValid:
    primary = object()
    fallback = object()

    def generate_json(
        self,
        prompt: str,  # noqa: ARG002
        output_schema: dict[str, Any] | None = None,  # noqa: ARG002
        schema_name: str = "response",  # noqa: ARG002
        system_prompt: str | None = None,  # noqa: ARG002
    ) -> tuple[dict[str, Any] | None, str]:
        return (
            {
                "summary": "Строгий отчёт LLM.",
                "issues": [
                    {
                        "issue_id": "ISS-1",
                        "severity": "important",
                        "category": "deviation",
                        "title": "Potential mismatch",
                        "description": "Needs clinician review.",
                        "confidence": 0.81,
                        "chunk_ids": ["c1"],
                    }
                ],
                "missing_data": [{"field": "performance_status", "reason": "Required for confidence."}],
                "notes": "Clinical review required.",
            },
            "primary",
        )


class _FakeRouterFallbackInvalid:
    primary = None
    fallback = object()

    def generate_json(
        self,
        prompt: str,  # noqa: ARG002
        output_schema: dict[str, Any] | None = None,  # noqa: ARG002
        schema_name: str = "response",  # noqa: ARG002
    ) -> tuple[dict[str, Any] | None, str]:
        return {"_raw_text": "not-json"}, "fallback"


class _FakeRouterFallbackPartiallyStructured:
    primary = None
    fallback = object()

    def generate_json(
        self,
        prompt: str,  # noqa: ARG002
        output_schema: dict[str, Any] | None = None,  # noqa: ARG002
        schema_name: str = "response",  # noqa: ARG002
    ) -> tuple[dict[str, Any] | None, str]:
        return {
            "summary": "",
            "issues": [{"id": 0, "description": ""}],
            "missing_data": [{"field_name": "ECOG", "reason": "Не указан статус."}],
            "notes": [],
        }, "fallback"


class _FakeRouterFallbackRawTextRich:
    primary = None
    fallback = object()

    def generate_json(
        self,
        prompt: str,  # noqa: ARG002
        output_schema: dict[str, Any] | None = None,  # noqa: ARG002
        schema_name: str = "response",  # noqa: ARG002
    ) -> tuple[dict[str, Any] | None, str]:
        return {
            "_raw_text": (
                "Сформирован предварительный клинический комментарий.\n"
                "Необходимо уточнить стадию заболевания перед выбором следующей линии терапии."
            )
        }, "fallback"


class _FakeRouterFallbackDeterministicThenRawText:
    primary = None

    class _FallbackEndpoint:
        url = "http://ollama:11434"

    fallback = _FallbackEndpoint()

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(
        self,
        prompt: str,  # noqa: ARG002
        output_schema: dict[str, Any] | None = None,  # noqa: ARG002
        schema_name: str = "response",  # noqa: ARG002
        system_prompt: str | None = None,  # noqa: ARG002
    ) -> tuple[dict[str, Any] | None, str]:
        self.calls += 1
        if self.calls == 1:
            return None, "deterministic"
        return {
            "_raw_text": (
                "Сформирован предварительный клинический комментарий.\n"
                "Требуется уточнение данных перед выбором следующего шага."
            )
        }, "fallback"


def test_doctor_report_uses_strict_llm_payload_when_valid():
    router = _FakeRouterPrimaryOk()
    report, path, fallback_reason = build_doctor_report_with_fallback(
        kb_version="kb_test",
        diff_issues=[],
        retrieved_chunks=[_retrieved_chunk()],
        llm_router=router,  # type: ignore[arg-type]
    )
    assert path == "llm_primary"
    assert fallback_reason is None
    assert report["summary"]
    assert "Выявлено" in report["summary"]
    assert report["issues"][0]["chunk_ids"] == ["c1"]
    assert report["issues"][0]["title"] == "Клиническое замечание"
    assert report["issues"][0]["description"] == "Требуется уточнение клинического шага."
    assert router.calls
    assert router.calls[0]["schema_name"] == "doctor_report_v2"
    assert isinstance(router.calls[0]["output_schema"], dict)


def test_doctor_report_falls_back_when_strict_payload_is_invalid():
    report, path, fallback_reason = build_doctor_report_with_fallback(
        kb_version="kb_test",
        diff_issues=[],
        retrieved_chunks=[_retrieved_chunk()],
        llm_router=_FakeRouterPrimaryInvalid(),  # type: ignore[arg-type]
    )
    assert path == "deterministic"
    assert fallback_reason == "llm_invalid_response"
    assert report["issues"]


def test_doctor_report_marks_llm_fallback_when_fallback_payload_is_invalid():
    report, path, fallback_reason = build_doctor_report_with_fallback(
        kb_version="kb_test",
        diff_issues=[],
        retrieved_chunks=[_retrieved_chunk()],
        llm_router=_FakeRouterFallbackInvalid(),  # type: ignore[arg-type]
    )
    assert path == "llm_fallback"
    assert fallback_reason == "llm_invalid_response"
    assert report["issues"]


def test_doctor_report_coerces_partial_fallback_payload_to_valid_issue_shape():
    report, path, fallback_reason = build_doctor_report_with_fallback(
        kb_version="kb_test",
        diff_issues=[],
        retrieved_chunks=[_retrieved_chunk()],
        llm_router=_FakeRouterFallbackPartiallyStructured(),  # type: ignore[arg-type]
    )
    assert path == "llm_fallback"
    assert fallback_reason is None
    assert report["issues"]
    first_issue = report["issues"][0]
    assert first_issue["severity"] in {"critical", "important", "note"}
    assert first_issue["chunk_ids"]
    assert report["missing_data"] == [{"field": "ECOG", "reason": "Не указан статус."}]


def test_doctor_report_schema_requires_all_issue_fields_for_strict_mode():
    issue_schema = (
        DOCTOR_REPORT_OUTPUT_SCHEMA["properties"]["issues"]["items"]  # type: ignore[index]
    )
    required = set(issue_schema["required"])  # type: ignore[index]
    properties = set(issue_schema["properties"].keys())  # type: ignore[index]
    assert required == properties


def test_doctor_report_coerces_raw_text_fallback_payload() -> None:
    report, path, fallback_reason = build_doctor_report_with_fallback(
        kb_version="kb_test",
        diff_issues=[],
        retrieved_chunks=[_retrieved_chunk()],
        llm_router=_FakeRouterFallbackRawTextRich(),  # type: ignore[arg-type]
    )
    assert path == "llm_fallback"
    assert fallback_reason is None
    assert report["summary"]
    assert report["issues"]


def test_doctor_report_retries_local_fallback_with_rescue_prompt() -> None:
    router = _FakeRouterFallbackDeterministicThenRawText()
    report, path, fallback_reason = build_doctor_report_with_fallback(
        kb_version="kb_test",
        diff_issues=[],
        retrieved_chunks=[_retrieved_chunk()],
        llm_router=router,  # type: ignore[arg-type]
    )
    assert router.calls >= 2
    assert path == "llm_fallback"
    assert fallback_reason is None
    assert report["issues"]


def test_doctor_report_fail_closed_requires_primary_llm() -> None:
    with pytest.raises(RuntimeError, match="strict_full requires configured LLM provider"):
        build_doctor_report_with_fallback(
            kb_version="kb_test",
            diff_issues=[],
            retrieved_chunks=[_retrieved_chunk()],
            llm_router=type("NoRouter", (), {"primary": None, "fallback": None})(),  # type: ignore[arg-type]
            fail_closed=True,
        )


def test_doctor_report_fail_closed_rejects_invalid_llm_response() -> None:
    with pytest.raises(RuntimeError, match="fail-closed mode"):
        build_doctor_report_with_fallback(
            kb_version="kb_test",
            diff_issues=[],
            retrieved_chunks=[_retrieved_chunk()],
            llm_router=_FakeRouterPrimaryInvalid(),  # type: ignore[arg-type]
            fail_closed=True,
        )


def test_doctor_report_strict_llm_only_rejects_invalid_primary_payload_without_coercion() -> None:
    with pytest.raises(RuntimeError, match="invalid response"):
        build_doctor_report_with_fallback(
            kb_version="kb_test",
            diff_issues=[],
            retrieved_chunks=[_retrieved_chunk()],
            llm_router=_FakeRouterPrimaryOk(),  # type: ignore[arg-type]
            strict_llm_only=True,
        )


def test_doctor_report_strict_llm_only_accepts_primary_only_router_and_returns_primary_path() -> None:
    report, path, fallback_reason = build_doctor_report_with_fallback(
        kb_version="kb_test",
        diff_issues=[],
        retrieved_chunks=[_retrieved_chunk()],
        llm_router=_FakeRouterPrimaryStrictValid(),  # type: ignore[arg-type]
        strict_llm_only=True,
    )
    assert path == "llm_primary"
    assert fallback_reason is None
    assert report["summary"] == "Строгий отчёт LLM."
    assert report["issues"][0]["title"] == "Potential mismatch"


def test_doctor_report_strict_llm_only_requires_primary_provider() -> None:
    with pytest.raises(RuntimeError, match="primary LLM provider"):
        build_doctor_report_with_fallback(
            kb_version="kb_test",
            diff_issues=[],
            retrieved_chunks=[_retrieved_chunk()],
            llm_router=_FakeRouterFallbackInvalid(),  # type: ignore[arg-type]
            strict_llm_only=True,
        )
