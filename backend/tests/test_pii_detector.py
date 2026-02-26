from __future__ import annotations

from backend.app.security.pii_detector import contains_pii, find_pii, redact_pii


def test_find_pii_detects_email_and_phone():
    matches = find_pii("contact me: a.b@example.com +1 (415) 555-7788")
    kinds = {item.kind for item in matches}
    assert "email" in kinds
    assert "phone" in kinds


def test_contains_pii_false_on_synthetic_case():
    assert not contains_pii(["Синтетический обезличенный кейс", "План терапии"])


def test_find_pii_does_not_treat_dates_as_phone_numbers():
    text = "Дата визита: 2026-01-05, предыдущий курс 2025-12-01"
    assert not contains_pii([text])


def test_redact_pii_masks_detected_fragments():
    text = "Пациент Иван Иванов, email a.b@example.com, телефон +7 (999) 123-45-67."
    redacted = redact_pii(text)
    assert "[REDACTED_NAME]" in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
