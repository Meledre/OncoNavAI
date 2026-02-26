from __future__ import annotations

from backend.app.rules.sanity_checks import auto_repair_report, run_sanity_checks


def test_sanity_checks_fail_when_key_facts_missing() -> None:
    case_facts = {
        "initial_stage": {"tnm": "pT3N2M0", "stage_group": "III"},
        "metastases": [{"site": "печень"}],
        "treatment_history": [{"name": "рамуцирумаб + паклитаксел"}],
        "biomarkers": {"her2": "1+", "pd_l1_cps_values": [8.0], "msi_status": "MSS"},
    }
    doctor_report = {
        "case_facts": {},
        "consilium_md": "## Ключевые клинические факты\n- данных нет",
    }

    checks = run_sanity_checks(case_facts=case_facts, doctor_report=doctor_report)
    statuses = {item["check_id"]: item["status"] for item in checks}

    assert statuses["case_facts_stage_present"] == "fail"
    assert statuses["case_facts_metastases_present"] == "fail"
    assert statuses["case_facts_treatment_history_present"] == "fail"
    assert statuses["case_facts_biomarkers_present"] == "fail"


def test_auto_repair_restores_missing_case_facts_without_new_claims() -> None:
    case_facts = {
        "initial_stage": {"tnm": "pT3N2M0", "stage_group": "III"},
        "metastases": [{"site": "печень"}],
        "treatment_history": [{"name": "рамуцирумаб + паклитаксел"}],
        "biomarkers": {"her2": "1+", "pd_l1_cps_values": [8.0], "msi_status": "MSS"},
    }
    doctor_report = {
        "case_facts": {},
        "consilium_md": "## Ключевые клинические факты\n- исходно пусто",
    }

    repaired = auto_repair_report(case_facts=case_facts, doctor_report=doctor_report)

    assert repaired["case_facts"]["initial_stage"]["tnm"] == "pT3N2M0"
    assert repaired["case_facts"]["metastases"][0]["site"] == "печень"
    assert "pT3N2M0" in repaired["consilium_md"]
    assert "рамуцирумаб + паклитаксел" in repaired["consilium_md"]
