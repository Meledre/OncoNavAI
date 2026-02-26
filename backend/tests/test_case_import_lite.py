from __future__ import annotations

import base64
import uuid
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.app.config import Settings
from backend.app.exceptions import NotFoundError, ValidationError
from backend.app.service import OncoService


def make_settings(
    root: Path,
    *,
    case_import_allow_full_mode: bool = False,
    case_import_full_require_ack: bool = True,
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
        case_import_allow_full_mode=case_import_allow_full_mode,
        case_import_full_require_ack=case_import_full_require_ack,
        reasoning_mode=reasoning_mode,
    )


def _pack_case_id_request(case_id: str, *, request_id: str = "ab09090f-bf23-49e6-9f17-9f9ec3683bf8") -> dict[str, object]:
    return {
        "schema_version": "0.2",
        "request_id": request_id,
        "query_type": "CHECK_LAST_TREATMENT",
        "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
        "language": "ru",
        "case": {"case_id": case_id},
    }


def _minimal_case_json(case_id: str) -> dict[str, object]:
    diagnosis_id = str(uuid.uuid4())
    disease_id = str(uuid.uuid4())
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "import_profile": "CUSTOM_TEMPLATE",
        "patient": {"sex": "male", "birth_year": 1973},
        "diagnoses": [
            {
                "diagnosis_id": diagnosis_id,
                "disease_id": disease_id,
                "icd10": "C16",
                "histology": "adenocarcinoma",
                "stage": {"system": "TNM8", "stage_group": "IV"},
                "timeline": [
                    {
                        "event_id": str(uuid.uuid4()),
                        "date": "2026-01-05",
                        "precision": "day",
                        "type": "systemic_therapy",
                        "label": "Начата 1-я линия",
                        "details": "XELOX",
                    }
                ],
                "last_plan": {
                    "date": "2026-02-10",
                    "precision": "day",
                    "regimen": "XELOX",
                    "line": 1,
                    "cycle": 3,
                },
            }
        ],
        "attachments": [],
        "notes": "Синтетический кейс для проверки case_id bridge.",
    }


def _minimal_fhir_bundle() -> dict[str, object]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "patient-1",
                    "gender": "male",
                    "birthDate": "1973-03-14",
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-1",
                    "code": {
                        "coding": [
                            {"system": "http://hl7.org/fhir/sid/icd-10", "code": "C16.9", "display": "Stomach cancer"}
                        ],
                        "text": "adenocarcinoma",
                    },
                    "stage": [{"summary": {"text": "Stage IV"}}],
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-1",
                    "code": {"text": "HER2"},
                    "valueString": "positive",
                    "effectiveDateTime": "2026-01-10",
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-1",
                    "medicationCodeableConcept": {"text": "XELOX"},
                    "authoredOn": "2026-02-10",
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationStatement",
                    "id": "meds-1",
                    "medicationCodeableConcept": {"text": "XELOX"},
                    "effectiveDateTime": "2026-02-10",
                    "note": [{"text": "Line 2, cycle 3"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Procedure",
                    "id": "proc-1",
                    "status": "completed",
                    "code": {"text": "Diagnostic laparoscopy"},
                    "performedDateTime": "2026-01-15",
                    "note": [{"text": "Staging diagnostic procedure"}],
                }
            },
        ],
    }


def test_case_import_custom_template_case_json_can_be_analyzed_by_case_id(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    case_id = str(uuid.uuid4())
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "CUSTOM_TEMPLATE",
            "case_json": _minimal_case_json(case_id),
        },
    )
    assert run["schema_version"] == "1.0"
    assert run["status"] == "SUCCESS"
    assert run["case_id"] == case_id

    response = service.analyze(
        payload=_pack_case_id_request(case_id),
        role="clinician",
        client_id="case-import-custom-template",
    )
    assert response["doctor_report"]["schema_version"] == "1.2"
    assert response["doctor_report"]["disease_context"]["icd10"] == "C16"


def test_case_import_free_text_creates_canonical_case(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "language": "ru",
            "free_text": "Мужчина, рак желудка, первая линия XELOX.",
        },
    )
    assert run["schema_version"] == "1.0"
    assert run["status"] in {"SUCCESS", "PARTIAL_SUCCESS"}
    case_id = str(run["case_id"])
    case_json = service.get_case(role="clinician", case_id=case_id)
    assert case_json["schema_version"] == "1.0"
    assert case_json["case_id"] == case_id
    assert case_json["import_profile"] == "FREE_TEXT"
    assert "XELOX" in case_json.get("notes", "")


def test_case_import_free_text_llm_only_bypasses_heuristic_parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = OncoService(make_settings(tmp_path, reasoning_mode="llm_rag_only"))

    def _raise_heuristic(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("heuristic parser must not be used in llm_rag_only mode")

    def _fake_llm_parser(
        *,
        import_profile: str,
        payload: dict[str, object],
        case_id: str,
        now: str,
        data_mode: str,
    ) -> tuple[dict[str, object], list[str]]:
        assert import_profile == "FREE_TEXT"
        assert str(payload.get("free_text") or "").strip()
        return (
            {
                "schema_version": "1.0",
                "case_id": case_id,
                "created_at": now,
                "updated_at": now,
                "data_mode": data_mode,
                "import_profile": "FREE_TEXT",
                "patient": {"sex": "male", "birth_year": 1973},
                "diagnoses": [
                    {
                        "diagnosis_id": str(uuid.uuid4()),
                        "disease_id": str(uuid.uuid4()),
                        "icd10": "C16",
                        "histology": "adenocarcinoma",
                        "timeline": [],
                        "biomarkers": [{"name": "HER2", "value": "positive"}],
                        "last_plan": {
                            "date": now[:10],
                            "precision": "day",
                            "regimen": "XELOX",
                            "line": 1,
                        },
                    }
                ],
                "attachments": [],
                "notes": str(payload.get("free_text") or ""),
            },
            [],
        )

    monkeypatch.setattr(service, "_build_case_json_from_import", _raise_heuristic)
    monkeypatch.setattr(service, "_build_case_json_from_import_llm", _fake_llm_parser)

    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "language": "ru",
            "free_text": "Мужчина, рак желудка C16, первая линия XELOX.",
        },
    )
    case_id = str(run["case_id"])
    case_json = service.get_case(role="clinician", case_id=case_id)
    assert case_json["import_profile"] == "FREE_TEXT"
    assert case_json["diagnoses"][0]["icd10"] == "C16"


def test_case_import_free_text_extracts_patient_metrics(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "language": "ru",
            "free_text": (
                "Мужчина, 47 лет. Рост: 178 см. Вес: 75 кг. ECOG 1. "
                "Диагноз: рак желудка C16, стадия III, текущая схема XELOX."
            ),
        },
    )
    case_id = str(run["case_id"])
    case_json = service.get_case(role="clinician", case_id=case_id)
    patient = case_json.get("patient", {})
    assert patient.get("sex") == "male"
    assert patient.get("birth_year") == pytest.approx(1979, abs=1)
    assert patient.get("height_cm") == 178.0
    assert patient.get("weight_kg") == 75.0
    assert patient.get("ecog") == 1


def test_case_import_free_text_can_be_analyzed_by_case_id(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "language": "ru",
            "free_text": "Мужчина, рак желудка, первая линия XELOX.",
        },
    )
    case_id = str(run["case_id"])

    response = service.analyze(
        payload=_pack_case_id_request(case_id, request_id=str(uuid.uuid4())),
        role="clinician",
        client_id="case-import-free-text",
    )
    assert response["doctor_report"]["schema_version"] == "1.2"
    assert response["request_id"]
    assert response["run_meta"]["schema_version"] == "0.2"


def test_case_import_free_text_extracts_icd10_and_cancer_context(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "language": "ru",
            "free_text": "Диагноз C34.9, немелкоклеточный рак легкого, стадия IV. Назначен osimertinib 80 mg.",
        },
    )
    case_id = str(run["case_id"])
    case_json = service.get_case(role="clinician", case_id=case_id)
    diagnosis = case_json.get("diagnoses", [{}])[0]
    assert diagnosis.get("icd10") == "C34.9"
    assert diagnosis.get("stage", {}).get("stage_group") in {"IV", "4"}

    response = service.analyze(
        payload=_pack_case_id_request(case_id, request_id=str(uuid.uuid4())),
        role="clinician",
        client_id="case-import-free-text-icd10",
    )
    routing_meta = response["run_meta"].get("routing_meta")
    assert isinstance(routing_meta, dict)
    assert routing_meta.get("resolved_cancer_type") == "nsclc_egfr"


def test_case_import_realistic_breast_history_uses_primary_nosology_and_birth_year(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "language": "ru",
            "free_text": (
                "ФИО: N. Дата рождения: 01.01.1970г. "
                "Диагноз: рак левой молочной железы, трижды негативный подтип. "
                "Выявлены метастазы в головной мозг. "
                "ПХТ 1 линии (паклитаксел+карбоплатин) с 09.2021 по 03.2022. "
                "Прогрессирование от 16.03.2022. "
                "ХТ 2 линии эрибулином с 03.2022 по 08.2022."
            ),
        },
    )
    case_id = str(run["case_id"])
    case_json = service.get_case(role="clinician", case_id=case_id)
    patient = case_json.get("patient") if isinstance(case_json.get("patient"), dict) else {}
    diagnoses = case_json.get("diagnoses") if isinstance(case_json.get("diagnoses"), list) else []
    diagnosis = diagnoses[0] if diagnoses and isinstance(diagnoses[0], dict) else {}

    assert patient.get("birth_year") == 1970
    assert str(diagnosis.get("icd10") or "").upper().startswith("C50")

    response = service.analyze(
        payload=_pack_case_id_request(case_id, request_id=str(uuid.uuid4())),
        role="clinician",
        client_id="case-import-breast-realistic",
    )
    routing_meta = response["run_meta"].get("routing_meta")
    assert isinstance(routing_meta, dict)
    assert routing_meta.get("resolved_cancer_type") == "breast_hr+/her2-"

    case_facts = response["doctor_report"].get("case_facts") if isinstance(response.get("doctor_report"), dict) else {}
    treatment_history = case_facts.get("treatment_history") if isinstance(case_facts, dict) else []
    assert isinstance(treatment_history, list)
    assert len(treatment_history) >= 2


def test_case_import_fhir_bundle_creates_canonical_case(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FHIR_BUNDLE",
            "fhir_bundle": _minimal_fhir_bundle(),
        },
    )
    assert run["schema_version"] == "1.0"
    assert run["status"] in {"SUCCESS", "PARTIAL_SUCCESS"}
    case_id = str(run["case_id"])
    case_json = service.get_case(role="clinician", case_id=case_id)
    assert case_json is not None
    assert case_json["import_profile"] == "FHIR_BUNDLE"
    assert case_json["patient"]["sex"] == "male"
    diagnosis = case_json["diagnoses"][0]
    assert diagnosis["icd10"] == "C16.9"
    assert diagnosis["last_plan"]["regimen"] == "XELOX"
    assert diagnosis["last_plan"]["line"] == 2
    assert diagnosis["last_plan"]["cycle"] == 3
    timeline = diagnosis.get("timeline", [])
    assert isinstance(timeline, list) and timeline
    assert any(item.get("type") in {"surgery", "diagnostic"} for item in timeline)
    assert case_json["attachments"][0]["kind"] == "fhir_bundle"

    response = service.analyze(
        payload=_pack_case_id_request(case_id, request_id=str(uuid.uuid4())),
        role="clinician",
        client_id="case-import-fhir-bundle",
    )
    assert response["doctor_report"]["schema_version"] == "1.2"
    assert response["doctor_report"]["disease_context"]["icd10"] == "C16.9"


def test_case_import_kin_pdf_creates_canonical_case(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "KIN_PDF",
            "filename": "kin_case.pdf",
            "kin_pdf_text": "Пациент муж. МКБ-10: C16. Стадия IV. Последняя схема XELOX, курс 3. HER2: positive.",
        },
    )
    assert run["schema_version"] == "1.0"
    assert run["status"] in {"SUCCESS", "PARTIAL_SUCCESS"}
    case_id = str(run["case_id"])
    case_json = service.get_case(role="clinician", case_id=case_id)
    assert case_json is not None
    assert case_json["import_profile"] == "KIN_PDF"
    diagnosis = case_json["diagnoses"][0]
    assert diagnosis["icd10"] == "C16"
    assert diagnosis["stage"]["stage_group"] == "IV"
    assert diagnosis["last_plan"]["regimen"] == "XELOX"
    assert case_json["attachments"][0]["kind"] == "pdf"
    assert case_json["attachments"][0]["filename"] == "kin_case.pdf"


def test_case_import_fhir_bundle_invalid_payload_returns_failed_run(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FHIR_BUNDLE",
        },
    )
    assert run["schema_version"] == "1.0"
    assert run["status"] == "FAILED"
    assert run["errors"][0]["code"] == "INVALID_IMPORT_PAYLOAD"


def test_case_import_full_mode_is_rejected_when_disabled(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "data_mode": "FULL",
            "full_mode_acknowledged": True,
            "free_text": "Пациент Ivan Ivanov, телефон +7 (999) 555-12-34, email ivan@example.com",
        },
    )
    assert run["status"] == "FAILED"
    assert run["errors"][0]["code"] == "FULL_MODE_DISABLED"


def test_case_import_full_mode_requires_ack_when_enabled(tmp_path: Path) -> None:
    service = OncoService(
        make_settings(
            tmp_path,
            case_import_allow_full_mode=True,
            case_import_full_require_ack=True,
        )
    )
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "data_mode": "FULL",
            "free_text": "Synthetic FULL mode payload without explicit ack.",
        },
    )
    assert run["status"] == "FAILED"
    assert run["errors"][0]["code"] == "FULL_MODE_ACK_REQUIRED"


def test_case_import_file_base64_propagates_extraction_warnings(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>Коротко</w:t></w:r></w:p></w:body>
</w:document>
"""
    payload_buffer = BytesIO()
    with ZipFile(payload_buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml.encode("utf-8"))
    content_base64 = base64.b64encode(payload_buffer.getvalue()).decode("ascii")

    run = service.case_import_file_base64(
        role="clinician",
        payload={
            "filename": "short.docx",
            "content_base64": content_base64,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )

    warning_codes = {item.get("code") for item in run.get("warnings", []) if isinstance(item, dict)}
    assert "LOW_TEXT_VOLUME" in warning_codes


def test_case_import_full_mode_with_ack_keeps_original_content_and_allows_analyze(tmp_path: Path) -> None:
    service = OncoService(
        make_settings(
            tmp_path,
            case_import_allow_full_mode=True,
            case_import_full_require_ack=True,
        )
    )
    case_id = str(uuid.uuid4())
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "CUSTOM_TEMPLATE",
            "data_mode": "FULL",
            "full_mode_acknowledged": True,
            "case_json": {
                **_minimal_case_json(case_id),
                "data_mode": "FULL",
                "notes": "Пациент Ivan Ivanov, телефон +7 (999) 555-12-34, email ivan@example.com",
            },
        },
    )
    assert run["status"] in {"SUCCESS", "PARTIAL_SUCCESS"}

    stored_case = service.get_case(role="clinician", case_id=case_id)
    assert stored_case["data_mode"] == "FULL"
    assert "ivan@example.com" in stored_case["notes"]

    response = service.analyze(
        payload=_pack_case_id_request(case_id, request_id=str(uuid.uuid4())),
        role="clinician",
        client_id="case-import-full-mode",
    )
    assert response["doctor_report"]["schema_version"] == "1.2"


def test_case_import_deid_mode_redacts_pii_from_notes(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "data_mode": "DEID",
            "free_text": "Пациент Ivan Ivanov, телефон +7 (999) 555-12-34, email ivan@example.com",
        },
    )
    assert run["status"] in {"SUCCESS", "PARTIAL_SUCCESS"}
    case_id = str(run["case_id"])
    stored_case = service.get_case(role="clinician", case_id=case_id)
    notes = str(stored_case.get("notes") or "")
    assert "Ivan Ivanov" not in notes
    assert "ivan@example.com" not in notes
    assert "+7 (999) 555-12-34" not in notes
    assert "[REDACTED_EMAIL]" in notes
    assert "[REDACTED_PHONE]" in notes


def test_case_import_profile_not_supported_returns_failed_run(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    run = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "CSV_UPLOAD",
        },
    )
    assert run["schema_version"] == "1.0"
    assert run["status"] == "FAILED"
    assert run["errors"][0]["code"] == "PROFILE_NOT_SUPPORTED"


def test_case_import_run_get_and_list(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    first = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "FREE_TEXT",
            "free_text": "C16, line 1 XELOX",
        },
    )
    second = service.case_import(
        role="clinician",
        payload={
            "schema_version": "1.0",
            "import_profile": "KIN_PDF",
            "kin_pdf_text": "МКБ-10 C16. Стадия IV. XELOX курс 2.",
        },
    )

    fetched = service.get_case_import_run(role="clinician", import_run_id=str(first["import_run_id"]))
    assert fetched["import_run_id"] == first["import_run_id"]
    assert fetched["case_id"] == first["case_id"]

    latest = service.list_case_import_runs(role="admin", limit=1)
    assert len(latest) == 1
    assert latest[0]["import_run_id"] == second["import_run_id"]


def test_case_import_run_get_not_found(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(NotFoundError):
        service.get_case_import_run(role="clinician", import_run_id=str(uuid.uuid4()))


def test_analyze_pack_case_id_not_found_raises_validation_error(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(ValidationError, match="CASE_NOT_FOUND"):
        service.analyze(
            payload=_pack_case_id_request(str(uuid.uuid4()), request_id=str(uuid.uuid4())),
            role="clinician",
            client_id="pack-missing-case",
        )


def test_analyze_full_mode_payload_rejected_when_policy_disabled(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = {
        "schema_version": "0.2",
        "request_id": str(uuid.uuid4()),
        "query_type": "CHECK_LAST_TREATMENT",
        "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
        "language": "ru",
        "case": {
            "case_json": {
                **_minimal_case_json(str(uuid.uuid4())),
                "data_mode": "FULL",
                "notes": "Пациент Ivan Ivanov, телефон +7 (999) 555-12-34, email ivan@example.com",
            }
        },
    }
    with pytest.raises(ValidationError, match="FULL_MODE_DISABLED"):
        service.analyze(
            payload=payload,
            role="clinician",
            client_id="analyze-full-mode-disabled",
        )
