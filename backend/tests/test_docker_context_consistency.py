from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_backend_dockerfile_copy_targets_are_not_ignored_by_dockerignore() -> None:
    root = _repo_root()
    dockerfile = (root / "backend" / "Dockerfile").read_text()
    dockerignore_lines = [line.strip() for line in (root / ".dockerignore").read_text().splitlines()]

    if "COPY data /app/data" in dockerfile:
        assert "data/" not in dockerignore_lines


def test_compose_includes_ollama_service_for_local_demo() -> None:
    compose = (_repo_root() / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "  ollama:" in compose
    assert "image: ollama/ollama:latest" in compose
    assert "\"11434:11434\"" in compose


def test_compose_sets_safe_backend_defaults_for_empty_env() -> None:
    compose = (_repo_root() / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ONCOAI_RELEASE_PROFILE=${ONCOAI_RELEASE_PROFILE:-compat}" in compose
    assert "VECTOR_BACKEND=${VECTOR_BACKEND:-local}" in compose
    assert "EMBEDDING_BACKEND=${EMBEDDING_BACKEND:-hash}" in compose
    assert "RERANKER_BACKEND=${RERANKER_BACKEND:-lexical}" in compose
    assert "ONCOAI_DATA_DIR=${ONCOAI_DATA_DIR:-/app/data}" in compose
    assert "ONCOAI_DB_PATH=${ONCOAI_DB_PATH:-/app/data/oncoai.sqlite3}" in compose
