from __future__ import annotations

from backend.app.guidelines.nosology_mapper import (
    enrich_doc_with_nosology,
    infer_cancer_type_for_guideline,
    is_nosology_mapped,
)


def test_infer_cancer_type_uses_russco_doc_id_heuristics() -> None:
    assert (
        infer_cancer_type_for_guideline(
            doc_id="russco_2025_1_1_13",
            source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
            title="2025-1-1-13.pdf",
            fallback="unknown",
        )
        == "gastric_cancer"
    )
    assert (
        infer_cancer_type_for_guideline(
            doc_id="russco_2025_1_1_12",
            source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-12.pdf",
            title="2025-1-1-12.pdf",
            fallback="unknown",
        )
        == "esophagogastric_junction_cancer"
    )
    assert (
        infer_cancer_type_for_guideline(
            doc_id="russco_2025_1_1_19",
            source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-19.pdf",
            title="2025-1-1-19.pdf",
            fallback="unknown",
        )
        == "gist"
    )


def test_infer_cancer_type_handles_reference_and_supportive_patterns() -> None:
    assert (
        infer_cancer_type_for_guideline(
            doc_id="russco_2025_mkb10",
            source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-mkb10.pdf",
            title="МКБ-10 2025",
            fallback="unknown",
        )
        == "reference_icd10"
    )
    assert (
        infer_cancer_type_for_guideline(
            doc_id="russco_supportive_guide",
            source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-2-4.pdf",
            title="Поддерживающая терапия",
            fallback="unknown",
        )
        == "supportive_care"
    )


def test_is_nosology_mapped_and_enrich_doc() -> None:
    assert is_nosology_mapped("gastric_cancer") is True
    assert is_nosology_mapped("unknown") is False

    enriched = enrich_doc_with_nosology(
        {
            "doc_id": "russco_2025_1_1_12",
            "source_url": "https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-12.pdf",
            "title": "Рак пищевода и ПЖП",
            "cancer_type": "unknown",
        }
    )
    assert enriched["cancer_type"] == "esophagogastric_junction_cancer"
    assert enriched["nosology_mapped"] is True
