from __future__ import annotations

from typing import Any

from backend.app.exceptions import ValidationError

CASE_IMPORT_SCHEMA_VERSION = "1.0"
SUPPORTED_CASE_IMPORT_PROFILES = frozenset(
    {
        "FREE_TEXT",
        "CUSTOM_TEMPLATE",
        "FHIR_BUNDLE",
        "KIN_PDF",
    }
)
SUPPORTED_CASE_DATA_MODES = frozenset({"DEID", "FULL"})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def normalize_case_import_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(payload, dict), "case import payload must be an object")

    normalized = dict(payload)
    schema_version = str(normalized.get("schema_version") or CASE_IMPORT_SCHEMA_VERSION).strip()
    _require(schema_version == CASE_IMPORT_SCHEMA_VERSION, "case import schema_version must be 1.0")
    normalized["schema_version"] = CASE_IMPORT_SCHEMA_VERSION

    import_profile = str(normalized.get("import_profile") or "").strip().upper()
    _require(bool(import_profile), "import_profile is required")
    normalized["import_profile"] = import_profile

    explicit_data_mode = "data_mode" in normalized and normalized.get("data_mode") is not None
    data_mode = str(normalized.get("data_mode") or "DEID").strip().upper()
    _require(data_mode in SUPPORTED_CASE_DATA_MODES, "data_mode must be DEID or FULL")
    normalized["data_mode"] = data_mode

    if "full_mode_acknowledged" in normalized and normalized["full_mode_acknowledged"] is not None:
        _require(
            isinstance(normalized["full_mode_acknowledged"], bool),
            "full_mode_acknowledged must be boolean when provided",
        )

    if "case_id" in normalized and normalized["case_id"] is not None:
        _require(_is_non_empty_string(normalized["case_id"]), "case_id must be a non-empty string when provided")

    case_json = normalized.get("case_json")
    if case_json is not None:
        _require(isinstance(case_json, dict), "case_json must be an object when provided")
        case_json_mode = str(case_json.get("data_mode") or "").strip().upper()
        if case_json_mode:
            _require(case_json_mode in SUPPORTED_CASE_DATA_MODES, "case_json.data_mode must be DEID or FULL")
            if explicit_data_mode and case_json_mode != data_mode:
                raise ValidationError("data_mode mismatch: payload.data_mode and case_json.data_mode must match")
            if not explicit_data_mode:
                normalized["data_mode"] = case_json_mode
        return normalized

    if import_profile == "FHIR_BUNDLE":
        _require(isinstance(normalized.get("fhir_bundle"), dict), "FHIR_BUNDLE requires `fhir_bundle` object payload")
        return normalized

    if import_profile == "KIN_PDF":
        kin_text = normalized.get("kin_pdf_text")
        kin_payload = normalized.get("kin_pdf")
        has_text = _is_non_empty_string(kin_text)
        has_payload = isinstance(kin_payload, dict)
        _require(has_text or has_payload, "KIN_PDF requires `kin_pdf_text` or `kin_pdf` payload")
        return normalized

    if import_profile == "FREE_TEXT" and "free_text" in normalized and normalized["free_text"] is not None:
        _require(_is_non_empty_string(normalized["free_text"]), "free_text must be a non-empty string when provided")

    if import_profile == "CUSTOM_TEMPLATE" and "custom_template" in normalized and normalized["custom_template"] is not None:
        _require(isinstance(normalized["custom_template"], dict), "custom_template must be an object when provided")

    return normalized
