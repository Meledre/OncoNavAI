from __future__ import annotations

from pathlib import Path

from backend.app.config import load_settings


def test_load_settings_defaults_rag_engine_to_basic(monkeypatch):
    monkeypatch.delenv("RAG_ENGINE", raising=False)
    monkeypatch.delenv("ONCOAI_RELEASE_PROFILE", raising=False)
    settings = load_settings()
    assert settings.rag_engine == "basic"
    assert settings.release_profile == "compat"


def test_load_settings_reads_rag_engine_from_env(monkeypatch):
    monkeypatch.setenv("RAG_ENGINE", "llamaindex")
    monkeypatch.setenv("ONCOAI_RELEASE_PROFILE", "strict_full")
    settings = load_settings()
    assert settings.rag_engine == "llamaindex"
    assert settings.release_profile == "strict_full"


def test_load_settings_treats_empty_env_as_unset(monkeypatch):
    monkeypatch.setenv("ONCOAI_DATA_DIR", "")
    monkeypatch.setenv("ONCOAI_DB_PATH", "")
    monkeypatch.setenv("VECTOR_BACKEND", "")
    monkeypatch.setenv("EMBEDDING_BACKEND", "")
    monkeypatch.setenv("RERANKER_BACKEND", "")
    monkeypatch.setenv("LLM_PRIMARY_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "smoke-key")
    settings = load_settings()
    expected_data_dir = settings.project_root / "data"
    assert settings.data_dir == expected_data_dir
    assert settings.db_path == expected_data_dir / "oncoai.sqlite3"
    assert settings.vector_backend == "local"
    assert settings.embedding_backend == "hash"
    assert settings.reranker_backend == "lexical"
    assert settings.llm_primary_api_key == "smoke-key"


def test_load_settings_preserves_explicit_non_empty_env(monkeypatch):
    monkeypatch.setenv("ONCOAI_DATA_DIR", "/tmp/oncoai-data")
    monkeypatch.setenv("ONCOAI_DB_PATH", "/tmp/oncoai-data/custom.sqlite3")
    monkeypatch.setenv("VECTOR_BACKEND", "qdrant")
    settings = load_settings()
    assert settings.data_dir == Path("/tmp/oncoai-data")
    assert settings.db_path == Path("/tmp/oncoai-data/custom.sqlite3")
    assert settings.vector_backend == "qdrant"


def test_load_settings_falls_back_embedding_key_to_llm_primary(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_PRIMARY_API_KEY", "llm-key")
    settings = load_settings()
    assert settings.embedding_api_key == "llm-key"
