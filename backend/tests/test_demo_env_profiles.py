from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_demo_api_env_preserves_existing_keys() -> None:
    text = (_repo_root() / ".env.demo.api").read_text(encoding="utf-8")

    assert "LLM_PRIMARY_API_KEY=${LLM_PRIMARY_API_KEY:-${OPENAI_API_KEY:-${EMBEDDING_API_KEY:-}}}" in text
    assert "EMBEDDING_API_KEY=${EMBEDDING_API_KEY:-${OPENAI_API_KEY:-${LLM_PRIMARY_API_KEY:-}}}" in text


def test_demo_local_env_preserves_external_fallback_endpoint() -> None:
    text = (_repo_root() / ".env.demo.local").read_text(encoding="utf-8")

    assert "LLM_FALLBACK_URL=${LLM_FALLBACK_URL:-http://ollama:11434}" in text
    assert "LLM_FALLBACK_MODEL=${LLM_FALLBACK_MODEL:-qwen2.5:0.5b}" in text
    assert "ONCOAI_DEMO_LOCAL_MULTI_ONCO_CASES=${ONCOAI_DEMO_LOCAL_MULTI_ONCO_CASES:-C16}" in text


def test_demo_api_env_defaults_to_single_case_for_low_traffic() -> None:
    text = (_repo_root() / ".env.demo.api").read_text(encoding="utf-8")
    assert "ONCOAI_DEMO_API_MULTI_ONCO_CASES=${ONCOAI_DEMO_API_MULTI_ONCO_CASES:-C16}" in text
