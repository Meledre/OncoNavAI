from __future__ import annotations

import re


_TOKEN_REPLACEMENTS = {
    "contraindication": "противопоказание",
    "contraindications": "противопоказания",
    "warning": "предупреждение",
    "warnings": "предупреждения",
    "precaution": "мера предосторожности",
    "interactions": "взаимодействия",
    "interaction": "взаимодействие",
    "adverse reactions": "нежелательные реакции",
    "adverse reaction": "нежелательная реакция",
    "serious": "серьезный",
    "severe": "тяжелый",
    "avoid": "избегать",
    "monitor": "контролировать",
    "use with caution": "применять с осторожностью",
    "risk": "риск",
    "bleeding": "кровотечение",
    "hepatotoxicity": "гепатотоксичность",
    "neutropenia": "нейтропения",
    "myelosuppression": "миелосупрессия",
}


def _contains_cyrillic(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", str(value or "")))


def _normalize_sentence(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    return text[:900]


def translate_safety_line_to_ru(value: str) -> str:
    text = _normalize_sentence(value)
    if not text:
        return ""
    if _contains_cyrillic(text):
        return text
    lowered = text.lower()
    translated = lowered
    for source, target in _TOKEN_REPLACEMENTS.items():
        translated = translated.replace(source, target)
    if translated == lowered:
        return f"Требуется клиническая интерпретация (EN): {text}"
    translated = translated[:1].upper() + translated[1:]
    return translated


def translate_safety_lines_to_ru(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        translated = translate_safety_line_to_ru(raw)
        key = translated.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(translated)
    return out[:10]

