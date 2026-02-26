from __future__ import annotations

from backend.app.reporting.timeline_reconciler import reconcile_timeline_signals


def test_timeline_reconciler_parses_stage_group_from_short_form() -> None:
    result = reconcile_timeline_signals(
        case_text=(
            "Диагноз: рак пищеводно-желудочного перехода III ст., pT3N2M0. "
            "Периоперационная XELOX. Затем рамуцирумаб + паклитаксел и прогрессирование."
        ),
        case_facts={
            "initial_stage": {"tnm": "pT3N2M0"},
            "biomarkers": {"her2": "1+", "pd_l1_cps_values": [8.0, 3.0], "msi_status": "MSS"},
            "treatment_history": [{"name": "рамуцирумаб + паклитаксел", "response": "progression"}],
            "metastases": [],
            "complications": [],
        },
    )
    text = "\n".join(result.get("facts_lines") or [])
    assert "стадия III" in text
    assert "cT3N2M0" in text
    assert "pT3N2M0" in text


def test_timeline_reconciler_infers_clinical_tnm_from_pathological_when_missing() -> None:
    result = reconcile_timeline_signals(
        case_text="ПЖП, стадия III, pT3N2M0. XELOX. рамуцирумаб + паклитаксел, прогрессирование.",
        case_facts={
            "initial_stage": {"tnm": "pT3N2M0"},
            "biomarkers": {},
            "treatment_history": [{"name": "ramucirumab + paclitaxel", "response": "progression"}],
            "metastases": [],
            "complications": [],
        },
    )
    text = "\n".join(result.get("facts_lines") or [])
    assert "cT3N2M0" in text


def test_timeline_reconciler_keeps_signals_for_non_n5_profile() -> None:
    result = reconcile_timeline_signals(
        case_text=(
            "Аденокарцинома желудка, стадия III, pT3N1M0. "
            "Проведена периоперационная XELOX."
        ),
        case_facts={
            "initial_stage": {"tnm": "pT3N1M0"},
            "biomarkers": {},
            "treatment_history": [],
            "metastases": [],
            "complications": [],
        },
    )
    assert result.get("n5_profile") is False
    facts_lines = result.get("facts_lines") or []
    missing = result.get("missing_items") or []
    assert any("Исходное стадирование" in str(line) for line in facts_lines)
    assert any("XELOX/CAPOX" in str(line) for line in facts_lines)
    assert any("рамуцирумаба + паклитаксела" in str(item) for item in missing)


def test_timeline_reconciler_detects_postop_capecitabine_without_explicit_adjuvant_word() -> None:
    result = reconcile_timeline_signals(
        case_text=(
            "Хирургическое лечение от 07.08.2023: операция типа Льюиса в объеме R1. "
            "3 курса ХТ 1 линии, капецитабин до 22.11.2023. "
            "Затем прогрессирование на фоне 2-й линии."
        ),
        case_facts={
            "initial_stage": {"tnm": "pT3N2M0"},
            "biomarkers": {},
            "treatment_history": [{"name": "рамуцирумаб + паклитаксел", "response": "progression"}],
            "metastases": [],
            "complications": [],
        },
    )
    facts_lines = result.get("facts_lines") or []
    missing = result.get("missing_items") or []
    assert any("капецитабин" in str(line).lower() for line in facts_lines)
    assert not any("адъювантной терапии капецитабином" in str(item).lower() for item in missing)


def test_timeline_reconciler_reports_missing_d2_specifically() -> None:
    result = reconcile_timeline_signals(
        case_text=(
            "Хирургическое лечение: операция типа Льюиса, R1. "
            "Периоперационная XELOX и прогрессирование после рамуцирумаб + паклитаксел."
        ),
        case_facts={
            "initial_stage": {"tnm": "pT3N2M0"},
            "biomarkers": {},
            "treatment_history": [{"name": "рамуцирумаб + паклитаксел", "response": "progression"}],
            "metastases": [],
            "complications": [],
        },
    )
    facts_lines = result.get("facts_lines") or []
    missing = result.get("missing_items") or []
    assert any("R1/Льюис" in str(line) for line in facts_lines)
    assert any("лимфодиссекции D2" in str(item) for item in missing)
