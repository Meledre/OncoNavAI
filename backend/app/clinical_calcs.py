from __future__ import annotations

import math


def mosteller_bsa_m2(*, height_cm: float | int | None, weight_kg: float | int | None) -> float | None:
    if height_cm is None or weight_kg is None:
        return None
    try:
        height = float(height_cm)
        weight = float(weight_kg)
    except (TypeError, ValueError):
        return None
    if height <= 0 or weight <= 0:
        return None
    return math.sqrt((height * weight) / 3600.0)


def umol_l_to_mg_dl(value_umol_l: float | int | None) -> float:
    if value_umol_l is None:
        return 0.0
    return float(value_umol_l) / 88.4


def cockcroft_gault_crcl_ml_min(
    *,
    age: int | None,
    weight_kg: float | int | None,
    serum_creatinine_mg_dl: float | int | None,
    sex: str | None,
) -> float | None:
    if age is None or weight_kg is None or serum_creatinine_mg_dl is None:
        return None
    try:
        age_value = int(age)
        weight_value = float(weight_kg)
        creatinine_value = float(serum_creatinine_mg_dl)
    except (TypeError, ValueError):
        return None

    if age_value <= 0 or weight_value <= 0 or creatinine_value <= 0:
        return None

    base = ((140.0 - float(age_value)) * weight_value) / (72.0 * creatinine_value)
    normalized_sex = str(sex or "").strip().lower()
    if normalized_sex in {"female", "f", "жен", "ж"}:
        base *= 0.85
    return base
