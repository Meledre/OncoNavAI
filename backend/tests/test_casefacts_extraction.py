from __future__ import annotations

from backend.app.casefacts.extractor import extract_case_facts


N5_TEXT = """
Пациент с диагнозом аденокарцинома ПЖП.
Стадия pT3N2M0 (III стадия).
2 линия: рамуцирумаб + паклитаксел 12.2024-09.2025, прогрессирование 10.2025.
Биомаркеры: HER2/neu IHC 1+, PD-L1 (CPS): 8 (2024), PD-L1 CPS=3 (2025), MSS, CLDN18.2 75%.
Осложнения: тромбоз воротной вены, портальная гипертензия, асцит.
"""


def test_extract_case_facts_n5_core_signals() -> None:
    facts = extract_case_facts(case_text=N5_TEXT, case_json=None)
    payload = facts.model_dump()

    assert payload["initial_stage"]["tnm"] == "pT3N2M0"
    assert payload["initial_stage"]["stage_group"] == "III"
    assert payload["current_stage"]["tnm"] == "pT3N2M0"
    assert payload["biomarkers"]["her2"] == "1+"
    assert payload["biomarkers"]["her2_interpretation"] == "negative"
    assert payload["biomarkers"]["msi_status"] == "MSS"
    assert payload["biomarkers"]["pd_l1_cps_values"] == [8.0, 3.0]
    assert payload["biomarkers"]["cldn18_2_percent"] == 75.0
    assert payload["biomarkers"]["cldn18_2_interpretation"] == "positive"

    history = payload["treatment_history"]
    assert history
    assert any("рамуцирумаб" in item["name"].lower() for item in history)
    assert any(item.get("response") == "progression" for item in history)

    assert "тромбоз воротной вены" in payload["complications"]
    assert "портальная гипертензия" in payload["complications"]
    assert "асцит" in payload["complications"]


def test_extract_case_facts_empty_text_returns_unknowns() -> None:
    facts = extract_case_facts(case_text="   ", case_json=None)
    payload = facts.model_dump()

    assert payload["key_unknowns"]
    assert "tnm_stage" in payload["key_unknowns"]
    assert "treatment_history" in payload["key_unknowns"]
    assert "biomarkers" in payload["key_unknowns"]


def test_extract_case_facts_supports_erbb2_alias_and_pdl1_parentheses() -> None:
    text = "ERBB2 IHC: 3+. PD-L1 (CPS): 4. dMMR."
    facts = extract_case_facts(case_text=text, case_json=None).model_dump()
    assert facts["biomarkers"]["her2"] == "3+"
    assert facts["biomarkers"]["her2_interpretation"] == "positive"
    assert facts["biomarkers"]["pd_l1_cps_values"] == [4.0]
    assert facts["biomarkers"]["msi_status"] == "dMMR"


def test_extract_case_facts_metastases_respect_negation() -> None:
    text = "Метастазы не выявлены в печени. Очаг в печени без признаков мтс."
    facts = extract_case_facts(case_text=text, case_json=None).model_dump()
    assert facts["metastases"] == []


def test_extract_case_facts_parses_line_based_therapy_history() -> None:
    text = (
        "ПХТ 1 линии (паклитаксел+карбоплатин) с 09.2021 по 03.2022. "
        "Прогрессирование от 16.03.2022. "
        "ХТ 2 линии эрибулином с 03.2022 по 08.2022."
    )
    facts = extract_case_facts(case_text=text, case_json=None).model_dump()
    history = facts["treatment_history"]

    assert len(history) >= 2
    names = [str(item.get("name") or "").lower() for item in history]
    assert any("паклитаксел" in name and "карбоплатин" in name for name in names)
    assert any("эрибулин" in name for name in names)
    assert any(item.get("start") == "09.2021" and item.get("end") == "03.2022" for item in history)
    assert any(item.get("response") == "progression" for item in history)
