from __future__ import annotations

import base64
import json
from pathlib import Path

from backend.app.config import Settings
from backend.app.drugs.dictionary_loader import load_drug_dictionary_bundle_from_text
from backend.app.drugs.models import DrugSafetyProfile
from backend.app.drugs.safety_provider import DrugSafetyFetchResult
from backend.app.service import OncoService


def make_settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=100,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
        oncoai_drug_safety_enabled=True,
    )


def _dictionary_payload() -> dict[str, object]:
    return {
        "schema": "urn:onco:drug_dictionary_ru_inn:v1.2",
        "version": "test-1.0",
        "notes": "test bundle",
        "drug_dictionary": [
            {
                "inn": "capecitabine",
                "ru_names": ["капецитабин", "кселода"],
                "en_names": ["capecitabine"],
                "group": "antineoplastic",
            },
            {
                "inn": "warfarin",
                "ru_names": ["варфарин"],
                "en_names": ["warfarin"],
                "group": "anticoagulant",
            },
            {
                "inn": "ramucirumab",
                "ru_names": ["рамуцирумаб"],
                "en_names": ["ramucirumab"],
                "group": "antineoplastic",
            },
        ],
        "regimen_aliases": [
            {
                "regimen": "CAPOX",
                "aliases_ru": ["капокс"],
                "components_inn": ["capecitabine"],
                "notes": "test",
            }
        ],
        "synonyms_extra": {
            "ru_shortcuts": [
                {"pattern": r"\bкселода\b", "maps_to_inn": "capecitabine"},
            ]
        },
    }


def test_dictionary_loader_normalizes_payload() -> None:
    payload = _dictionary_payload()
    bundle = load_drug_dictionary_bundle_from_text(json.dumps(payload, ensure_ascii=False))
    assert bundle.version == "test-1.0"
    assert len(bundle.entries) == 3
    assert any(item.get("inn") == "capecitabine" for item in bundle.entries)
    assert any(item.get("regimen") == "CAPOX" for item in bundle.regimen_aliases)
    assert isinstance(bundle.synonyms_extra, dict)


def test_admin_drug_dictionary_load_and_cache_summary(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    content = json.dumps(_dictionary_payload(), ensure_ascii=False).encode("utf-8")

    result = service.admin_drug_dictionary_load(
        role="admin",
        payload={
            "filename": "drug_dictionary_ru_inn.v1.2.json",
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
    )
    assert result["status"] == "ok"
    assert int(result["entries_loaded"]) >= 3

    cache = service.admin_drug_safety_cache(role="admin", limit=50)
    summary = cache.get("summary", {})
    assert int(summary.get("dictionary_entries_total") or 0) >= 3
    assert "items" in cache


def test_drug_safety_build_produces_capecitabine_warfarin_signal(tmp_path: Path, monkeypatch) -> None:
    service = OncoService(make_settings(tmp_path))
    content = json.dumps(_dictionary_payload(), ensure_ascii=False).encode("utf-8")
    service.admin_drug_dictionary_load(
        role="admin",
        payload={
            "filename": "drug_dictionary_ru_inn.v1.2.json",
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
    )

    def _fake_get_profiles(inns: list[str]) -> DrugSafetyFetchResult:
        profiles: list[DrugSafetyProfile] = []
        if "capecitabine" in inns:
            profiles.append(
                DrugSafetyProfile(
                    inn="capecitabine",
                    source="test",
                    interactions_ru=["Капецитабин может усиливать эффект антикоагулянтов, включая варфарин."],
                )
            )
        return DrugSafetyFetchResult(status="ok", profiles=profiles, warnings=[])

    monkeypatch.setattr(service.drug_safety_provider, "get_profiles", _fake_get_profiles)
    drug_safety = service._build_drug_safety(
        case_text="Пациент получает капецитабин, дополнительно принимает варфарин ежедневно.",
        case_json=None,
    )

    assert drug_safety.status in {"ok", "partial"}
    assert any(item.inn == "capecitabine" for item in drug_safety.extracted_inn)
    assert any(item.inn == "warfarin" for item in drug_safety.extracted_inn)
    assert any(signal.kind == "contraindication" for signal in drug_safety.signals)
