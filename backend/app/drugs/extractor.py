from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from backend.app.drugs.models import DrugEvidenceSpan, DrugExtractedInn, DrugUnresolvedCandidate


_SEPARATOR_PATTERN = re.compile(r"[\s\-_]+")
_MEDICATION_CONTEXT_PATTERN = re.compile(
    r"\b(?:терапия|химиотерапия|лечение|назнач(?:ен|ена|ить|ена)|получал(?:а)?|принимает)\b",
    flags=re.IGNORECASE,
)
_MED_LIKE_TOKEN_PATTERN = re.compile(
    r"\b([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9\-/]{3,40})\b",
    flags=re.IGNORECASE,
)


def _normalize_token(value: str) -> str:
    return _SEPARATOR_PATTERN.sub(" ", str(value or "").lower().replace("ё", "е")).strip()


def _alias_to_regex(alias: str) -> re.Pattern[str] | None:
    token = _normalize_token(alias)
    if not token:
        return None
    parts = [re.escape(item) for item in token.split(" ") if item]
    if not parts:
        return None
    body = r"[\s\-_]*".join(parts)
    return re.compile(rf"(?<![0-9A-Za-zА-Яа-яЁё]){body}(?![0-9A-Za-zА-Яа-яЁё])", flags=re.IGNORECASE)


def _parse_page_map(page_map: dict[int, tuple[int, int]] | None) -> dict[int, tuple[int, int]]:
    if not isinstance(page_map, dict):
        return {}
    out: dict[int, tuple[int, int]] = {}
    for key, value in page_map.items():
        if not isinstance(value, tuple) or len(value) != 2:
            continue
        page = int(key)
        start, end = int(value[0]), int(value[1])
        if page <= 0 or start < 0 or end < start:
            continue
        out[page] = (start, end)
    return out


def _page_from_position(page_map: dict[int, tuple[int, int]], pos: int) -> int | None:
    for page, (start, end) in page_map.items():
        if start <= pos <= end:
            return page
    return None


def _build_evidence_span(text: str, start: int, end: int, page_map: dict[int, tuple[int, int]]) -> DrugEvidenceSpan:
    safe_start = max(0, min(start, len(text)))
    safe_end = max(safe_start, min(end, len(text)))
    return DrugEvidenceSpan(
        text=text[safe_start:safe_end].strip(),
        char_start=safe_start,
        char_end=safe_end,
        page=_page_from_position(page_map, safe_start),
    )


def _sorted_aliases_with_patterns(items: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for item in sorted({str(alias or "").strip() for alias in items if str(alias or "").strip()}, key=len, reverse=True):
        pattern = _alias_to_regex(item)
        if pattern is None:
            continue
        out.append((item, pattern))
    return out


def extract_drugs_and_regimens(
    *,
    case_text: str,
    entries: list[dict[str, Any]],
    regimens: list[dict[str, Any]],
    synonyms_extra: dict[str, Any] | None = None,
    page_map: dict[int, tuple[int, int]] | None = None,
) -> tuple[list[DrugExtractedInn], list[DrugUnresolvedCandidate]]:
    text = str(case_text or "")
    if not text.strip():
        return [], []
    page_lookup = _parse_page_map(page_map)

    inn_to_mentions: dict[str, set[str]] = defaultdict(set)
    inn_to_spans: dict[str, list[DrugEvidenceSpan]] = defaultdict(list)
    inn_to_source: dict[str, str] = {}
    inn_to_confidence: dict[str, float] = {}

    # Regimen-first extraction.
    for regimen_item in regimens:
        if not isinstance(regimen_item, dict):
            continue
        aliases = regimen_item.get("aliases_ru") if isinstance(regimen_item.get("aliases_ru"), list) else []
        regimen_name = str(regimen_item.get("regimen") or "").strip()
        components = [str(value).strip().lower() for value in (regimen_item.get("components_inn") or []) if str(value).strip()]
        alias_patterns = _sorted_aliases_with_patterns([regimen_name, *[str(alias) for alias in aliases]])
        for alias, pattern in alias_patterns:
            for match in pattern.finditer(text):
                span = _build_evidence_span(text, match.start(), match.end(), page_lookup)
                for inn in components:
                    if not inn:
                        continue
                    inn_to_mentions[inn].add(alias)
                    inn_to_spans[inn].append(span)
                    inn_to_source[inn] = "regimen"
                    inn_to_confidence[inn] = max(inn_to_confidence.get(inn, 0.0), 0.95)

    # Drug mention extraction.
    alias_to_inn: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        inn = str(entry.get("inn") or "").strip().lower()
        if not inn:
            continue
        for alias in [*entry.get("ru_names", []), *entry.get("en_names", [])]:
            normalized_alias = str(alias or "").strip()
            if not normalized_alias:
                continue
            alias_to_inn[normalized_alias] = inn

    shortcuts = synonyms_extra.get("ru_shortcuts") if isinstance(synonyms_extra, dict) else []
    for shortcut in shortcuts if isinstance(shortcuts, list) else []:
        if not isinstance(shortcut, dict):
            continue
        pattern_text = str(shortcut.get("pattern") or "").strip()
        maps_to_inn = str(shortcut.get("maps_to_inn") or "").strip().lower()
        if not pattern_text or not maps_to_inn:
            continue
        try:
            pattern = re.compile(pattern_text, flags=re.IGNORECASE)
        except re.error:
            continue
        for match in pattern.finditer(text):
            span = _build_evidence_span(text, match.start(), match.end(), page_lookup)
            mention = span.text or text[match.start() : match.end()]
            inn_to_mentions[maps_to_inn].add(mention)
            inn_to_spans[maps_to_inn].append(span)
            if inn_to_source.get(maps_to_inn) != "regimen":
                inn_to_source[maps_to_inn] = "drug"
            inn_to_confidence[maps_to_inn] = max(inn_to_confidence.get(maps_to_inn, 0.0), 0.9)

    for alias, alias_pattern in _sorted_aliases_with_patterns(list(alias_to_inn.keys())):
        for match in alias_pattern.finditer(text):
            span = _build_evidence_span(text, match.start(), match.end(), page_lookup)
            mention = span.text or text[match.start() : match.end()]
            resolved_inn = alias_to_inn.get(alias, "")
            if not resolved_inn:
                continue
            inn_to_mentions[resolved_inn].add(mention)
            inn_to_spans[resolved_inn].append(span)
            if inn_to_source.get(resolved_inn) != "regimen":
                inn_to_source[resolved_inn] = "drug"
            inn_to_confidence[resolved_inn] = max(inn_to_confidence.get(resolved_inn, 0.0), 0.9)

    extracted: list[DrugExtractedInn] = []
    for inn, mentions in sorted(inn_to_mentions.items(), key=lambda item: item[0]):
        source_value = inn_to_source.get(inn, "drug")
        confidence = inn_to_confidence.get(inn, 0.7)
        extracted.append(
            DrugExtractedInn(
                inn=inn,
                mentions=sorted(mentions),
                source=source_value if source_value in {"regimen", "drug", "fallback"} else "fallback",
                confidence=max(0.0, min(1.0, float(confidence))),
                evidence_spans=inn_to_spans.get(inn, [])[:20],
            )
        )

    # Unresolved candidates near medication context.
    unresolved: list[DrugUnresolvedCandidate] = []
    known_mentions_normalized = {_normalize_token(mention) for mentions in inn_to_mentions.values() for mention in mentions}
    for context_match in _MEDICATION_CONTEXT_PATTERN.finditer(text):
        window_start = context_match.start()
        window_end = min(len(text), context_match.end() + 220)
        snippet = text[window_start:window_end]
        for token_match in _MED_LIKE_TOKEN_PATTERN.finditer(snippet):
            candidate = str(token_match.group(1) or "").strip()
            normalized_candidate = _normalize_token(candidate)
            if not normalized_candidate or len(normalized_candidate) < 4:
                continue
            if normalized_candidate in known_mentions_normalized:
                continue
            if re.fullmatch(r"[0-9\-/]+", normalized_candidate):
                continue
            unresolved.append(
                DrugUnresolvedCandidate(
                    mention=candidate,
                    context=snippet.strip()[:400],
                    reason="not_found_in_dictionary",
                )
            )
        if len(unresolved) >= 20:
            break

    dedup_unresolved: list[DrugUnresolvedCandidate] = []
    seen_candidates: set[str] = set()
    for item in unresolved:
        key = _normalize_token(item.mention)
        if not key or key in seen_candidates:
            continue
        seen_candidates.add(key)
        dedup_unresolved.append(item)

    return extracted, dedup_unresolved[:20]
