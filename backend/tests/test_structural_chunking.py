from __future__ import annotations

from pathlib import Path

from backend.app.rag.ingest_pdf import extract_pdf_chunks


def _metadata() -> dict[str, str]:
    return {
        "doc_id": "guideline_gastric",
        "doc_version": "2025-1-1-13",
        "source_set": "russco",
        "cancer_type": "gastric_cancer",
        "language": "ru",
        "source_url": "https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
    }


def test_structural_chunk_has_metadata_fields(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def fake_pages(_: Path):
        return [
            {"page_index": 0, "page_label": "1", "text": "1. Диагностика\nКраткий раздел с рекомендациями."},
            {"page_index": 1, "page_label": "2", "text": "2. Лечение\nТаблица режимов второй линии."},
        ]

    from backend.app.rag import ingest_pdf

    monkeypatch.setattr(ingest_pdf, "_extract_pages_advanced", fake_pages)
    chunks = extract_pdf_chunks(pdf, metadata=_metadata())

    assert chunks
    first = chunks[0]
    assert isinstance(first["section_path"], list)
    assert isinstance(first["page_start"], int)
    assert isinstance(first["page_end"], int)
    assert isinstance(first["token_count"], int)
    assert isinstance(first["source_url"], str)
    assert isinstance(first["content_hash"], str)


def test_structural_chunk_id_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def fake_pages(_: Path):
        return [{"page_index": 0, "page_label": "1", "text": "Раздел A\nНекоторый текст."}]

    from backend.app.rag import ingest_pdf

    monkeypatch.setattr(ingest_pdf, "_extract_pages_advanced", fake_pages)
    chunks1 = extract_pdf_chunks(pdf, metadata=_metadata())
    chunks2 = extract_pdf_chunks(pdf, metadata=_metadata())

    assert chunks1[0]["chunk_id"] == chunks2[0]["chunk_id"]


def test_structural_chunker_flag_false_uses_legacy_section_path(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def fake_pages(_: Path):
        return [
            {
                "page_index": 0,
                "page_label": "1",
                "text": "1. Заголовок\n" + ("Текст раздела. " * 400),
            }
        ]

    from backend.app.rag import ingest_pdf

    monkeypatch.setattr(ingest_pdf, "_extract_pages_advanced", fake_pages)
    chunks = extract_pdf_chunks(pdf, metadata=_metadata(), structural_chunker_enabled=False)

    assert chunks
    assert all(chunk["section_path"] == ["Guideline fragment"] for chunk in chunks)
    assert all(chunk["section_title"] == "Guideline fragment" for chunk in chunks)
