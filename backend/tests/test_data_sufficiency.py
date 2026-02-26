from __future__ import annotations

from backend.app.rules.data_sufficiency import evaluate_data_sufficiency


def test_data_sufficiency_marks_missing_predictive_markers_for_next_steps() -> None:
    result = evaluate_data_sufficiency(
        case_facts={
            "initial_stage": {"tnm": "cT3N1M1"},
            "metastases": [{"site": "печень"}],
            "biomarkers": {"her2": "", "pd_l1_cps_values": [], "msi_status": "unknown"},
        },
        query_type="NEXT_STEPS",
        case_text="Метастатический рак желудка.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Смена линии системной терапии"}]}],
    )
    assert result["status"] is True
    assert "HER2" in result["missing_critical_fields"]
    assert "PD-L1 CPS" in result["missing_critical_fields"]
    assert "MSI/dMMR" in result["missing_critical_fields"]


def test_data_sufficiency_requires_renal_labs_before_cisplatin() -> None:
    result = evaluate_data_sufficiency(
        case_facts={
            "initial_stage": {"tnm": "cT3N1M1"},
            "metastases": [{"site": "печень"}],
            "biomarkers": {"her2": "3+", "pd_l1_cps_values": [10.0], "msi_status": "MSS"},
        },
        query_type="NEXT_STEPS",
        case_text="В плане цисплатин. Лабораторные данные не представлены.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Назначить cisplatin + fluoropyrimidine"}]}],
    )
    assert result["status"] is True
    assert "creatinine" in result["missing_critical_fields"]
    assert "eGFR" in result["missing_critical_fields"]


def test_data_sufficiency_detects_explicit_missing_her2_signal() -> None:
    result = evaluate_data_sufficiency(
        case_facts={
            "initial_stage": {"tnm": "cT3N1M1"},
            "metastases": [{"site": "печень"}],
            "biomarkers": {"her2": "", "pd_l1_cps_values": [5.0], "msi_status": "MSS"},
        },
        query_type="NEXT_STEPS",
        case_text="Отсутствие данных о HER2-статусе перед выбором первой линии.",
        plan_sections=[{"section": "diagnostics", "steps": [{"text": "Определить HER2 IHC/ISH"}]}],
    )
    assert result["status"] is True
    assert "HER2" in result["missing_critical_fields"]


def test_data_sufficiency_detects_missing_support_assessment_for_elderly_capecitabine() -> None:
    result = evaluate_data_sufficiency(
        case_facts={
            "initial_stage": {"tnm": "pT3N2M0"},
            "metastases": [],
            "biomarkers": {"her2": "negative", "pd_l1_cps_values": [], "msi_status": "MSS"},
        },
        query_type="NEXT_STEPS",
        case_text=(
            "Планируется адъювантный капецитабин у пожилой пациентки, проживающей одной. "
            "Оценка когнитивного статуса и социальной поддержки не проводилась."
        ),
        plan_sections=[{"section": "treatment", "steps": [{"text": "Адъювантная терапия капецитабином"}]}],
    )
    assert result["status"] is True
    assert "cognitive_assessment" in result["missing_critical_fields"]
    assert "social_support" in result["missing_critical_fields"]


def test_data_sufficiency_trusts_minimum_dataset_when_marked_complete() -> None:
    result = evaluate_data_sufficiency(
        case_facts={
            "minimum_dataset": {
                "status": False,
                "missing_critical_fields": [],
                "missing_optional_fields": [],
                "reason": "Минимальный набор заполнен.",
            }
        },
        query_type="NEXT_STEPS",
        case_text="",
        plan_sections=[],
    )
    assert result["status"] is False
    assert result["missing_critical_fields"] == []
