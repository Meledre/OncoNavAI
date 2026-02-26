from __future__ import annotations

from pathlib import Path


def test_frontend_dockerfile_handles_missing_package_lock() -> None:
    dockerfile = Path(__file__).resolve().parents[2] / "frontend" / "Dockerfile"
    text = dockerfile.read_text()

    assert "if [ -f package-lock.json ]" in text
    assert "npm ci" in text
    assert "npm install" in text


def test_prefetch_script_handles_missing_package_lock() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "prefetch_deps.sh"
    text = script.read_text()

    assert "if [ -f package-lock.json ]" in text
    assert "npm ci" in text
    assert "npm install" in text


def test_prefetch_script_downloads_backend_wheels_for_linux_python311() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "prefetch_deps.sh"
    text = script.read_text()

    assert "--python-version 3.11" in text
    assert "manylinux2014_aarch64" in text
    assert "manylinux2014_x86_64" in text
    assert "--abi cp311" in text
    assert "--only-binary=:all:" in text
    assert "pip download" in text


def test_prefetch_script_primes_next_swc_cache_for_offline_frontend_runtime() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "prefetch_deps.sh"
    text = script.read_text()

    assert "npm cache add" in text
    assert "@next/swc-linux-arm64-gnu" in text
    assert "@next/swc-linux-x64-gnu" in text
