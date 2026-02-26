from __future__ import annotations

from pathlib import Path


def test_backend_requirements_include_python_multipart() -> None:
    req_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    lines = [line.strip() for line in req_path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    assert any(line.startswith("python-multipart") for line in lines)


def test_backend_requirements_include_case_file_extractors() -> None:
    req_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    lines = [line.strip() for line in req_path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    assert any(line.startswith("pypdf") for line in lines)
    assert any(line.startswith("python-docx") for line in lines)
