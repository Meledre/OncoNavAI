from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.schemas.analyze_bridge import normalize_analyze_request
from backend.app.config import Settings
from backend.app.exceptions import ValidationError
from backend.app.schemas.contracts import validate_analyze_request, validate_analyze_response
from backend.app.service import OncoService


def make_settings(
    root: Path,
    *,
    doctor_schema_v1_2_enabled: bool = True,
    casefacts_enabled: bool = True,
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
        llm_probe_enabled=False,
        rag_engine="basic",
        oncoai_doctor_schema_v1_2_enabled=doctor_schema_v1_2_enabled,
        oncoai_casefacts_enabled=casefacts_enabled,
        reasoning_mode=reasoning_mode,
    )


def build_pack_request() -> dict[str, object]:
    return {
        "schema_version": "0.2",
        "request_id": "e7ebf4f4-282e-54a2-9ecd-78222cee9887",
        "query_type": "CHECK_LAST_TREATMENT",
        "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
        "language": "ru",
        "case": {
            "case_json": {
                "schema_version": "1.0",
                "case_id": "9864b343-6a61-53b3-8e8c-3854d7e99452",
                "import_profile": "FREE_TEXT",
                "patient": {"sex": "male", "birth_year": 1973},
                "diagnoses": [
                    {
                        "diagnosis_id": "10db35a3-dd32-52a7-896b-afb323c197b7",
                        "disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e",
                        "icd10": "C16",
                        "histology": "adenocarcinoma",
                        "stage": {"system": "TNM8", "stage_group": "IV"},
                        "biomarkers": [
                            {"name": "HER2", "value": "positive"},
                            {"name": "PD-L1_CPS", "value": "10"},
                        ],
                        "timeline": [
                            {
                                "event_id": "ae0ba38a-e199-5ad1-8e01-11b77d25b423",
                                "date": "2026-01-05",
                                "precision": "day",
                                "type": "systemic_therapy",
                                "label": "Начата 1-я линия",
                                "details": "mFOLFOX6",
                            }
                        ],
                        "last_plan": {
                            "date": "2026-02-10",
                            "precision": "day",
                            "regimen": "mFOLFOX6",
                            "line": 1,
                            "cycle": 3,
                        },
                    }
                ],
                "attachments": [],
                "notes": "Кейс-демо: желудок, метастатический процесс.",
            }
        },
        "options": {"strict_evidence": True, "max_chunks": 40, "max_citations": 40, "timeout_ms": 120000},
    }


def _mark_release_ready(
    service: OncoService,
    *,
    doc_id: str,
    doc_version: str,
    source_url: str,
) -> None:
    service.store.update_guideline_version_status(
        doc_id=doc_id,
        doc_version=doc_version,
        status="INDEXED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata_patch={
            "source_url": source_url,
            "doc_kind": "guideline",
        },
    )


def test_validate_analyze_request_accepts_pack_v0_2_shape() -> None:
    validate_analyze_request(build_pack_request())


def test_validate_analyze_request_accepts_historical_reference_date_alias() -> None:
    payload = build_pack_request()
    payload["historical_reference_date"] = "2024-01-10"
    validate_analyze_request(payload)
    context = normalize_analyze_request(payload)
    assert context.as_of_date == "2024-01-10"
    assert context.historical_assessment is True


def test_pack_bridge_preserves_kb_filter_doc_ids() -> None:
    payload = build_pack_request()
    payload["kb_filters"] = {
        "doc_ids": ["kr_c16_minzdrav_2026", "kr_c16_russco_2026", "", None, 123],
    }
    context = normalize_analyze_request(payload)
    assert context.normalized_payload["kb_filters"]["doc_ids"] == [
        "kr_c16_minzdrav_2026",
        "kr_c16_russco_2026",
        "123",
    ]


def test_service_analyze_pack_v0_2_returns_pack_response(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = build_pack_request()

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02")

    validate_analyze_response(response)
    assert response["schema_version"] == "0.2"
    assert response["request_id"] == payload["request_id"]
    assert response["doctor_report"]["schema_version"] == "1.2"
    assert response["doctor_report"]["request_id"] == payload["request_id"]
    assert response["patient_explain"]["schema_version"] == "1.2"
    assert response["patient_explain"]["request_id"] == payload["request_id"]
    assert isinstance(response["doctor_report"]["case_facts"], dict)
    assert isinstance(response["doctor_report"]["timeline"], list)
    assert isinstance(response["doctor_report"]["consilium_md"], str)
    assert isinstance(response["doctor_report"].get("summary_md"), str)
    assert response["doctor_report"]["summary_md"]
    assert "## Входные данные" in response["doctor_report"]["summary_md"]
    assert isinstance(response["doctor_report"]["sanity_checks"], list)
    assert isinstance(response["doctor_report"]["drug_safety"], dict)
    assert response["doctor_report"]["drug_safety"]["status"] in {"ok", "partial", "unavailable"}
    assert isinstance(response["patient_explain"]["drug_safety"], dict)
    assert response["run_meta"]["schema_version"] == "0.2"
    assert response["run_meta"]["request_id"] == payload["request_id"]
    assert response["run_meta"]["reasoning_mode"] in {"compat", "llm_rag_only"}
    assert response["run_meta"]["report_generation_path"] in {"primary", "fallback", "deterministic_only"}
    assert response["run_meta"]["retrieval_engine"] in {"basic", "llamaindex", "other"}
    routing_meta = response["run_meta"].get("routing_meta")
    assert isinstance(routing_meta, dict)
    assert isinstance(routing_meta.get("resolved_cancer_type"), str)
    assert isinstance(routing_meta.get("source_ids"), list)
    assert isinstance(routing_meta.get("doc_ids"), list)
    assert isinstance(routing_meta.get("candidate_chunks"), int)
    assert response["meta"]["execution_profile"] == "compat"
    assert response["meta"]["strict_mode"] is False


def test_pack_bridge_run_meta_requires_reasoning_mode(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = build_pack_request()

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02-reasoning-mode")
    run_meta = response.get("run_meta")
    assert isinstance(run_meta, dict)
    assert run_meta.get("reasoning_mode") in {"compat", "llm_rag_only"}

    run_meta.pop("reasoning_mode", None)
    with pytest.raises(ValidationError):
        validate_analyze_response(response)


def test_pack_bridge_preserves_llm_patient_summary_when_available(tmp_path: Path, monkeypatch) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = build_pack_request()

    def _fake_patient_builder(*args, **kwargs):  # noqa: ANN002, ANN003
        return (
            {
                "schema_version": "0.2",
                "kb_version": "kb-test",
                "based_on_report_id": "rep-test",
                "summary": "LLM-Пациент: по кейсу выявлены вопросы для обсуждения следующего этапа.",
                "key_points": ["LLM-Пациент: проверить переносимость перед следующим лечением."],
                "questions_to_ask_doctor": ["LLM-Пациент: какие дообследования обязательны сейчас?"],
                "safety_disclaimer": "Этот текст носит справочный характер и не заменяет консультацию врача.",
            },
            "llm",
        )

    monkeypatch.setattr("backend.app.service.build_patient_explain_with_fallback", _fake_patient_builder)

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02-patient-llm")
    patient = response["patient_explain"]
    assert patient["summary_plain"].startswith("LLM-Пациент:")
    assert any(str(item).startswith("LLM-Пациент:") for item in patient["key_points"])


def test_pack_bridge_maps_c16_to_gastric_cancer() -> None:
    payload = build_pack_request()
    context = normalize_analyze_request(payload)
    assert context.normalized_payload["case"]["cancer_type"] == "gastric_cancer"


def test_pack_bridge_routes_generic_c_prefix_to_non_unknown_cancer_type(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = build_pack_request()
    diagnosis = payload["case"]["case_json"]["diagnoses"][0]
    diagnosis["icd10"] = "C18.9"
    diagnosis["disease_id"] = "c8b1f6d0-4b6f-53cf-9e7d-6df58cc1ad5f"

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02-c18")
    routing_meta = response["run_meta"].get("routing_meta")
    assert isinstance(routing_meta, dict)
    assert routing_meta.get("resolved_cancer_type") == "oncology_c18"


def test_pack_bridge_multi_source_citations_include_both_sources(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = build_pack_request()
    payload["sources"] = {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]}

    minzdrav_content = b"%PDF-1.4 minzdrav gastric mfolfox6 her2"
    russco_content = b"%PDF-1.4 russco gastric mfolfox6 her2"

    service.admin_upload(
        role="admin",
        filename="minzdrav.pdf",
        content=minzdrav_content,
        metadata={
            "doc_id": "minzdrav_574_1",
            "doc_version": "2020",
            "source_set": "minzdrav",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "source_url": "https://cr.minzdrav.gov.ru/preview-cr/574_1",
        },
    )
    service.admin_upload(
        role="admin",
        filename="russco_2023_22.pdf",
        content=russco_content,
        metadata={
            "doc_id": "russco_2023_22",
            "doc_version": "2023",
            "source_set": "russco",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "source_url": "https://www.rosoncoweb.ru/standarts/RUSSCO/2023/russco_2023_22.pdf",
        },
    )
    service.admin_reindex(role="admin")
    _mark_release_ready(
        service,
        doc_id="minzdrav_574_1",
        doc_version="2020",
        source_url="https://cr.minzdrav.gov.ru/preview-cr/574_1",
    )
    _mark_release_ready(
        service,
        doc_id="russco_2023_22",
        doc_version="2023",
        source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2023/russco_2023_22.pdf",
    )

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02-multi-source")
    citations = response["doctor_report"]["citations"]
    source_ids = {item["source_id"] for item in citations}
    assert "minzdrav" in source_ids
    assert "russco" in source_ids
    routing_meta = response["run_meta"].get("routing_meta")
    assert isinstance(routing_meta, dict)
    assert set(routing_meta.get("source_ids") or []) >= {"minzdrav", "russco"}
    assert str(routing_meta.get("match_strategy") or "") != "manual_source_override"
    assert int(routing_meta.get("baseline_candidate_chunks") or 0) >= int(routing_meta.get("candidate_chunks") or 0)
    reduction_ratio = float(routing_meta.get("reduction_ratio") or 0.0)
    assert 0.0 <= reduction_ratio <= 1.0


def test_pack_bridge_multi_source_retrieval_falls_back_when_doc_cancer_type_unknown(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = build_pack_request()
    payload["sources"] = {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]}

    service.admin_upload(
        role="admin",
        filename="minzdrav_unknown.pdf",
        content=b"%PDF-1.4 minzdrav gastric recommendation mfolfox6 her2",
        metadata={
            "doc_id": "minzdrav_574_1",
            "doc_version": "2020",
            "source_set": "minzdrav",
            "cancer_type": "unknown",
            "language": "ru",
            "source_url": "https://cr.minzdrav.gov.ru/preview-cr/574_1",
        },
    )
    service.admin_upload(
        role="admin",
        filename="russco_unknown.pdf",
        content=b"%PDF-1.4 russco gastric recommendation mfolfox6 her2",
        metadata={
            "doc_id": "russco_2023_22",
            "doc_version": "2023",
            "source_set": "russco",
            "cancer_type": "unknown",
            "language": "ru",
            "source_url": "https://www.rosoncoweb.ru/standarts/RUSSCO/2023/russco_2023_22.pdf",
        },
    )
    service.admin_reindex(role="admin")

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02-unknown-cancer-type")
    citations = response["doctor_report"]["citations"]
    # Official docs with unknown cancer_type are not release-valid and must be excluded
    # from routing/retrieval even if source IDs are requested explicitly.
    assert citations == []
    assert response["insufficient_data"]["status"] is True


def test_pack_bridge_casefacts_flag_disabled_returns_placeholder_casefacts(tmp_path: Path) -> None:
    service = OncoService(
        make_settings(
            tmp_path,
            doctor_schema_v1_2_enabled=True,
            casefacts_enabled=False,
        )
    )
    payload = build_pack_request()

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02-casefacts-disabled")

    case_facts = response["doctor_report"]["case_facts"]
    key_unknowns = case_facts.get("key_unknowns") if isinstance(case_facts, dict) else None
    assert isinstance(key_unknowns, list)
    assert any("ONCOAI_CASEFACTS_ENABLED=false" in str(item) for item in key_unknowns)
    sanity_checks = response["doctor_report"]["sanity_checks"]
    assert any(
        item.get("check_id") == "casefacts_feature_flag_disabled" and item.get("status") == "warn"
        for item in sanity_checks
        if isinstance(item, dict)
    )


def test_pack_bridge_doctor_v1_0_compat_is_feature_flagged(tmp_path: Path) -> None:
    service = OncoService(
        make_settings(
            tmp_path,
            doctor_schema_v1_2_enabled=False,
            casefacts_enabled=True,
        )
    )
    payload = build_pack_request()

    response = service.analyze(payload=payload, role="clinician", client_id="pack-v02-doctor-v1-0-compat")

    assert response["doctor_report"]["schema_version"] == "1.0"
    assert response["patient_explain"]["schema_version"] == "1.0"
    validate_analyze_response(response, allow_pack_legacy_v1_0=True)


def test_pack_bridge_supports_sources_only_and_historical_fields(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = build_pack_request()
    payload["query_mode"] = "SOURCES_ONLY"
    payload["historical_assessment"] = True
    payload["as_of_date"] = "2025-03-01"

    response = service.analyze(payload=payload, role="clinician", client_id="pack-sources-only-history")
    validate_analyze_response(response)
    assert response["sources_only_result"]["mode"] == "SOURCES_ONLY"
    assert response["historical_assessment"]["requested_as_of_date"] == "2025-03-01"
    assert response["doctor_report"]["plan"] == []
