from __future__ import annotations

import base64
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.exceptions import ValidationError
from backend.app.service import OncoService


def make_settings(
    root: Path,
    *,
    llm_probe_enabled: bool = False,
    rag_engine: str = "basic",
    reasoning_mode: str = "compat",
) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=10,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
        llm_probe_enabled=llm_probe_enabled,
        rag_engine=rag_engine,
        reasoning_mode=reasoning_mode,
    )


def test_service_analyze_and_report_roundtrip(tmp_path):
    service = OncoService(make_settings(tmp_path))

    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"synthetic guideline content for nsclc",
        metadata={
            "doc_id": "guideline_nsclc",
            "doc_version": "2025-11",
            "source_set": "mvp_guidelines_ru_2025",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
        },
    )
    service.admin_reindex(role="admin")

    payload = {
        "schema_version": "0.1",
        "request_id": "demo-001",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "notes": "Синтетический кейс",
        },
        "treatment_plan": {
            "plan_text": "Системная терапия: осимертиниб 80 мг ежедневно",
        },
        "return_patient_explain": True,
    }

    response = service.analyze(payload=payload, role="clinician", client_id="smoke")
    assert "doctor_report" in response
    assert response["doctor_report"]["issues"]

    report_id = response["doctor_report"]["report_id"]
    report_json = service.report_json(role="clinician", report_id=report_id)
    assert report_json["doctor_report"]["report_id"] == report_id

    html = service.report_html(role="clinician", report_id=report_id)
    assert "Doctor Report" in html


def test_summary_reflects_visible_issues_when_evidence_is_missing(tmp_path):
    service = OncoService(make_settings(tmp_path))
    payload = {
        "schema_version": "0.1",
        "request_id": "demo-no-kb",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "notes": "Синтетический кейс",
        },
        "treatment_plan": {
            "plan_text": "Системная терапия: осимертиниб 80 мг ежедневно",
        },
        "return_patient_explain": True,
    }

    response = service.analyze(payload=payload, role="clinician", client_id="summary-check")
    assert response["doctor_report"]["issues"] == []
    assert "Выявлено 0 потенциальных замечаний" in response["doctor_report"]["summary"]


def test_analyze_v0_2_returns_run_meta_and_insufficient_data(tmp_path):
    service = OncoService(make_settings(tmp_path))
    payload = {
        "schema_version": "0.2",
        "request_id": "demo-v02",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "patient": {"sex": "female", "age": 62},
            "diagnosis": {"stage": "IV"},
            "biomarkers": [{"name": "EGFR", "value": "L858R"}],
            "comorbidities": [],
            "contraindications": [],
            "notes": "Синтетический кейс",
        },
        "treatment_plan": {
            "plan_text": "Осимертиниб 80 мг ежедневно",
            "plan_structured": [{"step_type": "systemic_therapy", "name": "osimertinib"}],
        },
        "return_patient_explain": True,
    }

    response = service.analyze(payload=payload, role="clinician", client_id="v02-check")
    assert response["doctor_report"]["schema_version"] == "0.2"
    assert response["patient_explain"]["schema_version"] == "0.2"
    assert response["run_meta"]["retrieval_k"] == 0
    assert response["run_meta"]["rerank_n"] == 0
    assert response["run_meta"]["llm_path"] in {"deterministic", "primary", "fallback"}
    assert response["run_meta"]["latency_ms_total"] >= 0
    assert response["run_meta"]["vector_backend"] in {"local", "qdrant"}
    assert response["run_meta"]["embedding_backend"] in {"hash", "openai"}
    assert response["run_meta"]["reranker_backend"] in {"lexical", "llm"}
    assert response["run_meta"]["report_generation_path"] in {"llm_primary", "llm_fallback", "deterministic"}
    assert response["run_meta"]["retrieval_engine"] in {"basic", "llamaindex"}
    assert response["run_meta"].get("fallback_reason") == "llm_not_configured"
    assert response["meta"]["execution_profile"] == "compat"
    assert response["meta"]["strict_mode"] is False
    assert response["insufficient_data"]["status"] is True


def test_analyze_v0_2_with_kb_has_positive_retrieval_and_no_insufficient_flag(tmp_path):
    service = OncoService(make_settings(tmp_path))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"synthetic guideline content with osimertinib and diagnostic confirmation requirements",
        metadata={
            "doc_id": "guideline_nsclc",
            "doc_version": "2025-11",
            "source_set": "mvp_guidelines_ru_2025",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
        },
    )
    service.admin_reindex(role="admin")

    payload = {
        "schema_version": "0.2",
        "request_id": "demo-v02-kb",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "patient": {"sex": "female", "age": 62},
            "diagnosis": {"stage": "IV"},
            "biomarkers": [{"name": "EGFR", "value": "L858R"}],
            "comorbidities": [],
            "contraindications": [],
            "notes": "Синтетический кейс",
        },
        "treatment_plan": {
            "plan_text": "Диагностический контроль и системная терапия: осимертиниб 80 мг ежедневно",
            "plan_structured": [
                {"step_type": "diagnostic", "name": "КТ грудной клетки"},
                {"step_type": "systemic_therapy", "name": "Осимертиниб"},
            ],
        },
        "return_patient_explain": True,
    }

    response = service.analyze(payload=payload, role="clinician", client_id="v02-kb-check")
    assert response["run_meta"]["retrieval_k"] > 0
    assert response["run_meta"]["rerank_n"] > 0
    assert response["insufficient_data"]["status"] is False


def test_report_html_handles_v1_2_issues_with_summary_details_shape(tmp_path):
    service = OncoService(make_settings(tmp_path))
    report_id = "report-v1-2-issue-shape"
    payload = {
        "request_id": "req-v1-2-issue-shape",
        "doctor_report": {
            "schema_version": "1.2",
            "report_id": report_id,
            "summary": "summary text",
            "issues": [
                {
                    "severity": "warn",
                    "summary": "legacy summary field",
                    "details": "legacy details field",
                }
            ],
        },
    }
    service.store.save_report(report_id=report_id, payload=payload, created_at="2026-02-21T00:00:00Z")

    html = service.report_html(role="clinician", report_id=report_id)

    assert "legacy summary field" in html
    assert "legacy details field" in html
    assert "KB: unknown" in html


def test_analyze_skips_llm_probe_by_default(tmp_path, monkeypatch):
    service = OncoService(make_settings(tmp_path))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"synthetic guideline content with osimertinib",
        metadata={
            "doc_id": "guideline_nsclc",
            "doc_version": "2025-11",
            "source_set": "mvp_guidelines_ru_2025",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
        },
    )
    service.admin_reindex(role="admin")

    def _fail_if_called(prompt: str):  # noqa: ARG001
        raise AssertionError("llm probe should be disabled by default")

    monkeypatch.setattr(service.llm_router, "generate_json", _fail_if_called)

    payload = {
        "schema_version": "0.2",
        "request_id": "probe-default-off",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "patient": {"sex": "female"},
            "diagnosis": {"stage": "IV"},
            "biomarkers": [],
            "comorbidities": [],
            "contraindications": [],
            "notes": "Синтетический кейс",
        },
        "treatment_plan": {
            "plan_text": "Осимертиниб 80 мг ежедневно",
            "plan_structured": [{"step_type": "systemic_therapy", "name": "osimertinib"}],
        },
        "return_patient_explain": True,
    }
    response = service.analyze(payload=payload, role="clinician", client_id="probe-default-off")
    assert response["run_meta"]["llm_path"] == "deterministic"
    assert response["run_meta"]["report_generation_path"] in {"llm_primary", "llm_fallback", "deterministic"}
    assert response["run_meta"]["retrieval_engine"] in {"basic", "llamaindex"}


def test_analyze_calls_llm_probe_when_enabled(tmp_path, monkeypatch):
    service = OncoService(make_settings(tmp_path, llm_probe_enabled=True))
    calls = {"n": 0}

    def _record_call(prompt: str, **_: object):  # noqa: ARG001
        calls["n"] += 1
        return None, "deterministic"

    monkeypatch.setattr(service.llm_router, "generate_json", _record_call)
    monkeypatch.setattr(service.llm_router, "fallback", object())

    payload = {
        "schema_version": "0.2",
        "request_id": "probe-enabled",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "patient": {"sex": "female"},
            "diagnosis": {"stage": "IV"},
            "biomarkers": [],
            "comorbidities": [],
            "contraindications": [],
            "notes": "Синтетический кейс",
        },
        "treatment_plan": {
            "plan_text": "Осимертиниб 80 мг ежедневно",
            "plan_structured": [{"step_type": "systemic_therapy", "name": "osimertinib"}],
        },
        "return_patient_explain": True,
    }
    response = service.analyze(payload=payload, role="clinician", client_id="probe-enabled")
    assert calls["n"] >= 1
    assert response["run_meta"]["llm_path"] == "deterministic"
    assert response["run_meta"]["report_generation_path"] in {"llm_primary", "llm_fallback", "deterministic"}
    assert response["run_meta"]["retrieval_engine"] in {"basic", "llamaindex"}


def test_analyze_falls_back_to_basic_retrieval_engine_when_llamaindex_missing(tmp_path):
    service = OncoService(make_settings(tmp_path, rag_engine="llamaindex"))
    payload = {
        "schema_version": "0.2",
        "request_id": "rag-engine-fallback",
        "case": {
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "patient": {"sex": "female"},
            "diagnosis": {"stage": "IV"},
            "biomarkers": [],
            "comorbidities": [],
            "contraindications": [],
            "notes": "Синтетический кейс",
        },
        "treatment_plan": {
            "plan_text": "Осимертиниб 80 мг ежедневно",
            "plan_structured": [{"step_type": "systemic_therapy", "name": "osimertinib"}],
        },
        "return_patient_explain": True,
    }
    response = service.analyze(payload=payload, role="clinician", client_id="rag-engine-fallback")
    assert response["run_meta"]["retrieval_engine"] == "basic"
    assert "llamaindex_unavailable" in response["run_meta"].get("fallback_reason", "")


def test_service_skips_public_openai_llm_endpoint_without_api_key():
    endpoint = OncoService._build_llm_endpoint(
        url="https://api.openai.com",
        model="gpt-4o-mini",
        api_key="",
    )
    assert endpoint is None


def test_service_allows_local_llm_endpoint_without_api_key():
    endpoint = OncoService._build_llm_endpoint(
        url="http://vllm:8001",
        model="Qwen/Qwen2.5-7B-Instruct",
        api_key="",
    )
    assert endpoint is not None


def test_resolve_run_meta_llm_path_uses_generation_path_when_probe_is_deterministic() -> None:
    assert OncoService._resolve_run_meta_llm_path("deterministic", "llm_primary") == "primary"
    assert OncoService._resolve_run_meta_llm_path("deterministic", "llm_fallback") == "fallback"
    assert OncoService._resolve_run_meta_llm_path("deterministic", "deterministic") == "deterministic"


def test_infer_cancer_type_from_case_text_gastric() -> None:
    inferred = OncoService._infer_cancer_type(
        explicit_cancer_type="unknown",
        case_text="Диагноз: аденокарцинома желудка, кардиоэзофагеальный переход, стадия IV.",
    )
    assert inferred == "gastric_cancer"


def test_infer_cancer_type_overrides_conflicting_explicit_route() -> None:
    inferred = OncoService._infer_cancer_type(
        explicit_cancer_type="breast_hr+/her2-",
        case_text="Клинический диагноз: рак желудка (cT4N2M1), аденокарцинома желудка.",
    )
    assert inferred == "gastric_cancer"


def test_build_case_text_for_casefacts_strips_embedded_reference_block() -> None:
    text = OncoService._build_case_text_for_casefacts(
        normalized_payload={
            "case": {
                "notes": (
                    "Клиническая часть кейса: pT3N2M0, XELOX, операция Льюиса, R1.\n"
                    "Рекомендация AI-помощника:\n"
                    "Иммунотерапия при активном аутоиммунном заболевании требует отдельного консилиума."
                )
            },
            "treatment_plan": {"plan_text": "ramucirumab + paclitaxel"},
        },
        case_json=None,
    )
    assert "Клиническая часть кейса" in text
    assert "Рекомендация AI-помощника" not in text
    assert "аутоиммунном заболевании" not in text


def test_contraindication_issue_without_support_is_downgraded() -> None:
    issues = [
        {
            "severity": "critical",
            "kind": "contraindication",
            "summary": "Иммунотерапия при активном аутоиммунном заболевании требует отдельного консилиума.",
            "details": "Нужна оценка риска тяжелых осложнений.",
            "field_path": "case.comorbidity.autoimmune",
            "citation_ids": [],
        }
    ]
    guarded = OncoService._guard_pack_issues_against_support(
        issues=issues,
        case_facts={"initial_stage": {}, "current_stage": {}, "biomarkers": {}, "metastases": [], "treatment_history": [], "complications": []},
        citations=[],
    )
    assert len(guarded) == 1
    assert guarded[0]["kind"] == "inconsistency"
    assert guarded[0]["severity"] == "warning"


def _pack_case_json_for_tests() -> dict:
    return {
        "schema_version": "1.0",
        "case_id": str(uuid.uuid4()),
        "import_profile": "CUSTOM_TEMPLATE",
        "patient": {"sex": "female", "birth_year": 1970, "ecog": 1},
        "diagnoses": [
            {
                "diagnosis_id": str(uuid.uuid4()),
                "disease_id": str(uuid.uuid4()),
                "icd10": "C34.1",
                "histology": "adenocarcinoma",
                "stage": {"system": "TNM8", "stage_group": "IV"},
                "timeline": [{"date": "2025-01-10", "precision": "day", "type": "diagnostic", "label": "КТ", "details": "стадирование"}],
            }
        ],
        "attachments": [],
        "notes": "Синтетический кейс для теста.",
    }


def test_pack_sources_only_and_historical_are_returned(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = {
        "schema_version": "0.2",
        "request_id": str(uuid.uuid4()),
        "query_type": "NEXT_STEPS",
        "query_mode": "SOURCES_ONLY",
        "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
        "language": "ru",
        "as_of_date": "2025-01-01",
        "historical_assessment": True,
        "case": {"case_json": _pack_case_json_for_tests()},
    }
    response = service.analyze(payload=payload, role="clinician", client_id="pack-sources-only")
    assert response["sources_only_result"]["mode"] == "SOURCES_ONLY"
    assert isinstance(response["sources_only_result"]["items"], list)
    assert response["historical_assessment"]["requested_as_of_date"] == "2025-01-01"
    assert response["doctor_report"]["plan"] == []


def test_service_rejects_invalid_strict_release_profile_settings(tmp_path: Path) -> None:
    strict_settings = replace(
        make_settings(tmp_path),
        release_profile="strict_full",
    )
    with pytest.raises(ValidationError, match="STRICT_PROFILE_CONFIG_ERROR"):
        OncoService(strict_settings)


def test_service_accepts_strict_release_profile_when_required_backends_are_configured(tmp_path: Path) -> None:
    strict_settings = replace(
        make_settings(tmp_path),
        release_profile="strict_full",
        reasoning_mode="llm_rag_only",
        llm_generation_enabled=True,
        llm_primary_url="http://127.0.0.1:12345",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="strict-key",
        vector_backend="qdrant",
        qdrant_url="http://127.0.0.1:65534",
        embedding_backend="openai",
        embedding_url="http://127.0.0.1:12345",
        embedding_model="text-embedding-3-small",
        embedding_api_key="strict-embed-key",
        reranker_backend="llm",
    )
    service = OncoService(strict_settings)
    assert service._strict_fail_closed is True


def test_pack_historical_assessment_requires_as_of_date_when_requested(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = {
        "schema_version": "0.2",
        "request_id": str(uuid.uuid4()),
        "query_type": "NEXT_STEPS",
        "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
        "language": "ru",
        "historical_assessment": True,
        "case": {"case_json": _pack_case_json_for_tests()},
    }
    response = service.analyze(payload=payload, role="clinician", client_id="pack-historical-missing-date")
    historical = response["historical_assessment"]
    assert historical["status"] == "insufficient_data"
    assert historical["reason_code"] == "missing_as_of_date"


def test_pack_historical_assessment_detects_version_conflict_between_then_and_now(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    doc_id = "minzdrav_nsclc_hist"
    source_url = "https://cr.minzdrav.gov.ru/preview-cr/574_1"
    service.admin_upload(
        role="admin",
        filename="minzdrav-old.pdf",
        content=b"old guideline version for nsclc",
        metadata={
            "doc_id": doc_id,
            "doc_version": "2024",
            "source_set": "minzdrav",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "source_url": source_url,
        },
    )
    service.admin_upload(
        role="admin",
        filename="minzdrav-new.pdf",
        content=b"new guideline version for nsclc",
        metadata={
            "doc_id": doc_id,
            "doc_version": "2026",
            "source_set": "minzdrav",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "source_url": source_url,
        },
    )
    service.admin_reindex(role="admin")
    service.store.update_guideline_version_status(
        doc_id=doc_id,
        doc_version="2024",
        status="INDEXED",
        updated_at="2026-02-23T10:00:00Z",
        metadata_patch={
            "source_url": source_url,
            "doc_kind": "guideline",
            "valid_from": "2024-01-01",
            "valid_to": "2024-12-31",
        },
    )
    service.store.update_guideline_version_status(
        doc_id=doc_id,
        doc_version="2026",
        status="INDEXED",
        updated_at="2026-02-23T10:01:00Z",
        metadata_patch={
            "source_url": source_url,
            "doc_kind": "guideline",
            "valid_from": "2025-01-01",
            "valid_to": "",
        },
    )

    payload = {
        "schema_version": "0.2",
        "request_id": str(uuid.uuid4()),
        "query_type": "NEXT_STEPS",
        "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
        "language": "ru",
        "as_of_date": "2024-06-01",
        "historical_assessment": True,
        "case": {"case_json": _pack_case_json_for_tests()},
    }
    response = service.analyze(payload=payload, role="clinician", client_id="pack-historical-conflict")
    historical = response["historical_assessment"]
    assert historical["status"] == "ok"
    assert historical["reason_code"] == "ok"
    assert any(
        isinstance(item, dict)
        and item.get("type") == "version_changed"
        and item.get("doc_id") == doc_id
        for item in historical["conflicts"]
    )


def test_comparative_claim_policy_requires_pubmed() -> None:
    with pytest.raises(ValidationError):
        OncoService._validate_comparative_claims_policy(
            {
                "comparative_claims": [
                    {
                        "claim_id": str(uuid.uuid4()),
                        "text": "Regimen A is superior to regimen B.",
                        "comparative_superiority": True,
                        "citation_ids": [str(uuid.uuid4())],
                    }
                ]
            }
        )


def test_case_import_batch_builds_merged_case(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    first = base64.b64encode("Пациент, документ 1".encode("utf-8")).decode("ascii")
    second = base64.b64encode("Пациент, документ 2".encode("utf-8")).decode("ascii")
    result = service.case_import_batch_file_base64(
        role="clinician",
        payload={
            "files": [
                {"filename": "case1.txt", "content_base64": first, "mime_type": "text/plain"},
                {"filename": "case2.txt", "content_base64": second, "mime_type": "text/plain"},
            ],
            "data_mode": "DEID",
        },
    )
    assert result["total_files"] == 2
    assert result["successful_imports"] >= 1
    assert isinstance(result.get("runs"), list)
    merged_case_id = str(result.get("merged_case_id") or "")
    assert merged_case_id
    merged_case = service.get_case(role="clinician", case_id=merged_case_id)
    assert "Doc 1" in str(merged_case.get("notes") or "")


def test_report_pdf_and_docx_exports(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = {
        "schema_version": "0.1",
        "request_id": "export-001",
        "case": {"cancer_type": "nsclc_egfr", "language": "ru", "notes": "Тестовый кейс"},
        "treatment_plan": {"plan_text": "Тестовый план"},
        "return_patient_explain": True,
    }
    response = service.analyze(payload=payload, role="clinician", client_id="export-check")
    report_id = str(response["doctor_report"]["report_id"])
    pdf_bytes = service.report_pdf(role="clinician", report_id=report_id)
    docx_bytes = service.report_docx(role="clinician", report_id=report_id)
    assert pdf_bytes.startswith(b"%PDF")
    assert docx_bytes.startswith(b"PK")
