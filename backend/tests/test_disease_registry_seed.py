from __future__ import annotations

import json
import re
from pathlib import Path

from backend.app.service import OncoService


_ICD10_PREFIX_PATTERN = re.compile(r"^C\d{2}$")


def _extract_c_prefixes(entries: list[dict]) -> set[str]:
    prefixes: set[str] = set()
    for entry in entries:
        codes = entry.get("icd10_codes")
        if not isinstance(codes, list):
            continue
        for raw_code in codes:
            normalized = str(raw_code).strip().upper().split(".", 1)[0]
            if _ICD10_PREFIX_PATTERN.fullmatch(normalized):
                prefixes.add(normalized)
    return prefixes


def test_disease_registry_seed_covers_full_icd10_c_group() -> None:
    seed_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "contracts"
        / "onco_json_pack_v1"
        / "seeds"
        / "disease_registry.seed.json"
    )
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)

    prefixes = _extract_c_prefixes(payload)
    expected = {f"C{idx:02d}" for idx in range(98)}
    missing = sorted(expected - prefixes)
    assert not missing


def test_builtin_disease_registry_seed_covers_full_icd10_c_group() -> None:
    payload = OncoService._builtin_disease_registry_seed()

    prefixes = _extract_c_prefixes(payload)
    expected = {f"C{idx:02d}" for idx in range(98)}
    missing = sorted(expected - prefixes)
    assert not missing
