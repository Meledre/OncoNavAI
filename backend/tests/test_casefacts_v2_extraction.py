from __future__ import annotations

from pathlib import Path

from backend.app.casefacts.extractor_v2 import extract_case_facts_v2
from backend.app.config import Settings
from backend.app.service import OncoService


SAMPLE_TEXT = """
Мужчина, 47 лет (1978 г.р.). Рост 178 см, вес 75 кг, ECOG 1.
Сопутствующие заболевания: ХБП 3 ст., сахарный диабет 2 типа.
Постоянная терапия: варфарин 5 мг/сут, бисопролол 5 мг утром.
Лаборатория 20.02.2026: креатинин 132 мкмоль/л, eGFR 48 мл/мин/1.73м2, Hb 104 г/л, тромбоциты 210 x10^9/л, INR 1.7.
Диагноз: аденокарцинома желудка, pT3N2M0, HER2 1+, PD-L1 CPS=8, MSS.
2 линия: рамуцирумаб + паклитаксел, затем прогрессирование.
""".strip()


def _iter_spans(node: object) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence_spans" and isinstance(value, list):
                spans.extend(item for item in value if isinstance(item, dict))
            else:
                spans.extend(_iter_spans(value))
    elif isinstance(node, list):
        for item in node:
            spans.extend(_iter_spans(item))
    return spans


def _settings(root: Path) -> Settings:
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
        reasoning_mode="compat",
    )


def test_extract_case_facts_v2_patient_labs_meds_and_evidence_bounds() -> None:
    facts = extract_case_facts_v2(case_text=SAMPLE_TEXT, case_json=None).model_dump()

    patient = facts["patient"]
    assert patient["sex"] == "male"
    assert patient["age"] == 47
    assert patient["birth_year"] == 1978
    assert patient["height_cm"] == 178.0
    assert patient["weight_kg"] == 75.0
    assert patient["ecog"] == 1
    assert patient["bsa_m2"] is not None
    assert round(float(patient["bsa_m2"]), 2) == 1.93

    labs = facts["labs"]
    names = {str(item.get("name") or "").lower() for item in labs if isinstance(item, dict)}
    assert "creatinine" in names
    assert "egfr" in names
    assert "inr" in names

    meds = facts["current_medications"]
    med_names = {str(item.get("name") or "").lower() for item in meds if isinstance(item, dict)}
    assert "варфарин" in med_names
    assert "бисопролол" in med_names
    assert isinstance(facts.get("normalized_medications"), list)
    assert isinstance(facts.get("unresolved_medication_candidates"), list)

    comorbidity_names = {str(item.get("name") or "").lower() for item in facts["comorbidities"]}
    assert "хбп" in comorbidity_names
    assert "сахарный диабет" in comorbidity_names

    spans = _iter_spans(facts)
    assert spans
    assert all(int(item.get("char_start") or 0) >= 0 for item in spans)
    assert all(int(item.get("char_end") or 0) <= len(SAMPLE_TEXT) for item in spans)


def test_service_analyze_includes_casefacts_v2(tmp_path: Path) -> None:
    service = OncoService(_settings(tmp_path))

    payload = {
        "schema_version": "0.2",
        "request_id": "casefacts-v2-service-smoke",
        "query_type": "NEXT_STEPS",
        "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
        "language": "ru",
        "case": {
            "case_json": {
                "schema_version": "1.0",
                "case_id": "4cf73b7d-66ad-4d8d-8850-1e4598afebc5",
                "import_profile": "FREE_TEXT",
                "patient": {"sex": "male"},
                "diagnoses": [
                    {
                        "diagnosis_id": "d7b7c2b0-eef7-437e-8453-ad1938f6769e",
                        "disease_id": "a76e5701-e3b1-54fd-a4b8-001bcd63de6e",
                        "icd10": "C16",
                        "stage": {"system": "TNM8", "stage_group": "III"},
                        "biomarkers": [],
                        "timeline": [],
                    }
                ],
                "attachments": [],
                "notes": SAMPLE_TEXT,
            }
        },
        "options": {"strict_evidence": True, "max_chunks": 20, "max_citations": 20, "timeout_ms": 120000},
    }

    response = service.analyze(payload=payload, role="clinician", client_id="casefacts-v2")
    case_facts = response["doctor_report"]["case_facts"]
    assert "case_facts_v2" in case_facts
    v2 = case_facts["case_facts_v2"]
    assert v2["patient"]["height_cm"] == 178.0
    assert v2["patient"]["weight_kg"] == 75.0
    assert any(str(item.get("name") or "").lower() == "egfr" for item in v2.get("labs", []))
    normalized_inn = {str(item.get("inn") or "").lower() for item in v2.get("normalized_medications", [])}
    assert "ramucirumab" in normalized_inn
