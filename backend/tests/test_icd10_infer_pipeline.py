from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
from backend.app.icd10.infer import infer_icd10_code
from backend.app.service import OncoService


def _make_settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=100,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
        reasoning_mode="compat",
    )


def test_case_import_infers_c16_for_gastric_text_without_explicit_code(tmp_path: Path) -> None:
    service = OncoService(_make_settings(tmp_path))
    payload = {
        "schema_version": "1.0",
        "import_profile": "FREE_TEXT",
        "free_text": "Пациент, диагноз: рак желудка, аденокарцинома, стадия III.",
    }
    result = service.case_import(role="clinician", payload=payload)
    assert "diagnoses[0].icd10" not in result.get("missing_required_fields", [])
    case = service.get_case(role="clinician", case_id=str(result["case_id"]))
    diagnoses = case.get("diagnoses") if isinstance(case.get("diagnoses"), list) else []
    assert diagnoses and isinstance(diagnoses[0], dict)
    assert str(diagnoses[0].get("icd10") or "").upper().startswith("C16")


def test_case_import_infers_c16_for_adenocarcinoma_stomach_phrase(tmp_path: Path) -> None:
    service = OncoService(_make_settings(tmp_path))
    payload = {
        "schema_version": "1.0",
        "import_profile": "FREE_TEXT",
        "free_text": "Морфология: аденокарцинома желудка. После прогрессирования требуется консилиум.",
    }
    result = service.case_import(role="clinician", payload=payload)
    assert "diagnoses[0].icd10" not in result.get("missing_required_fields", [])
    case = service.get_case(role="clinician", case_id=str(result["case_id"]))
    diagnoses = case.get("diagnoses") if isinstance(case.get("diagnoses"), list) else []
    assert diagnoses and isinstance(diagnoses[0], dict)
    assert str(diagnoses[0].get("icd10") or "").upper().startswith("C16")


def test_case_import_keeps_missing_icd10_for_ambiguous_text(tmp_path: Path) -> None:
    service = OncoService(_make_settings(tmp_path))
    payload = {
        "schema_version": "1.0",
        "import_profile": "FREE_TEXT",
        "free_text": "Онкологическое заболевание, требуется уточнение диагноза и дообследование.",
    }
    result = service.case_import(role="clinician", payload=payload)
    assert "diagnoses[0].icd10" in result.get("missing_required_fields", [])


def test_reference_index_loads_icd10_table(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    service = OncoService(_make_settings(tmp_path))

    def fake_extract_pdf_chunks(path, metadata, *, structural_chunker_enabled=True):  # type: ignore[no-untyped-def]
        return [
            {
                "chunk_id": "mkb10:2025:1",
                "doc_id": str(metadata["doc_id"]),
                "doc_version": str(metadata["doc_version"]),
                "source_set": str(metadata["source_set"]),
                "cancer_type": str(metadata["cancer_type"]),
                "language": str(metadata["language"]),
                "pdf_page_index": 0,
                "page_label": "1",
                "section_title": "МКБ-10",
                "text": (
                    "C15 Злокачественное новообразование пищевода\n"
                    "C16 Злокачественное новообразование желудка\n"
                    "C16.0 Кардиальный отдел желудка"
                ),
                "updated_at": "2026-02-22T00:00:00+00:00",
            }
        ]

    monkeypatch.setattr("backend.app.service.extract_pdf_chunks", fake_extract_pdf_chunks)

    service.admin_upload(
        role="admin",
        filename="2025-mkb10.pdf",
        content=b"%PDF-1.4 mkb10 reference",
        metadata={
            "doc_id": "russco_2025_mkb10",
            "doc_version": "2025",
            "source_set": "russco",
            "cancer_type": "reference_icd10",
            "language": "ru",
            "source_url": "https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-mkb10.pdf",
            "doc_kind": "reference",
        },
    )
    service.admin_doc_rechunk(role="admin", doc_id="russco_2025_mkb10", doc_version="2025")
    service.admin_doc_approve(role="admin", doc_id="russco_2025_mkb10", doc_version="2025")
    indexed = service.admin_doc_index(role="admin", doc_id="russco_2025_mkb10", doc_version="2025")
    assert indexed["status"] == "INDEXED"

    rows = service.store.list_icd10_reference(
        source_doc_id="russco_2025_mkb10",
        source_doc_version="2025",
        limit=50,
    )
    by_code = {str(item.get("code") or ""): str(item.get("title_ru") or "") for item in rows}
    assert "C16" in by_code
    assert "желуд" in by_code["C16"].lower()


def test_icd10_infer_detects_cns_metastases_keyword() -> None:
    inferred = infer_icd10_code(text="Верифицированы метастазы в головной мозг на МРТ.", explicit_code="")
    assert inferred["code"] == "C79.3"
    assert inferred["method"] == "keyword_heuristic"


def test_icd10_infer_prefers_breast_primary_over_cns_metastases() -> None:
    inferred = infer_icd10_code(
        text=(
            "Диагноз: рак левой молочной железы, тройной негативный фенотип. "
            "Позднее выявлены метастазы в головной мозг."
        ),
        explicit_code="",
    )
    assert inferred["code"].startswith("C50")


def test_icd10_infer_detects_primary_brain_tumor_keyword() -> None:
    inferred = infer_icd10_code(text="Глиобластома левой лобной доли, первичная опухоль головного мозга.", explicit_code="")
    assert inferred["code"] == "C71"
    assert inferred["method"] == "keyword_heuristic"
