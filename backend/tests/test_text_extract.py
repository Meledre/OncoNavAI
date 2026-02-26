from __future__ import annotations

import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest

from backend.app.exceptions import ValidationError
from backend.app.importers import text_extract


def test_extract_text_from_txt_payload_returns_expected_metadata() -> None:
    payload = "Пациент C16. Стадия IV.\nЛиния 1 XELOX.".encode("utf-8")
    result = text_extract.extract_text(payload, filename="case.txt", mime="text/plain")

    assert "Пациент C16" in result["text"]
    assert result["pages_count"] == 1
    assert result["page_map"] == {"1": [0, len(result["text"])]}
    assert result["sha256"] == f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_extract_text_from_pdf_uses_pdf_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_extract_pdf(_: bytes) -> tuple[str, int, dict[str, list[int]]]:
        return "PDF extracted text", 2, {"1": [0, 8], "2": [9, 17]}

    monkeypatch.setattr(text_extract, "_extract_pdf_text", fake_extract_pdf)
    result = text_extract.extract_text(b"%PDF-synthetic", filename="case.pdf", mime="application/pdf")
    assert result["text"] == "PDF extracted text"
    assert result["pages_count"] == 2
    assert result["page_map"] == {"1": [0, 8], "2": [9, 17]}


def test_extract_text_from_docx_uses_docx_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_extract_docx(_: bytes) -> tuple[str, int, dict[str, list[int]]]:
        return "DOCX extracted text", 1, {"1": [0, 19]}

    monkeypatch.setattr(text_extract, "_extract_docx_text", fake_extract_docx)
    result = text_extract.extract_text(b"docx-bytes", filename="case.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert result["text"] == "DOCX extracted text"
    assert result["pages_count"] == 1
    assert result["page_map"] == {"1": [0, 19]}


def test_extract_docx_text_reads_table_cells_from_xml() -> None:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Креатинин 78</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc>
          <w:p><w:r><w:t>ERBB2</w:t></w:r></w:p>
        </w:tc>
        <w:tc>
          <w:p><w:r><w:t>PD-L1 (CPS): 8</w:t></w:r></w:p>
        </w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
    payload_buffer = BytesIO()
    with ZipFile(payload_buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml.encode("utf-8"))
    payload = payload_buffer.getvalue()

    result = text_extract.extract_text(
        payload,
        filename="case.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert "Креатинин 78" in result["text"]
    assert "ERBB2" in result["text"]
    assert "PD-L1 (CPS): 8" in result["text"]


def test_extract_text_reports_low_text_volume_warning_for_short_docx() -> None:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>Коротко</w:t></w:r></w:p></w:body>
</w:document>
"""
    payload_buffer = BytesIO()
    with ZipFile(payload_buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml.encode("utf-8"))
    payload = payload_buffer.getvalue()

    result = text_extract.extract_text(
        payload,
        filename="short.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    warning_codes = {item["code"] for item in result.get("warnings", [])}
    assert "LOW_TEXT_VOLUME" in warning_codes


def test_extract_text_rejects_unsupported_extension() -> None:
    with pytest.raises(ValidationError, match="Unsupported file type"):
        text_extract.extract_text(b"{}", filename="case.json", mime="application/json")
