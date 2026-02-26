from __future__ import annotations

from backend.app.rules.ru_text_normalizer import normalize_ru_clinical_text


def test_ru_normalizer_translates_known_english_fallbacks() -> None:
    text = normalize_ru_clinical_text(
        "No critical mismatch detected. The current plan appears broadly aligned with available guideline fragments."
    )
    assert "No critical mismatch detected" not in text
    assert "The current plan appears broadly aligned with available guideline fragments." not in text
    assert "Критических расхождений не выявлено" in text


def test_ru_normalizer_rewrites_post_progression_to_russian() -> None:
    text = normalize_ru_clinical_text("Неполная клиническая последовательность для post-progression кейса.")
    assert "post-progression" not in text
    assert "после прогрессирования" in text

