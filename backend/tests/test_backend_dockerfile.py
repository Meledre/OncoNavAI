from __future__ import annotations

from pathlib import Path


def test_backend_dockerfile_copies_contract_seed_pack() -> None:
    dockerfile = Path(__file__).resolve().parents[2] / "backend" / "Dockerfile"
    text = dockerfile.read_text()
    assert "COPY docs/contracts/onco_json_pack_v1 /app/docs/contracts/onco_json_pack_v1" in text
