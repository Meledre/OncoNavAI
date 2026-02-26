from __future__ import annotations

from backend.app.clinical_calcs import cockcroft_gault_crcl_ml_min, mosteller_bsa_m2, umol_l_to_mg_dl


def test_mosteller_bsa_m2() -> None:
    bsa = mosteller_bsa_m2(height_cm=178.0, weight_kg=75.0)
    assert bsa is not None
    assert round(float(bsa), 2) == 1.93


def test_cockcroft_gault_crcl_ml_min() -> None:
    crcl = cockcroft_gault_crcl_ml_min(
        age=47,
        weight_kg=75.0,
        serum_creatinine_mg_dl=umol_l_to_mg_dl(132.0),
        sex="male",
    )
    assert crcl is not None
    assert 40.0 <= float(crcl) <= 90.0


def test_umol_to_mg_dl_conversion() -> None:
    assert round(float(umol_l_to_mg_dl(88.4)), 2) == 1.0
