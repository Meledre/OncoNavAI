from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_public_export_deploy_doc_exists_with_security_sections() -> None:
    doc = _repo_root() / "docs" / "deploy" / "public-sanitized-export.md"
    text = doc.read_text()

    assert "# Public Sanitized Export" in text
    assert "./scripts/public_export.sh" in text
    assert "--public-repo-url" in text
    assert "least privilege" in text.lower()
    assert "rotate" in text.lower()
    assert "revoke" in text.lower()


def test_readmes_include_public_export_runbook() -> None:
    readme_ru = (_repo_root() / "README.md").read_text()
    readme_en = (_repo_root() / "README.en.md").read_text()

    assert "public export" in readme_en.lower()
    assert "public" in readme_ru.lower()
    assert "./scripts/public_export.sh" in readme_ru
    assert "./scripts/public_export.sh" in readme_en
    assert "docs/deploy/public-sanitized-export.md" in readme_ru
    assert "docs/deploy/public-sanitized-export.md" in readme_en

