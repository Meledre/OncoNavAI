from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.llm.prompt_registry import PromptRegistry
from backend.app.llm.prompt_schema_guard import (
    PromptSchemaMismatchError,
    guard_and_normalize_system_prompt,
)


def test_prompt_registry_loads_prompt_from_filesystem(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "doctor_report_v1_1_system_prompt.md").write_text("doctor prompt body", encoding="utf-8")

    registry = PromptRegistry(prompts_dir=prompts_dir)
    prompt = registry.load("doctor_report_v1_1_system_prompt")

    assert prompt == "doctor prompt body"


def test_prompt_schema_guard_rejects_incompatible_prompt_in_strict_mode() -> None:
    schema = {
        "type": "object",
        "required": ["summary", "issues"],
        "properties": {
            "summary": {"type": "string"},
            "issues": {"type": "array"},
        },
    }
    incompatible_prompt = "Верни JSON с полями: patient_summary, checklist, disclaimer_md"

    with pytest.raises(PromptSchemaMismatchError):
        guard_and_normalize_system_prompt(
            prompt_key="doctor_report_v1_1_system_prompt",
            prompt_text=incompatible_prompt,
            output_schema=schema,
            strict_mode=True,
        )


def test_prompt_schema_guard_appends_contract_first_constraints() -> None:
    schema = {
        "type": "object",
        "required": ["summary", "issues", "missing_data", "notes"],
        "properties": {
            "summary": {"type": "string"},
            "issues": {"type": "array"},
            "missing_data": {"type": "array"},
            "notes": {"type": "string"},
        },
    }
    prompt = "Ты формируешь отчёт для врача."

    normalized = guard_and_normalize_system_prompt(
        prompt_key="doctor_report_v1_1_system_prompt",
        prompt_text=prompt,
        output_schema=schema,
        strict_mode=False,
    )

    assert "CONTRACT-FIRST OUTPUT KEYS" in normalized
    assert "summary" in normalized
    assert "issues" in normalized
    assert "missing_data" in normalized
    assert "notes" in normalized
