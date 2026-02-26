from __future__ import annotations

from backend.app.guidelines.source_registry import (
    DEFAULT_AUTO_SOURCE_IDS,
    domain_matches_official,
    evaluate_release_validity,
    is_pubmed_url,
    normalize_source_set_id,
    source_readiness,
    resolve_official_doc_hints,
)


def test_domain_matches_official_supports_subdomains() -> None:
    assert domain_matches_official("russco", "https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf") is True
    assert domain_matches_official("minzdrav", "https://cr.minzdrav.gov.ru/preview-cr/237_6") is True
    assert domain_matches_official("russco", "https://example.org/file.pdf") is False


def test_resolve_official_doc_hints_by_doc_id() -> None:
    hints = resolve_official_doc_hints(
        source_set="russco",
        doc_id="russco_2025_1_1_12",
        source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-12.pdf",
        fallback_cancer_type="unknown",
    )
    assert hints["cancer_type"] == "esophagogastric_junction_cancer"
    assert hints["doc_kind"] == "guideline"
    assert hints["icd10_prefixes"] == ["C15", "C16"]


def test_resolve_official_doc_hints_by_filename_alias() -> None:
    hints = resolve_official_doc_hints(
        source_set="minzdrav",
        doc_id="custom_doc_id",
        source_url="https://cr.minzdrav.gov.ru/preview-cr/237_6/КР237_6.pdf",
        fallback_cancer_type="unknown",
    )
    assert hints["cancer_type"] == "gastric_cancer"
    assert hints["doc_kind"] == "guideline"
    assert hints["icd10_prefixes"] == ["C16"]


def test_resolve_official_doc_hints_falls_back_for_unknown_doc() -> None:
    hints = resolve_official_doc_hints(
        source_set="russco",
        doc_id="unknown_doc",
        source_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/unknown.pdf",
        fallback_cancer_type="supportive_care",
        fallback_doc_kind="guideline",
    )
    assert hints["cancer_type"] == "supportive_care"
    assert hints["doc_kind"] == "guideline"
    assert hints["icd10_prefixes"] == []


def test_pubmed_domain_and_comparative_policy() -> None:
    assert is_pubmed_url("https://pubmed.ncbi.nlm.nih.gov/12345678/") is True
    assert domain_matches_official("pubmed", "https://www.ncbi.nlm.nih.gov/pubmed/12345678") is True
    validity = evaluate_release_validity(
        source_set="pubmed",
        source_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
        status="APPROVED",
        doc_id="pubmed_12345678",
        nosology_mapped=True,
    )
    assert validity["is_valid"] is False
    assert validity["validity_reason"] == "comparative_only_source_set"


def test_normalize_source_set_id_alias_and_defaults() -> None:
    assert normalize_source_set_id("pdq") == "nci_pdq"
    assert normalize_source_set_id("PDQ") == "nci_pdq"
    assert normalize_source_set_id("  NCCN ") == "nccn"
    assert list(DEFAULT_AUTO_SOURCE_IDS) == ["minzdrav", "russco", "asco", "esmo", "nccn", "nci_pdq"]


def test_domain_matches_official_for_international_sources() -> None:
    assert domain_matches_official("asco", "https://www.asco.org/practice-patients/guidelines") is True
    assert domain_matches_official("esmo", "https://www.esmo.org/guidelines/gastrointestinal-cancers") is True
    assert domain_matches_official("nccn", "https://www.nccn.org/guidelines/category_1") is True
    assert domain_matches_official("nci_pdq", "https://www.cancer.gov/publications/pdq") is True
    assert domain_matches_official("pdq", "https://www.cancer.gov/publications/pdq") is True


def test_release_validity_accepts_pdq_alias() -> None:
    validity = evaluate_release_validity(
        source_set="pdq",
        source_url="https://www.cancer.gov/publications/pdq",
        status="APPROVED",
        doc_id="nci_pdq_gastric_2026",
        nosology_mapped=True,
    )
    assert validity["is_valid"] is True
    assert validity["validity_reason"] == "ok"


def test_source_readiness_for_international_layer_and_aliases() -> None:
    assert source_readiness("international_guidelines") == "partial"
    assert source_readiness("pdq") == "complete"
