from __future__ import annotations

import pytest

from backend.app.exceptions import ValidationError
from backend.app.schemas.contracts import (
    validate_analyze_request,
    validate_analyze_response,
    validate_external_compatibility_projections,
)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": "0.1",
            "case": {"cancer_type": "nsclc_egfr", "language": "ru"},
            "treatment_plan": {"plan_text": "Осимертиниб 80 мг"},
        }
    ],
)
def test_validate_analyze_request_accepts_minimal_payload(payload):
    validate_analyze_request(payload)


def test_validate_analyze_request_accepts_v0_2_payload():
    validate_analyze_request(
        {
            "schema_version": "0.2",
            "request_id": "v02-001",
            "case": {
                "cancer_type": "nsclc_egfr",
                "language": "ru",
                "patient": {"sex": "female", "age": 62},
                "diagnosis": {"stage": "IV", "histology": "adenocarcinoma"},
                "biomarkers": [{"name": "EGFR", "value": "L858R"}],
                "comorbidities": ["hypertension"],
                "contraindications": ["none"],
            },
            "treatment_plan": {
                "plan_text": "Осимертиниб 80 мг ежедневно",
                "plan_structured": [{"step_type": "systemic_therapy", "name": "osimertinib"}],
            },
        }
    )


def test_validate_analyze_request_rejects_invalid_payload():
    with pytest.raises(ValidationError):
        validate_analyze_request({"schema_version": "0.1"})


def test_validate_analyze_response_rejects_missing_doctor_report():
    with pytest.raises(ValidationError):
        validate_analyze_response({})


def test_validate_analyze_response_accepts_v0_2_with_run_meta():
    validate_analyze_response(
        {
            "doctor_report": {
                "schema_version": "0.2",
                "report_id": "rep-1",
                "kb_version": "kb_test",
                "summary": "ok",
                "issues": [],
                "missing_data": [],
            },
            "patient_explain": {
                "schema_version": "0.2",
                "kb_version": "kb_test",
                "based_on_report_id": "rep-1",
                "summary": "safe",
                "key_points": ["a"],
                "questions_to_ask_doctor": ["b"],
                "safety_disclaimer": "c",
            },
            "run_meta": {
                "retrieval_k": 0,
                "rerank_n": 0,
                "llm_path": "deterministic",
                "latency_ms_total": 12.5,
                "kb_version": "kb_test",
                "vector_backend": "local",
                "embedding_backend": "hash",
                "reranker_backend": "lexical",
                "report_generation_path": "deterministic",
                "retrieval_engine": "basic",
                "reasoning_mode": "compat",
            },
        }
    )


def test_validate_analyze_response_rejects_v0_2_without_run_meta():
    with pytest.raises(ValidationError):
        validate_analyze_response(
            {
                "doctor_report": {
                    "schema_version": "0.2",
                    "report_id": "rep-1",
                    "kb_version": "kb_test",
                    "summary": "ok",
                    "issues": [],
                    "missing_data": [],
                }
            }
        )


def test_validate_analyze_response_rejects_v0_2_run_meta_without_backend_paths():
    with pytest.raises(ValidationError):
        validate_analyze_response(
            {
                "doctor_report": {
                    "schema_version": "0.2",
                    "report_id": "rep-1",
                    "kb_version": "kb_test",
                    "summary": "ok",
                    "issues": [],
                    "missing_data": [],
                },
                "run_meta": {
                    "retrieval_k": 0,
                    "rerank_n": 0,
                    "llm_path": "deterministic",
                    "latency_ms_total": 10.0,
                    "kb_version": "kb_test",
                },
            }
        )


def test_validate_analyze_response_accepts_optional_fallback_reason():
    validate_analyze_response(
        {
            "doctor_report": {
                "schema_version": "0.2",
                "report_id": "rep-1",
                "kb_version": "kb_test",
                "summary": "ok",
                "issues": [],
                "missing_data": [],
            },
            "run_meta": {
                "retrieval_k": 0,
                "rerank_n": 0,
                "llm_path": "deterministic",
                "latency_ms_total": 10.0,
                "kb_version": "kb_test",
                "vector_backend": "local",
                "embedding_backend": "hash",
                "reranker_backend": "lexical",
                "report_generation_path": "deterministic",
                "fallback_reason": "llm_not_configured",
                "retrieval_engine": "basic",
                "reasoning_mode": "compat",
            },
        }
    )


def test_validate_analyze_response_rejects_v0_2_run_meta_without_v0_3_fields():
    with pytest.raises(ValidationError):
        validate_analyze_response(
            {
                "doctor_report": {
                    "schema_version": "0.2",
                    "report_id": "rep-1",
                    "kb_version": "kb_test",
                    "summary": "ok",
                    "issues": [],
                    "missing_data": [],
                },
                "run_meta": {
                    "retrieval_k": 0,
                    "rerank_n": 0,
                    "llm_path": "deterministic",
                    "latency_ms_total": 10.0,
                    "kb_version": "kb_test",
                    "vector_backend": "local",
                    "embedding_backend": "hash",
                    "reranker_backend": "lexical",
                },
            }
        )


def test_validate_analyze_response_accepts_pack_v1_2_report() -> None:
    validate_analyze_response(
        {
            "schema_version": "0.2",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "doctor_report": {
                "schema_version": "1.2",
                "report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
                "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
                "query_type": "NEXT_STEPS",
                "disease_context": {"disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e"},
                "case_facts": {},
                "timeline": [],
                "consilium_md": "## Ключевые клинические факты\n- нет",
                "plan": [
                    {
                        "section": "treatment",
                        "title": "План",
                        "steps": [
                            {
                                "step_id": "a6e1cb0b-9e8a-4578-8308-82b25b73f381",
                                "text": "Контрольный этап",
                                "priority": "high",
                                "rationale": "Тест",
                                "citation_ids": ["83b5c681-3a75-5a79-8186-9d3b7496f5cb"],
                                "depends_on_missing_data": [],
                            }
                        ],
                    }
                ],
                "issues": [],
                "sanity_checks": [],
                "drug_safety": {
                    "status": "unavailable",
                    "extracted_inn": [],
                    "unresolved_candidates": [],
                    "profiles": [],
                    "signals": [],
                    "warnings": [],
                },
                "citations": [
                    {
                        "citation_id": "83b5c681-3a75-5a79-8186-9d3b7496f5cb",
                        "source_id": "minzdrav",
                        "document_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                        "version_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                        "page_start": 1,
                        "page_end": 1,
                        "section_path": "Тест",
                        "quote": "Тестовая цитата",
                        "file_uri": "about:blank",
                        "official_page_url": "https://cr.minzdrav.gov.ru/preview-cr/237_6",
                        "official_pdf_url": "https://cr.minzdrav.gov.ru/preview-cr/237_6/КР237_6.pdf",
                        "score": 0.5,
                    }
                ],
                "generated_at": "2026-02-21T10:00:00Z",
            },
            "patient_explain": {
                "schema_version": "1.2",
                "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
                "summary_plain": "Краткое объяснение",
                "key_points": ["Пункт"],
                "questions_for_doctor": ["Вопрос"],
                "what_was_checked": ["Проверено"],
                "safety_notes": ["Не менять лечение без врача"],
                "drug_safety": {
                    "status": "unavailable",
                    "important_risks": [],
                    "questions_for_doctor": [],
                },
                "sources_used": ["minzdrav"],
                "generated_at": "2026-02-21T10:00:00Z",
            },
            "run_meta": {
                "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
                "schema_version": "0.2",
                "timings_ms": {"total": 10, "retrieval": 2, "llm": 4, "postprocess": 4},
                "docs_retrieved_count": 0,
                "docs_after_filter_count": 0,
                "citations_count": 1,
                "evidence_valid_ratio": 1.0,
                "retrieval_engine": "basic",
                "reasoning_mode": "compat",
                "llm_path": "deterministic",
                "vector_backend": "local",
                "embedding_backend": "hash",
                "reranker_backend": "lexical",
                "report_generation_path": "deterministic_only",
                "fallback_reason": "none",
            },
        }
    )


def test_validate_analyze_response_accepts_verification_summary() -> None:
    payload = {
        "schema_version": "0.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "doctor_report": {
            "schema_version": "1.2",
            "report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "query_type": "NEXT_STEPS",
            "disease_context": {"disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e"},
            "case_facts": {},
            "timeline": [],
            "consilium_md": "## Ключевые клинические факты\n- нет",
            "plan": [],
            "issues": [],
            "sanity_checks": [],
            "drug_safety": {
                "status": "unavailable",
                "extracted_inn": [],
                "unresolved_candidates": [],
                "profiles": [],
                "signals": [],
                "warnings": [],
            },
            "verification_summary": {
                "category": "OK",
                "status_line": "Текущая тактика соответствует критериям.",
                "counts": {"ok": 2, "not_compliant": 0, "needs_data": 0, "risk": 0},
            },
            "citations": [],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "patient_explain": {
            "schema_version": "1.2",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "summary_plain": "Краткое объяснение",
            "key_points": ["Пункт"],
            "questions_for_doctor": ["Вопрос"],
            "what_was_checked": ["Проверено"],
            "safety_notes": ["Не менять лечение без врача"],
            "drug_safety": {
                "status": "unavailable",
                "important_risks": [],
                "questions_for_doctor": [],
            },
            "sources_used": ["minzdrav"],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "run_meta": {
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "schema_version": "0.2",
            "timings_ms": {"total": 10, "retrieval": 2, "llm": 4, "postprocess": 4},
            "docs_retrieved_count": 0,
            "docs_after_filter_count": 0,
            "citations_count": 0,
            "evidence_valid_ratio": 1.0,
            "retrieval_engine": "basic",
            "reasoning_mode": "compat",
            "llm_path": "deterministic",
            "vector_backend": "local",
            "embedding_backend": "hash",
            "reranker_backend": "lexical",
            "report_generation_path": "deterministic_only",
            "fallback_reason": "none",
        },
    }
    validate_analyze_response(payload)


def test_validate_analyze_response_rejects_invalid_citation_official_urls() -> None:
    payload = {
        "schema_version": "0.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "doctor_report": {
            "schema_version": "1.2",
            "report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "query_type": "NEXT_STEPS",
            "disease_context": {"disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e"},
            "case_facts": {},
            "timeline": [],
            "consilium_md": "## Ключевые клинические факты\n- нет",
            "plan": [
                {
                    "section": "treatment",
                    "title": "План",
                    "steps": [
                        {
                            "step_id": "a6e1cb0b-9e8a-4578-8308-82b25b73f381",
                            "text": "Контрольный этап",
                            "priority": "high",
                            "rationale": "Тест",
                            "citation_ids": ["83b5c681-3a75-5a79-8186-9d3b7496f5cb"],
                            "depends_on_missing_data": [],
                        }
                    ],
                }
            ],
            "issues": [],
            "sanity_checks": [],
            "drug_safety": {
                "status": "unavailable",
                "extracted_inn": [],
                "unresolved_candidates": [],
                "profiles": [],
                "signals": [],
                "warnings": [],
            },
            "citations": [
                {
                    "citation_id": "83b5c681-3a75-5a79-8186-9d3b7496f5cb",
                    "source_id": "minzdrav",
                    "document_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "version_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "page_start": 1,
                    "page_end": 1,
                    "file_uri": "about:blank",
                    "official_page_url": 123,
                }
            ],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "patient_explain": {
            "schema_version": "1.2",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "summary_plain": "Краткое объяснение",
            "key_points": ["Пункт"],
            "questions_for_doctor": ["Вопрос"],
            "what_was_checked": ["Проверено"],
            "safety_notes": ["Не менять лечение без врача"],
            "drug_safety": {
                "status": "unavailable",
                "important_risks": [],
                "questions_for_doctor": [],
            },
            "sources_used": ["minzdrav"],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "run_meta": {
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "schema_version": "0.2",
            "timings_ms": {"total": 10, "retrieval": 2, "llm": 4, "postprocess": 4},
            "docs_retrieved_count": 0,
            "docs_after_filter_count": 0,
            "citations_count": 1,
            "evidence_valid_ratio": 1.0,
            "retrieval_engine": "basic",
            "reasoning_mode": "compat",
            "llm_path": "deterministic",
            "vector_backend": "local",
            "embedding_backend": "hash",
            "reranker_backend": "lexical",
            "report_generation_path": "deterministic_only",
            "fallback_reason": "none",
        },
    }
    with pytest.raises(ValidationError, match="citation.official_page_url invalid"):
        validate_analyze_response(payload)


def test_validate_external_compatibility_projections_accepts_valid_payloads() -> None:
    validation = validate_external_compatibility_projections(
        doctor_projection_v1_1={
            "schema_version": "1.1",
            "report_id": "rep-1",
            "request_id": "req-1",
            "kb_version": "kb-1",
            "clinical_summary": "Краткое резюме",
            "disease_context": {"cancer_type": "gastric_cancer"},
            "treatment_history": [],
            "current_plan": {"description": "Продолжить лечение"},
            "issues": [],
            "missing_data": [],
            "run_meta": {},
        },
        patient_projection_alt={
            "schema_version": "1.2",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "based_on_report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
            "overall_interpretation": "Пояснение",
            "disease_explanation": "Описание",
            "stage_explanation": "Стадия требует обсуждения.",
            "treatment_strategy_explanation": "Стратегия зависит от результатов обследований.",
            "key_points": ["Пункт"],
            "questions_for_doctor": ["Вопрос"],
            "safety_note": "Этот текст носит информационный характер и не заменяет консультацию врача.",
            "generated_at": "2026-02-22T12:00:00Z",
        },
    )
    assert validation["doctor_report_v1_1"]["valid"] is True
    assert validation["patient_explain_alt"]["valid"] is True


def test_validate_analyze_response_rejects_pack_v1_0_without_compat_flag() -> None:
    payload = {
        "schema_version": "0.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "doctor_report": {
            "schema_version": "1.0",
            "report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "query_type": "NEXT_STEPS",
            "disease_context": {"disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e"},
            "plan": [
                {
                    "section": "treatment",
                    "title": "План",
                    "steps": [
                        {
                            "step_id": "a6e1cb0b-9e8a-4578-8308-82b25b73f381",
                            "text": "Контрольный этап",
                            "priority": "high",
                            "rationale": "Тест",
                            "citation_ids": ["83b5c681-3a75-5a79-8186-9d3b7496f5cb"],
                            "depends_on_missing_data": [],
                        }
                    ],
                }
            ],
            "issues": [],
            "citations": [
                {
                    "citation_id": "83b5c681-3a75-5a79-8186-9d3b7496f5cb",
                    "source_id": "minzdrav",
                    "document_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "version_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "page_start": 1,
                    "page_end": 1,
                    "section_path": "Тест",
                    "quote": "Тестовая цитата",
                    "file_uri": "about:blank",
                    "score": 0.5,
                }
            ],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "patient_explain": {
            "schema_version": "1.0",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "summary_plain": "Краткое объяснение",
            "key_points": ["Пункт"],
            "questions_for_doctor": ["Вопрос"],
            "what_was_checked": ["Проверено"],
            "safety_notes": ["Не менять лечение без врача"],
            "sources_used": ["minzdrav"],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "run_meta": {
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "schema_version": "0.2",
            "timings_ms": {"total": 10, "retrieval": 2, "llm": 4, "postprocess": 4},
            "docs_retrieved_count": 0,
            "docs_after_filter_count": 0,
            "citations_count": 1,
            "evidence_valid_ratio": 1.0,
            "retrieval_engine": "basic",
            "reasoning_mode": "compat",
            "llm_path": "deterministic",
            "vector_backend": "local",
            "embedding_backend": "hash",
            "reranker_backend": "lexical",
            "report_generation_path": "deterministic_only",
            "fallback_reason": "none",
        },
    }
    with pytest.raises(ValidationError, match="doctor_report.schema_version must be 1.2"):
        validate_analyze_response(payload)


def test_validate_analyze_response_accepts_pack_v1_0_with_compat_flag() -> None:
    payload = {
        "schema_version": "0.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "doctor_report": {
            "schema_version": "1.0",
            "report_id": "f0428d95-6df3-4b8f-b18c-5978c954ea8f",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "query_type": "NEXT_STEPS",
            "disease_context": {"disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e"},
            "plan": [
                {
                    "section": "treatment",
                    "title": "План",
                    "steps": [
                        {
                            "step_id": "a6e1cb0b-9e8a-4578-8308-82b25b73f381",
                            "text": "Контрольный этап",
                            "priority": "high",
                            "rationale": "Тест",
                            "citation_ids": ["83b5c681-3a75-5a79-8186-9d3b7496f5cb"],
                            "depends_on_missing_data": [],
                        }
                    ],
                }
            ],
            "issues": [],
            "citations": [
                {
                    "citation_id": "83b5c681-3a75-5a79-8186-9d3b7496f5cb",
                    "source_id": "minzdrav",
                    "document_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "version_id": "c9d63720-a6cd-5d9f-af74-601f00687e84",
                    "page_start": 1,
                    "page_end": 1,
                    "section_path": "Тест",
                    "quote": "Тестовая цитата",
                    "file_uri": "about:blank",
                    "score": 0.5,
                }
            ],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "patient_explain": {
            "schema_version": "1.0",
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "summary_plain": "Краткое объяснение",
            "key_points": ["Пункт"],
            "questions_for_doctor": ["Вопрос"],
            "what_was_checked": ["Проверено"],
            "safety_notes": ["Не менять лечение без врача"],
            "sources_used": ["minzdrav"],
            "generated_at": "2026-02-21T10:00:00Z",
        },
        "run_meta": {
            "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
            "schema_version": "0.2",
            "timings_ms": {"total": 10, "retrieval": 2, "llm": 4, "postprocess": 4},
            "docs_retrieved_count": 0,
            "docs_after_filter_count": 0,
            "citations_count": 1,
            "evidence_valid_ratio": 1.0,
            "retrieval_engine": "basic",
            "reasoning_mode": "compat",
            "llm_path": "deterministic",
            "vector_backend": "local",
            "embedding_backend": "hash",
            "reranker_backend": "lexical",
            "report_generation_path": "deterministic_only",
            "fallback_reason": "none",
        },
    }
    validate_analyze_response(payload, allow_pack_legacy_v1_0=True)
