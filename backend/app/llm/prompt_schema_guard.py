from __future__ import annotations

import re
from typing import Any


class PromptSchemaMismatchError(RuntimeError):
    pass


_KEY_CANDIDATES = (
    "schema_version",
    "report_id",
    "request_id",
    "kb_version",
    "clinical_summary",
    "patient_summary",
    "disease_context",
    "treatment_history",
    "current_plan",
    "overall_assessment",
    "issues",
    "missing_data",
    "run_meta",
    "checklist",
    "citations",
    "generated_at",
    "disclaimer_md",
    "summary",
    "notes",
    "summary_plain",
    "overall_interpretation",
    "disease_explanation",
    "stage_explanation",
    "treatment_strategy_explanation",
    "key_points",
    "next_steps",
    "questions_for_doctor",
    "questions_to_ask_doctor",
    "what_was_checked",
    "safety_note",
    "safety_notes",
    "safety_disclaimer",
    "based_on_report_id",
    "possible_side_effects",
    "sources_used",
)

_PROMPT_ALIASES_BY_KEY: dict[str, dict[str, str]] = {
    "doctor_report_v1_1_system_prompt": {
        "patient_summary": "clinical_summary",
    },
    "patient_explain_v1_1_system_prompt": {
        "overall_interpretation": "summary_plain",
        "safety_note": "safety_notes",
    },
}


def _extract_schema_keys(output_schema: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    required = output_schema.get("required")
    if isinstance(required, list):
        keys.update(str(item).strip() for item in required if str(item).strip())

    properties = output_schema.get("properties")
    if isinstance(properties, dict):
        keys.update(str(item).strip() for item in properties.keys() if str(item).strip())
    return keys


def _extract_prompt_keys(prompt_text: str) -> set[str]:
    text = str(prompt_text or "")
    keys: set[str] = set()
    for token in _KEY_CANDIDATES:
        pattern = re.compile(rf"(^|[^A-Za-z0-9_]){re.escape(token)}([^A-Za-z0-9_]|$)", re.IGNORECASE)
        if pattern.search(text):
            keys.add(token)
    return keys


def guard_and_normalize_system_prompt(
    *,
    prompt_key: str,
    prompt_text: str,
    output_schema: dict[str, Any] | None,
    strict_mode: bool,
) -> str:
    base = str(prompt_text or "").strip()
    if not base:
        return ""
    if not isinstance(output_schema, dict):
        return base

    schema_keys = _extract_schema_keys(output_schema)
    prompt_keys = _extract_prompt_keys(base)
    alias_map = _PROMPT_ALIASES_BY_KEY.get(str(prompt_key).strip(), {})
    alias_keys = set(alias_map.keys())

    incompatible = sorted(prompt_keys - schema_keys - alias_keys)
    if strict_mode and incompatible:
        raise PromptSchemaMismatchError(
            f"Prompt `{prompt_key}` contains keys incompatible with output schema: {', '.join(incompatible)}"
        )

    contract_required = output_schema.get("required")
    if not isinstance(contract_required, list):
        contract_required = sorted(schema_keys)
    required_text = ", ".join(str(item).strip() for item in contract_required if str(item).strip())

    alias_hint_lines = []
    for legacy_key, canonical_key in sorted(alias_map.items()):
        alias_hint_lines.append(f"- `{legacy_key}` -> `{canonical_key}`")
    alias_hints = "\n".join(alias_hint_lines)

    normalized_parts = [
        base,
        "",
        "CONTRACT-FIRST OUTPUT KEYS",
        f"Required top-level keys: {required_text}",
        "If any instruction conflicts with schema keys, follow schema keys only.",
    ]
    if alias_hints:
        normalized_parts.extend(
            [
                "Legacy key mapping (for interpretation only; output must use schema keys):",
                alias_hints,
            ]
        )
    normalized_parts.append("Return valid JSON only.")
    return "\n".join(part for part in normalized_parts if part is not None).strip()

