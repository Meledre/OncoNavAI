from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone pattern intentionally targets classic phone groupings and avoids date-like fragments (YYYY-MM-DD).
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+7|8)\d{10}(?!\w)|(?<!\w)(?:\+?\d{1,3}[\s().-]*)?(?:\(?\d{3}\)?[\s().-]*)\d{3}[\s().-]*\d{2}[\s().-]*\d{2}(?!\w)"
)

# Basic RU/EN full-name style pattern (heuristic only).
FULL_NAME_RE = re.compile(r"\b[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+)?\b")


@dataclass(frozen=True)
class PIIMatch:
    kind: str
    value: str


def find_pii(text: str) -> list[PIIMatch]:
    if not text:
        return []

    matches: list[PIIMatch] = []
    for regex, kind in ((EMAIL_RE, "email"), (PHONE_RE, "phone"), (FULL_NAME_RE, "full_name")):
        for found in regex.findall(text):
            matches.append(PIIMatch(kind=kind, value=found))
    return matches


def contains_pii(texts: Iterable[str]) -> bool:
    for text in texts:
        if find_pii(text):
            return True
    return False


def redact_pii(text: str) -> str:
    if not text:
        return ""
    value = text
    value = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = PHONE_RE.sub("[REDACTED_PHONE]", value)
    value = FULL_NAME_RE.sub("[REDACTED_NAME]", value)
    return value
