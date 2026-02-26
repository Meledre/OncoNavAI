from __future__ import annotations

from pathlib import Path


PROMPT_FILE_MAP: dict[str, str] = {
    "doctor_report_v1_1_system_prompt": "doctor_report_v1_1_system_prompt.md",
    "patient_explain_v1_1_system_prompt": "patient_explain_v1_1_system_prompt.md",
}


class PromptRegistry:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir
        self._cache: dict[str, str] = {}

    def _resolve_filename(self, prompt_key: str) -> str:
        mapped = PROMPT_FILE_MAP.get(prompt_key.strip())
        if mapped:
            return mapped
        key = prompt_key.strip()
        if key.endswith(".md"):
            return key
        return f"{key}.md"

    def load(self, prompt_key: str) -> str:
        key = str(prompt_key or "").strip()
        if not key:
            raise ValueError("prompt_key is required")
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        filename = self._resolve_filename(key)
        path = self.prompts_dir / filename
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise RuntimeError(f"Prompt file is empty: {path}")
        self._cache[key] = content
        return content

    def load_optional(self, prompt_key: str) -> str | None:
        try:
            return self.load(prompt_key)
        except Exception:  # noqa: BLE001
            return None

