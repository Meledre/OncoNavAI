from __future__ import annotations

from pathlib import Path

from backend.app.rag import ingest_pdf


def _metadata() -> dict[str, str]:
    return {
        "doc_id": "guideline_nsclc",
        "doc_version": "2025-11",
        "source_set": "mvp_guidelines_ru_2025",
        "cancer_type": "nsclc_egfr",
        "language": "ru",
    }


def test_extract_pdf_chunks_fallback_contains_page_metadata(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic text block for deterministic extraction")

    chunks = ingest_pdf.extract_pdf_chunks(pdf, metadata=_metadata())

    assert chunks
    first = chunks[0]
    assert first["doc_id"] == "guideline_nsclc"
    assert first["doc_version"] == "2025-11"
    assert isinstance(first["pdf_page_index"], int)
    assert isinstance(first["page_label"], str)
    assert first["section_title"]
    assert isinstance(first["section_path"], list)
    assert isinstance(first["page_start"], int)
    assert isinstance(first["page_end"], int)
    assert isinstance(first["token_count"], int)
    assert isinstance(first["content_hash"], str)


def test_extract_pdf_chunks_uses_advanced_pages_when_available(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def fake_pages(_: Path):
        return [
            {"page_index": 0, "page_label": "i", "text": "Section A osimertinib guidance"},
            {"page_index": 1, "page_label": "1", "text": "Section B diagnostic confirmation"},
        ]

    monkeypatch.setattr(ingest_pdf, "_extract_pages_advanced", fake_pages)

    chunks = ingest_pdf.extract_pdf_chunks(pdf, metadata=_metadata())
    assert chunks

    page0 = [chunk for chunk in chunks if chunk["pdf_page_index"] == 0]
    page1 = [chunk for chunk in chunks if chunk["pdf_page_index"] == 1]
    assert page0 and page1
    assert all(chunk["page_label"] == "i" for chunk in page0)
    assert all(chunk["page_label"] == "1" for chunk in page1)
