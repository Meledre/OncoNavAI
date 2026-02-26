from __future__ import annotations

import re
from typing import Any


_LINE_START_RE = re.compile(r"^\s*([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,2})?)\s*[-–—:)]?\s+(.+?)\s*$")
_ANY_CODE_RE = re.compile(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,2})?)\b")
_GLOBAL_CODE_TITLE_RE = re.compile(
    r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,2})?)\b\s+(.+?)(?=\b[A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,2})?\b|$)",
    re.DOTALL,
)
_TITLE_STOP_RE = re.compile(r"\b(Включено|Исключено|Примечание|ЗЛОКАЧЕСТВЕННЫЕ)\b", re.IGNORECASE)


def _normalize_title(value: str) -> str:
    text = str(value or "").replace("\t", " ").strip(" -–—:;,.")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_icd10_reference_entries(text: str) -> list[dict[str, str]]:
    """Extract ICD-10 rows from raw MKB-10 text."""
    if not isinstance(text, str) or not text.strip():
        return []

    by_code: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 4:
            continue

        code = ""
        title = ""
        start_match = _LINE_START_RE.match(line)
        if start_match:
            code = str(start_match.group(1)).upper()
            title = _normalize_title(start_match.group(2))
        else:
            any_match = _ANY_CODE_RE.search(line)
            if not any_match:
                continue
            if any_match.start() > 3:
                continue
            code = str(any_match.group(1)).upper()
            title = _normalize_title(line[any_match.end() :])

        if not code or not title:
            continue
        if not re.search(r"[A-Za-zА-Яа-я]", title):
            continue
        existing = by_code.get(code)
        if not existing or len(title) > len(existing):
            by_code[code] = title

    # Fallback for compressed PDF extraction where many ICD lines become one stream.
    if len(by_code) < 20:
        normalized_text = " ".join(part.strip() for part in text.splitlines() if part.strip())
        for match in _GLOBAL_CODE_TITLE_RE.finditer(normalized_text):
            code = str(match.group(1) or "").upper()
            title_raw = _normalize_title(str(match.group(2) or ""))
            if not code or not title_raw:
                continue
            title_raw = _TITLE_STOP_RE.split(title_raw)[0].strip(" -–—:;,")
            title = _normalize_title(title_raw)
            if not title or not re.search(r"[A-Za-zА-Яа-я]", title):
                continue
            existing = by_code.get(code)
            if not existing or len(title) > len(existing):
                by_code[code] = title

    return [{"code": code, "title_ru": title} for code, title in sorted(by_code.items())]


def parse_icd10_reference_entries_from_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    parts: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text") or "").strip()
        if text:
            parts.append(text)
    return parse_icd10_reference_entries("\n".join(parts))
