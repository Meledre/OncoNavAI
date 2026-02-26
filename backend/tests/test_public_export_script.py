from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_public_export_script_exists_with_required_cli_flags() -> None:
    script = _repo_root() / "scripts" / "public_export.sh"
    text = script.read_text()

    assert "--public-repo-url" in text
    assert "--branch" in text
    assert "--workdir" in text
    assert "--commit-message" in text
    assert "--dry-run" in text
    assert "--no-push" in text
    assert "--from-working-tree" in text


def test_public_export_script_has_snapshot_sanitize_and_security_gates() -> None:
    script = _repo_root() / "scripts" / "public_export.sh"
    text = script.read_text()

    assert "set -euo pipefail" in text
    assert "trap cleanup EXIT" in text
    assert "require_cmd git" in text
    assert "require_cmd rsync" in text
    assert "require_cmd python3" in text
    assert "require_cmd rg" in text
    assert "git archive --format=tar HEAD" in text
    assert "PUBLIC_EXPORT_MANIFEST.json" in text
    assert "python3" in text and "scripts/security_gate.py" in text and "--strict" in text
    assert "PRIVATE KEY" in text
    assert "ghp_" in text
    assert "AKIA" in text
    assert "sk-" in text
    assert "token|secret|password" in text
    assert "example" in text
    assert "placeholder" in text
    assert "changeme" in text
    assert "demo-token" in text
    assert "dev-idp-secret" in text


def test_public_export_script_has_whitelist_and_publish_flow() -> None:
    script = _repo_root() / "scripts" / "public_export.sh"
    text = script.read_text()

    assert "backend" in text
    assert "frontend" in text
    assert "infra" in text
    assert "scripts" in text
    assert "README.md" in text
    assert "README.en.md" in text
    assert "LICENSE" in text
    assert "COPYRIGHT" in text
    assert ".env.example" in text
    assert ".dockerignore" in text
    assert ".gitignore" in text
    assert "No changes to publish" in text
    assert "add -A" in text
    assert "commit -m" in text
    assert "push origin" in text
