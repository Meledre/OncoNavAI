from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.exceptions import ValidationError


@dataclass(frozen=True)
class DrugDictionaryBundle:
    schema: str
    version: str
    notes: str
    entries: list[dict[str, Any]]
    regimen_aliases: list[dict[str, Any]]
    synonyms_extra: dict[str, Any]
    sha256: str


def _normalize_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalize_entries(raw_entries: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_entries, list):
        raise ValidationError("drug_dictionary must be an array")
    normalized: list[dict[str, Any]] = []
    seen_inn: set[str] = set()
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        inn = str(item.get("inn") or "").strip().lower()
        if not inn or inn in seen_inn:
            continue
        seen_inn.add(inn)
        normalized.append(
            {
                "inn": inn,
                "ru_names": _normalize_text_list(item.get("ru_names")),
                "en_names": _normalize_text_list(item.get("en_names")),
                "group": str(item.get("group") or "other").strip().lower() or "other",
            }
        )
    if not normalized:
        raise ValidationError("drug_dictionary has no valid entries")
    return normalized


def _normalize_regimens(raw_regimens: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_regimens, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_regimens: set[str] = set()
    for item in raw_regimens:
        if not isinstance(item, dict):
            continue
        regimen = str(item.get("regimen") or "").strip().upper()
        if not regimen or regimen in seen_regimens:
            continue
        seen_regimens.add(regimen)
        normalized.append(
            {
                "regimen": regimen,
                "aliases_ru": _normalize_text_list(item.get("aliases_ru")),
                "components_inn": [str(comp).strip().lower() for comp in (item.get("components_inn") or []) if str(comp).strip()],
                "notes": str(item.get("notes") or "").strip(),
            }
        )
    return normalized


def load_drug_dictionary_bundle_from_text(content: str, *, content_sha256: str | None = None) -> DrugDictionaryBundle:
    try:
        payload = json.loads(str(content or ""))
    except json.JSONDecodeError as exc:
        raise ValidationError("Invalid drug dictionary JSON payload") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Drug dictionary payload must be an object")

    schema = str(payload.get("schema") or "").strip()
    if schema and not schema.startswith("urn:onco:drug_dictionary_ru_inn"):
        raise ValidationError("Unsupported drug dictionary schema")

    version = str(payload.get("version") or "").strip()
    if not version:
        raise ValidationError("Drug dictionary version is required")

    entries = _normalize_entries(payload.get("drug_dictionary"))
    regimen_aliases = _normalize_regimens(payload.get("regimen_aliases"))
    synonyms_extra = payload.get("synonyms_extra") if isinstance(payload.get("synonyms_extra"), dict) else {}
    notes = str(payload.get("notes") or "").strip()
    digest = content_sha256 or hashlib.sha256(str(content).encode("utf-8")).hexdigest()
    return DrugDictionaryBundle(
        schema=schema or "urn:onco:drug_dictionary_ru_inn:unknown",
        version=version,
        notes=notes,
        entries=entries,
        regimen_aliases=regimen_aliases,
        synonyms_extra=synonyms_extra,
        sha256=digest,
    )


def load_drug_dictionary_bundle_from_path(path: Path) -> DrugDictionaryBundle:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    sha256 = hashlib.sha256(data).hexdigest()
    return load_drug_dictionary_bundle_from_text(text, content_sha256=sha256)

