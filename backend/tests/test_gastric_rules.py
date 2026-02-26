from __future__ import annotations

from backend.app.rules.gastric_rules import apply_gastric_rules


def test_gastric_rules_flag_missing_trastuzumab_for_her2_positive_first_line() -> None:
    issues = apply_gastric_rules(
        case_facts={
            "metastases": [{"site": "печень"}],
            "biomarkers": {"her2_interpretation": "positive"},
        },
        disease_context={"setting": "metastatic", "line": 1},
        case_text="Метастатический HER2 positive рак желудка.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "FOLFOX в 1-й линии"}]}],
    )
    assert any(item["kind"] == "deviation" for item in issues)


def test_gastric_rules_flag_high_inr_before_biopsy() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {}},
        disease_context={"setting": "metastatic", "line": 2},
        case_text="МНО 1.8, планируется биопсия.",
        plan_sections=[{"section": "diagnostics", "steps": [{"text": "Провести биопсию очага"}]}],
    )
    assert any(item["kind"] == "contraindication" for item in issues)


def test_gastric_rules_flag_immunotherapy_risk_with_active_autoimmune_disease() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {"pd_l1_cps_values": [15.0], "msi_status": "MSI-H"}},
        disease_context={"setting": "metastatic", "line": 2},
        case_text="Активный ревматоидный артрит (DAS28 4.2), план пембролизумаб.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Назначить pembrolizumab monotherapy"}]}],
    )
    assert any(item["kind"] == "contraindication" for item in issues)


def test_gastric_rules_flag_hbv_reactivation_risk_without_antiviral_prophylaxis() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {}},
        disease_context={"setting": "locally_advanced", "line": 1},
        case_text="HBsAg+, HBV DNA 3500 МЕ/мл, запланирован FLOT без энтекавира/тенофовира.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Неоадъювантный FLOT"}]}],
    )
    assert any(item["kind"] == "contraindication" for item in issues)


def test_gastric_rules_flag_methotrexate_with_ckd_risk_signal() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {}},
        disease_context={"setting": "metastatic", "line": 3},
        case_text=(
            "Ошибка: назначение высокодозного метотрексата пациентке с ХБП 3Б, "
            "рСКФ 38 мл/мин и гиперкалиемией."
        ),
        plan_sections=[{"section": "supportive", "steps": [{"text": "Контроль симптомов"}]}],
    )
    assert any(item["summary"].startswith("Высокодозный метотрексат") for item in issues)


def test_gastric_rules_flag_text_level_her2_positive_without_trastuzumab_in_plan() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {"her2_interpretation": "unknown"}},
        disease_context={"setting": "metastatic", "line": 1},
        case_text="Ошибка: HER2 positive (FISH+) метастатический рак желудка без анти-HER2 компонента.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Провести системную химиотерапию XELOX"}]}],
    )
    assert any(item["kind"] == "deviation" for item in issues)


def test_gastric_rules_add_generic_inconsistency_when_error_signal_present() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {}},
        disease_context={"setting": "metastatic", "line": 2},
        case_text="Выявлена клиническая ошибка: несоответствие стандартам лечения.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Провести системную терапию"}]}],
    )
    assert any(item["kind"] == "inconsistency" for item in issues)


def test_gastric_rules_flag_anticoagulant_risk_with_ramucirumab() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {}},
        disease_context={"setting": "metastatic", "line": 2},
        case_text="Пациент принимает варфарин, INR 1.9. План: ramucirumab + paclitaxel.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Ramucirumab + paclitaxel"}]}],
    )
    assert any("антикоагулянт" in str(item.get("summary") or "").lower() for item in issues)


def test_gastric_rules_flag_capecitabine_with_warfarin_interaction() -> None:
    issues = apply_gastric_rules(
        case_facts={"biomarkers": {}},
        disease_context={"setting": "metastatic", "line": 2},
        case_text="Постоянно принимает варфарин 5 мг/сут.",
        plan_sections=[{"section": "treatment", "steps": [{"text": "Адъювантный капецитабин"}]}],
    )
    assert any("капецитабин" in str(item.get("summary") or "").lower() for item in issues)
