from __future__ import annotations

import re
from typing import Any


_ICD10_PATTERN = re.compile(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,2})?)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9]+", re.UNICODE)
_GASTRIC_RE = re.compile(r"(рак|карцин|аденокарц|gastric|stomach).{0,40}(желуд|stomach|gastric)|(желуд|stomach|gastric).{0,40}(рак|карцин|аденокарц|cancer)", re.IGNORECASE)
_ESOPHAGUS_RE = re.compile(r"(рак|карцин|cancer).{0,40}(пищевод|esophag)|(пищевод|esophag).{0,40}(рак|карцин|cancer)", re.IGNORECASE)
_BREAST_RE = re.compile(
    r"(рак|карцин|cancer).{0,35}(молочн\w*\s+желез|breast)|"
    r"(молочн\w*\s+желез|breast).{0,35}(рак|карцин|cancer)|"
    r"\btriple[-\s]?negative\b",
    re.IGNORECASE,
)
_LUNG_PRIMARY_RE = re.compile(
    r"(рак\s+л[её]гк\w*|немелкоклеточ\w*\s+рак\s+л[её]гк\w*|nsclc|lung\s+cancer)",
    re.IGNORECASE,
)
_CNS_METS_RE = re.compile(
    r"(метастаз\w*).{0,45}(головн\w*\s+мозг|цнс)|"
    r"(головн\w*\s+мозг|цнс).{0,45}(метастаз\w*)|"
    r"(brain|cns).{0,20}(metasta)",
    re.IGNORECASE,
)
_BRAIN_PRIMARY_RE = re.compile(
    r"(глиобласт|астроцитом|олигодендроглиом|glioblast|astrocytom|oligodendrogliom)|"
    r"(первичн\w*).{0,45}(опухол\w*).{0,20}(головн\w*\s+мозг)|"
    r"(malignant).{0,20}(brain).{0,20}(tumor)",
    re.IGNORECASE,
)


def _normalize_code(value: str) -> str:
    match = _ICD10_PATTERN.search(str(value or "").strip())
    return str(match.group(1)).upper() if match else ""


def _tokenize(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _TOKEN_RE.findall(str(value or "").lower()):
        token = raw.strip()
        if len(token) < 3:
            continue
        tokens.add(token)
    return tokens


def _infer_by_disease_registry(text: str, disease_registry: list[dict[str, Any]]) -> tuple[str, float, str]:
    normalized_text = str(text or "").lower()
    best_code = ""
    best_score = 0.0
    best_reason = ""

    for entry in disease_registry:
        if not isinstance(entry, dict):
            continue
        codes = entry.get("icd10_codes") if isinstance(entry.get("icd10_codes"), list) else []
        code = _normalize_code(str(codes[0])) if codes else ""
        if not code:
            continue
        candidates: list[str] = []
        for key in ("disease_name_ru", "disease_name_en"):
            value = str(entry.get(key) or "").strip().lower()
            if value:
                candidates.append(value)
        synonyms = entry.get("common_synonyms") if isinstance(entry.get("common_synonyms"), list) else []
        candidates.extend(str(item or "").strip().lower() for item in synonyms if str(item or "").strip())

        local_score = 0.0
        local_reason = ""
        for candidate in candidates:
            if len(candidate) < 4:
                continue
            if candidate in normalized_text:
                score = 0.6 + min(len(candidate), 32) / 80.0
                if score > local_score:
                    local_score = score
                    local_reason = candidate
        if local_score > best_score:
            best_score = local_score
            best_code = code
            best_reason = local_reason

    if best_score < 0.72:
        return "", 0.0, ""
    return best_code, min(best_score, 0.95), best_reason


def _infer_by_reference(text: str, icd10_reference: list[dict[str, Any]]) -> tuple[str, float, str]:
    query_tokens = _tokenize(text)
    if not query_tokens:
        return "", 0.0, ""

    best_code = ""
    best_score = 0.0
    best_title = ""
    for row in icd10_reference:
        if not isinstance(row, dict):
            continue
        code = _normalize_code(str(row.get("code") or ""))
        title = str(row.get("title_ru") or "").strip()
        if not code or not title:
            continue
        title_tokens = _tokenize(title)
        if len(title_tokens) < 2:
            continue
        overlap = query_tokens.intersection(title_tokens)
        overlap_count = len(overlap)
        if overlap_count < 2:
            continue
        score = overlap_count / float(len(title_tokens))
        if score > best_score:
            best_score = score
            best_code = code
            best_title = title

    if best_score < 0.45:
        return "", 0.0, ""
    return best_code, min(0.85, 0.55 + best_score), best_title


def infer_icd10_code(
    *,
    text: str,
    explicit_code: str = "",
    disease_registry: list[dict[str, Any]] | None = None,
    icd10_reference: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_text = str(text or "")
    explicit = _normalize_code(explicit_code)
    if not explicit:
        explicit = _normalize_code(normalized_text)
    if explicit:
        return {
            "code": explicit,
            "confidence": 1.0,
            "method": "explicit",
            "reason": "code_present_in_text",
        }

    if _GASTRIC_RE.search(normalized_text):
        return {
            "code": "C16",
            "confidence": 0.82,
            "method": "keyword_heuristic",
            "reason": "gastric_keyword_match",
        }
    if _ESOPHAGUS_RE.search(normalized_text):
        return {
            "code": "C15",
            "confidence": 0.8,
            "method": "keyword_heuristic",
            "reason": "esophagus_keyword_match",
        }
    if _BREAST_RE.search(normalized_text):
        return {
            "code": "C50",
            "confidence": 0.82,
            "method": "keyword_heuristic",
            "reason": "breast_keyword_match",
        }
    if _LUNG_PRIMARY_RE.search(normalized_text):
        return {
            "code": "C34",
            "confidence": 0.8,
            "method": "keyword_heuristic",
            "reason": "lung_primary_keyword_match",
        }
    if _CNS_METS_RE.search(normalized_text):
        return {
            "code": "C79.3",
            "confidence": 0.84,
            "method": "keyword_heuristic",
            "reason": "cns_metastasis_keyword_match",
        }
    if _BRAIN_PRIMARY_RE.search(normalized_text):
        return {
            "code": "C71",
            "confidence": 0.82,
            "method": "keyword_heuristic",
            "reason": "brain_primary_keyword_match",
        }

    registry = disease_registry if isinstance(disease_registry, list) else []
    code, confidence, reason = _infer_by_disease_registry(normalized_text, registry)
    if code:
        return {
            "code": code,
            "confidence": confidence,
            "method": "disease_registry",
            "reason": reason or "registry_synonym_match",
        }

    reference_rows = icd10_reference if isinstance(icd10_reference, list) else []
    code, confidence, reason = _infer_by_reference(normalized_text, reference_rows)
    if code:
        return {
            "code": code,
            "confidence": confidence,
            "method": "icd10_reference",
            "reason": reason or "reference_overlap_match",
        }

    return {
        "code": "",
        "confidence": 0.0,
        "method": "none",
        "reason": "insufficient_signal",
    }
