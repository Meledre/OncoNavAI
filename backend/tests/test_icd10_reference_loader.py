from __future__ import annotations

from backend.app.icd10.reference_loader import parse_icd10_reference_entries


def test_parse_icd10_reference_entries_extracts_codes_and_titles() -> None:
    text = """
    C15 Злокачественное новообразование пищевода
    C16 Злокачественное новообразование желудка
    C16.0 Кардиальный отдел желудка
    C49 Злокачественные новообразования мягких тканей
    """
    rows = parse_icd10_reference_entries(text)
    by_code = {item["code"]: item["title_ru"] for item in rows}

    assert by_code["C15"].startswith("Злокачественное")
    assert by_code["C16"].startswith("Злокачественное")
    assert "желудка" in by_code["C16"].lower()
    assert "кардиальный" in by_code["C16.0"].lower()
    assert "мягких тканей" in by_code["C49"].lower()
