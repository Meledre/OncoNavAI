from __future__ import annotations

from pathlib import Path


def test_compose_has_offline_ready_image_and_build_args() -> None:
    compose_path = Path(__file__).resolve().parents[2] / "infra" / "docker-compose.yml"
    text = compose_path.read_text()

    assert "image: oncoai/backend:local" in text
    assert "image: oncoai/frontend:local" in text
    assert "PIP_INSTALL_MODE" in text
    assert "NPM_INSTALL_MODE" in text


def test_offline_compose_override_exists_and_forces_offline_modes() -> None:
    offline_path = Path(__file__).resolve().parents[2] / "infra" / "docker-compose.offline.yml"
    text = offline_path.read_text()

    assert "PIP_INSTALL_MODE: offline" in text
    assert "NPM_INSTALL_MODE: offline" in text
