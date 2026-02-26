from __future__ import annotations

import re
from typing import Iterable


_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bNo critical mismatch detected\b", re.IGNORECASE),
        "Критических расхождений не выявлено",
    ),
    (
        re.compile(
            r"\bThe current plan appears broadly aligned with available guideline fragments\.?\b",
            re.IGNORECASE,
        ),
        "Текущий план в целом согласуется с доступными фрагментами клинических рекомендаций.",
    ),
    (
        re.compile(r"\bFound\s+(\d+)\s+potential issue\(s\)\s+while checking treatment plan against indexed guidance\.?\b", re.IGNORECASE),
        r"Выявлено \1 потенциальных замечаний при проверке плана лечения по индексированным рекомендациям.",
    ),
    (
        re.compile(r"\bpost-progression\b", re.IGNORECASE),
        "после прогрессирования",
    ),
    (
        re.compile(r"\bPotential issue\b", re.IGNORECASE),
        "Потенциальное замечание",
    ),
    (
        re.compile(r"\bNo retrieved evidence for selected filters and current query\.?\b", re.IGNORECASE),
        "Не найдено подтверждающих фрагментов рекомендаций для выбранных фильтров и запроса.",
    ),
    (
        re.compile(r"\bNo evidence-backed assertions could be produced for this case\.?\b", re.IGNORECASE),
        "По текущему кейсу не удалось сформировать утверждения с доказательной поддержкой.",
    ),
    (
        re.compile(r"\bSufficient evidence available\.?\b", re.IGNORECASE),
        "Достаточно подтверждающих данных.",
    ),
)


def normalize_ru_clinical_text(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    for pattern, replacement in _PHRASE_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_ru_texts(values: Iterable[str]) -> list[str]:
    return [normalize_ru_clinical_text(item) for item in values]

