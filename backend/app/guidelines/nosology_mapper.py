from __future__ import annotations

import re
from typing import Any


_GASTRIC_PATTERNS = (
    re.compile(r"рак[_\-\s]*желуд", re.IGNORECASE),
    re.compile(r"gastric", re.IGNORECASE),
    re.compile(r"stomach", re.IGNORECASE),
)
_EGJ_PATTERNS = (
    re.compile(r"пищевод", re.IGNORECASE),
    re.compile(r"кардиоэзоф", re.IGNORECASE),
    re.compile(r"egj", re.IGNORECASE),
    re.compile(r"esophag", re.IGNORECASE),
    re.compile(r"gastroesophageal[_\-\s]*junction", re.IGNORECASE),
)
_GIST_PATTERNS = (
    re.compile(r"\bgist\b", re.IGNORECASE),
    re.compile(r"стромальн", re.IGNORECASE),
)
_LUNG_PATTERNS = (
    re.compile(r"рак[_\-\s]*легк", re.IGNORECASE),
    re.compile(r"nsclc", re.IGNORECASE),
    re.compile(r"lung", re.IGNORECASE),
)
_BRAIN_PRIMARY_PATTERNS = (
    re.compile(r"\bc71\b", re.IGNORECASE),
    re.compile(r"первичн\w*.*опухол\w*.*головн\w*\s+мозг", re.IGNORECASE),
    re.compile(r"glioblast|astrocytom|oligodendrogliom", re.IGNORECASE),
)
_CNS_METS_PATTERNS = (
    re.compile(r"\bc79(?:\.3)?\b", re.IGNORECASE),
    re.compile(r"метастаз\w*.*головн\w*\s+мозг", re.IGNORECASE),
    re.compile(r"brain[_\-\s]*metasta|cns[_\-\s]*metasta", re.IGNORECASE),
)
_BREAST_PATTERNS = (
    re.compile(r"рак[_\-\s]*молоч", re.IGNORECASE),
    re.compile(r"breast", re.IGNORECASE),
)
_MKB10_PATTERNS = (
    re.compile(r"мкб[_\-\s]*10", re.IGNORECASE),
    re.compile(r"icd[_\-\s]*10", re.IGNORECASE),
)
_SUPPORTIVE_PATTERNS = (
    re.compile(r"supportive", re.IGNORECASE),
    re.compile(r"поддержива", re.IGNORECASE),
    re.compile(r"паллиатив", re.IGNORECASE),
)


def _match_patterns(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def infer_cancer_type_for_guideline(*, doc_id: str, source_url: str, title: str, fallback: str = "") -> str:
    candidate = " ".join([str(doc_id or ""), str(source_url or ""), str(title or "")]).strip().lower()
    if _match_patterns(candidate, _MKB10_PATTERNS):
        return "reference_icd10"
    if "2025_1_1_13" in candidate or "2025-1-1-13" in candidate:
        return "gastric_cancer"
    if "2025_1_1_12" in candidate or "2025-1-1-12" in candidate:
        return "esophagogastric_junction_cancer"
    if "2025_1_1_19" in candidate or "2025-1-1-19" in candidate:
        return "gist"
    if _match_patterns(candidate, _CNS_METS_PATTERNS):
        return "cns_metastases_c79_3"
    if _match_patterns(candidate, _BRAIN_PRIMARY_PATTERNS):
        return "brain_primary_c71"
    if _match_patterns(candidate, _EGJ_PATTERNS):
        return "esophagogastric_junction_cancer"
    if _match_patterns(candidate, _GASTRIC_PATTERNS):
        return "gastric_cancer"
    if _match_patterns(candidate, _GIST_PATTERNS):
        return "gist"
    if _match_patterns(candidate, _LUNG_PATTERNS):
        return "nsclc_egfr"
    if _match_patterns(candidate, _BREAST_PATTERNS):
        return "breast_hr+/her2-"
    if _match_patterns(candidate, _SUPPORTIVE_PATTERNS):
        return "supportive_care"
    normalized_fallback = str(fallback or "").strip().lower()
    if normalized_fallback and normalized_fallback not in {"unknown", "other"}:
        return normalized_fallback
    return "unknown"


def is_nosology_mapped(cancer_type: str) -> bool:
    normalized = str(cancer_type or "").strip().lower()
    return bool(normalized and normalized not in {"unknown", "other"})


def apply_unknown_nosology_fallback(cancer_type: str) -> tuple[str, str]:
    normalized = str(cancer_type or "").strip().lower()
    if normalized in {"", "unknown", "other", "none", "null", "auto"}:
        return "general_oncology", "fallback_general_oncology"
    return normalized, ""


def enrich_doc_with_nosology(doc: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(doc)
    inferred = infer_cancer_type_for_guideline(
        doc_id=str(enriched.get("doc_id") or ""),
        source_url=str(enriched.get("source_url") or ""),
        title=str(enriched.get("title") or enriched.get("doc_id") or ""),
        fallback=str(enriched.get("cancer_type") or ""),
    )
    normalized, inference = apply_unknown_nosology_fallback(inferred)
    enriched["cancer_type"] = normalized
    enriched["nosology_mapped"] = is_nosology_mapped(normalized)
    if inference:
        enriched["nosology_inference"] = inference
    return enriched
