from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class OfficialSourceRule:
    source_set: str
    official_source: str
    domains: tuple[str, ...]
    usage_policy: str = "general"
    readiness: str = "complete"


@dataclass(frozen=True)
class OfficialDocHints:
    source_set: str
    doc_id: str
    cancer_type: str
    icd10_prefixes: tuple[str, ...]
    doc_kind: str = "guideline"


SOURCE_SET_ALIASES: dict[str, str] = {
    "pdq": "nci_pdq",
}

DEFAULT_AUTO_SOURCE_IDS: tuple[str, ...] = (
    "minzdrav",
    "russco",
    "asco",
    "esmo",
    "nccn",
    "nci_pdq",
)


OFFICIAL_SOURCE_RULES: dict[str, OfficialSourceRule] = {
    "russco": OfficialSourceRule(
        source_set="russco",
        official_source="RUSSCO",
        domains=("rosoncoweb.ru",),
    ),
    "minzdrav": OfficialSourceRule(
        source_set="minzdrav",
        official_source="Минздрав РФ",
        domains=(
            "minzdrav.gov.ru",
            "www.minzdrav.gov.ru",
            "cr.minzdrav.gov.ru",
            "static.edu.rosminzdrav.ru",
            "edu.rosminzdrav.ru",
        ),
    ),
    "asco": OfficialSourceRule(
        source_set="asco",
        official_source="ASCO",
        domains=(
            "asco.org",
            "www.asco.org",
            "ascopubs.org",
            "www.ascopubs.org",
        ),
    ),
    "esmo": OfficialSourceRule(
        source_set="esmo",
        official_source="ESMO",
        domains=(
            "esmo.org",
            "www.esmo.org",
            "oncologypro.esmo.org",
        ),
    ),
    "nccn": OfficialSourceRule(
        source_set="nccn",
        official_source="NCCN",
        domains=(
            "nccn.org",
            "www.nccn.org",
        ),
    ),
    "nci_pdq": OfficialSourceRule(
        source_set="nci_pdq",
        official_source="NCI PDQ",
        domains=(
            "cancer.gov",
            "www.cancer.gov",
        ),
    ),
    "pubmed": OfficialSourceRule(
        source_set="pubmed",
        official_source="PubMed/NCBI",
        domains=(
            "pubmed.ncbi.nlm.nih.gov",
            "www.ncbi.nlm.nih.gov",
            "ncbi.nlm.nih.gov",
        ),
        usage_policy="comparative_only",
    ),
    "international_guidelines": OfficialSourceRule(
        source_set="international_guidelines",
        official_source="International Oncology Guidelines",
        domains=(
            "www.esmo.org",
            "esmo.org",
            "www.esmoopen.com",
            "esmoopen.com",
            "uroweb.org",
            "www.uroweb.org",
            "eano.eu",
            "www.eano.eu",
        ),
        usage_policy="corroborative",
        readiness="partial",
    ),
}


OFFICIAL_DOC_HINTS: dict[str, OfficialDocHints] = {
    "russco_2025_1_1_13": OfficialDocHints(
        source_set="russco",
        doc_id="russco_2025_1_1_13",
        cancer_type="gastric_cancer",
        icd10_prefixes=("C16",),
    ),
    "russco_2025_1_1_12": OfficialDocHints(
        source_set="russco",
        doc_id="russco_2025_1_1_12",
        cancer_type="esophagogastric_junction_cancer",
        icd10_prefixes=("C15", "C16"),
    ),
    "russco_2025_1_1_19": OfficialDocHints(
        source_set="russco",
        doc_id="russco_2025_1_1_19",
        cancer_type="gist",
        icd10_prefixes=("C49",),
    ),
    "minzdrav_237_6": OfficialDocHints(
        source_set="minzdrav",
        doc_id="minzdrav_237_6",
        cancer_type="gastric_cancer",
        icd10_prefixes=("C16",),
    ),
    "minzdrav_574_rak_zheludka": OfficialDocHints(
        source_set="minzdrav",
        doc_id="minzdrav_574_rak_zheludka",
        cancer_type="gastric_cancer",
        icd10_prefixes=("C16",),
    ),
    "minzdrav_rak_pishevoda_i_kardii_2024": OfficialDocHints(
        source_set="minzdrav",
        doc_id="minzdrav_rak_pishevoda_i_kardii_2024",
        cancer_type="esophagogastric_junction_cancer",
        icd10_prefixes=("C15", "C16"),
    ),
    "russco_2025_mkb10": OfficialDocHints(
        source_set="russco",
        doc_id="russco_2025_mkb10",
        cancer_type="reference_icd10",
        icd10_prefixes=(),
        doc_kind="reference",
    ),
}


OFFICIAL_DOC_HINTS_BY_FILENAME: dict[str, str] = {
    "2025-1-1-13.pdf": "russco_2025_1_1_13",
    "2025-1-1-12.pdf": "russco_2025_1_1_12",
    "2025-1-1-19.pdf": "russco_2025_1_1_19",
    "2025-mkb10.pdf": "russco_2025_mkb10",
    "кр237_6.pdf": "minzdrav_237_6",
}


def _normalize_domain(value: str) -> str:
    domain = str(value or "").strip().lower()
    if domain.startswith("www."):
        return domain[4:]
    return domain


def _normalize_doc_id(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_source_set_id(value: str) -> str:
    token = str(value or "").strip().lower()
    return SOURCE_SET_ALIASES.get(token, token)


def normalize_source_set_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        token = normalize_source_set_id(str(item or ""))
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def resolve_primary_source_url(
    *,
    source_url: str = "",
    source_page_url: str = "",
    source_pdf_url: str = "",
) -> str:
    pdf_url = str(source_pdf_url or "").strip()
    if pdf_url:
        return pdf_url
    page_url = str(source_page_url or "").strip()
    if page_url:
        return page_url
    return str(source_url or "").strip()


def domain_matches_official(source_set: str, source_url: str) -> bool:
    rule = OFFICIAL_SOURCE_RULES.get(normalize_source_set_id(source_set))
    if not rule:
        return False
    url = str(source_url or "").strip()
    if not url:
        return False
    domain = _normalize_domain(urlparse(url).netloc)
    if not domain:
        return False
    for allowed in rule.domains:
        normalized_allowed = _normalize_domain(allowed)
        if domain == normalized_allowed or domain.endswith(f".{normalized_allowed}"):
            return True
    return False


def official_source_label(source_set: str) -> str:
    rule = OFFICIAL_SOURCE_RULES.get(normalize_source_set_id(source_set))
    return rule.official_source if rule else ""


def source_usage_policy(source_set: str) -> str:
    rule = OFFICIAL_SOURCE_RULES.get(normalize_source_set_id(source_set))
    return str(rule.usage_policy) if rule else ""


def source_readiness(source_set: str) -> str:
    rule = OFFICIAL_SOURCE_RULES.get(normalize_source_set_id(source_set))
    return str(rule.readiness) if rule else ""


def is_pubmed_url(source_url: str) -> bool:
    return domain_matches_official("pubmed", source_url)


def resolve_official_doc_hints(
    *,
    source_set: str,
    doc_id: str,
    source_url: str,
    fallback_cancer_type: str,
    fallback_doc_kind: str = "guideline",
) -> dict[str, str | list[str]]:
    normalized_source = normalize_source_set_id(source_set)
    normalized_doc_id = _normalize_doc_id(doc_id)
    hint = OFFICIAL_DOC_HINTS.get(normalized_doc_id)
    if hint and hint.source_set == normalized_source:
        return {
            "cancer_type": hint.cancer_type,
            "icd10_prefixes": list(hint.icd10_prefixes),
            "doc_kind": hint.doc_kind,
        }

    filename = str(source_url or "").strip().rsplit("/", 1)[-1].strip().lower()
    alias_doc_id = OFFICIAL_DOC_HINTS_BY_FILENAME.get(filename)
    alias_hint = OFFICIAL_DOC_HINTS.get(alias_doc_id or "")
    if alias_hint and alias_hint.source_set == normalized_source:
        return {
            "cancer_type": alias_hint.cancer_type,
            "icd10_prefixes": list(alias_hint.icd10_prefixes),
            "doc_kind": alias_hint.doc_kind,
        }

    return {
        "cancer_type": str(fallback_cancer_type or "").strip().lower() or "unknown",
        "icd10_prefixes": [],
        "doc_kind": str(fallback_doc_kind or "guideline").strip().lower() or "guideline",
    }


def is_demo_or_decoy_doc_id(doc_id: str) -> bool:
    token = str(doc_id or "").strip().lower()
    if not token:
        return False
    if token.startswith(("demo_", "smoke_", "test_")):
        return True
    if "decoy" in token:
        return True
    return False


def evaluate_release_validity(
    *,
    source_set: str,
    source_url: str,
    status: str,
    doc_id: str = "",
    nosology_mapped: bool = True,
) -> dict[str, str | bool]:
    normalized_source = normalize_source_set_id(source_set)
    normalized_status = str(status or "").strip().upper()
    rule = OFFICIAL_SOURCE_RULES.get(normalized_source)
    official_source = rule.official_source if rule else ""

    if not rule:
        return {
            "is_valid": False,
            "validity_reason": "invalid_source_set",
            "official_source": official_source,
        }
    if str(rule.usage_policy or "general") == "comparative_only":
        return {
            "is_valid": False,
            "validity_reason": "comparative_only_source_set",
            "official_source": official_source,
        }
    if not str(source_url or "").strip():
        return {
            "is_valid": False,
            "validity_reason": "missing_source_url",
            "official_source": official_source,
        }
    if not domain_matches_official(normalized_source, source_url):
        return {
            "is_valid": False,
            "validity_reason": "non_official_source_url",
            "official_source": official_source,
        }
    if not nosology_mapped:
        return {
            "is_valid": False,
            "validity_reason": "nosology_unmapped",
            "official_source": official_source,
        }
    if is_demo_or_decoy_doc_id(doc_id):
        return {
            "is_valid": False,
            "validity_reason": "demo_document_excluded",
            "official_source": official_source,
        }
    if normalized_status not in {"APPROVED", "INDEXED"}:
        return {
            "is_valid": False,
            "validity_reason": "status_not_release_ready",
            "official_source": official_source,
        }
    return {
        "is_valid": True,
        "validity_reason": "ok",
        "official_source": official_source,
    }
