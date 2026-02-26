from __future__ import annotations

import pytest

from backend.app.guidelines.sync_minzdrav import (
    KNOWN_MINZDRAV_PDFS,
    MinzdravDocument,
    download_minzdrav_pdf,
    extract_download_url_from_html,
    resolve_minzdrav_pdf_from_page,
)


def test_minzdrav_known_pdf_catalog_has_required_fields() -> None:
    assert KNOWN_MINZDRAV_PDFS
    first = KNOWN_MINZDRAV_PDFS[0]
    assert first.doc_id
    assert first.doc_version
    assert first.filename.endswith(".pdf")
    assert first.source_url.startswith("http")
    assert first.source_set == "minzdrav"
    assert first.language == "ru"


def test_minzdrav_catalog_contains_egj_profile() -> None:
    assert any(
        item.cancer_type == "esophagogastric_junction_cancer"
        for item in KNOWN_MINZDRAV_PDFS
    )


def test_minzdrav_catalog_contains_237_6_profile() -> None:
    assert any(item.doc_id == "minzdrav_237_6" for item in KNOWN_MINZDRAV_PDFS)


def test_download_minzdrav_pdf_accepts_pdf_payload() -> None:
    doc = MinzdravDocument(
        doc_id="minzdrav_test",
        doc_version="1.0",
        source_page_url="https://cr.minzdrav.gov.ru/preview-cr/1_0",
        filename="test.pdf",
    )
    payload = download_minzdrav_pdf(doc, fetch_bytes=lambda _url: b"%PDF-1.4 test")
    assert payload.startswith(b"%PDF-1.4")


def test_download_minzdrav_pdf_rejects_non_pdf_content() -> None:
    doc = MinzdravDocument(
        doc_id="minzdrav_test_html",
        doc_version="1.0",
        source_page_url="https://cr.minzdrav.gov.ru/preview-cr/1_0",
        filename="test.pdf",
    )
    with pytest.raises(ValueError, match="MINZDRAV_NON_PDF_CONTENT"):
        download_minzdrav_pdf(doc, fetch_bytes=lambda _url: b"<html>not pdf</html>")


def test_extract_download_url_from_html_supports_common_button_patterns() -> None:
    html = """
    <html><body>
      <a class="btn" href="/upload/iblock/aa1/file.pdf">Скачать</a>
      <button data-download-url="/upload/iblock/aa1/file.pdf">Скачать</button>
      <button onclick="window.location='/upload/iblock/aa1/file.pdf'">Скачать</button>
    </body></html>
    """
    resolved = extract_download_url_from_html(
        html=html,
        base_url="https://cr.minzdrav.gov.ru/preview-cr/237_6",
    )
    assert resolved == "https://cr.minzdrav.gov.ru/upload/iblock/aa1/file.pdf"


def test_resolve_minzdrav_pdf_from_page_uses_download_button() -> None:
    doc = MinzdravDocument(
        doc_id="minzdrav_button",
        doc_version="1.0",
        source_page_url="https://cr.minzdrav.gov.ru/preview-cr/237_6",
        source_pdf_url="",
        filename="test.pdf",
    )
    html = """
    <html><body>
      <button class="download" data-url="/upload/iblock/ff2/clinical.pdf">Скачать PDF</button>
    </body></html>
    """
    resolved = resolve_minzdrav_pdf_from_page(doc, fetch_text=lambda _url: html)
    assert resolved == "https://cr.minzdrav.gov.ru/upload/iblock/ff2/clinical.pdf"


def test_download_minzdrav_pdf_falls_back_to_known_pdf_url() -> None:
    doc = MinzdravDocument(
        doc_id="minzdrav_pdf_fallback",
        doc_version="1.0",
        source_page_url="https://cr.minzdrav.gov.ru/preview-cr/does-not-open",
        source_pdf_url="https://static.edu.rosminzdrav.ru/path/to/valid.pdf",
        filename="valid.pdf",
    )

    def fake_fetch(url: str) -> bytes:
        if "valid.pdf" in url:
            return b"%PDF-1.4 valid payload"
        raise RuntimeError("network issue")

    payload = download_minzdrav_pdf(
        doc,
        fetch_bytes=fake_fetch,
        fetch_text=lambda _url: "<html><body>broken page</body></html>",
    )
    assert payload.startswith(b"%PDF-1.4")
