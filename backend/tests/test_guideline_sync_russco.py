from __future__ import annotations

from backend.app.guidelines.sync_russco import (
    RUSSCO_2025_INDEX_URL,
    discover_russco_2025_documents,
    download_russco_pdf,
    parse_russco_index_html,
)


def test_parse_russco_index_html_extracts_unique_pdf_urls() -> None:
    html = """
    <html><body>
      <a href="2025-1-1-13.pdf">A</a>
      <a href="/standarts/RUSSCO/2025/2025-1-1-12.pdf">B</a>
      <a href="2025-1-1-13.pdf">dup</a>
    </body></html>
    """
    urls = parse_russco_index_html(html, base_url=RUSSCO_2025_INDEX_URL)
    assert len(urls) == 2
    assert urls[0].endswith("2025-1-1-13.pdf")
    assert urls[1].endswith("2025-1-1-12.pdf")


def test_discover_russco_2025_documents_builds_doc_metadata() -> None:
    html = """
    <a href="2025-1-1-13.pdf">guideline-13</a>
    <a href="2025-1-1-12.pdf">guideline-12</a>
    <a href="2025-2-4.pdf">supportive</a>
    <a href="2025-9-9-9.pdf">other</a>
    """

    docs = discover_russco_2025_documents(fetch_text=lambda _url: html)
    assert len(docs) == 4
    assert {doc.doc_id for doc in docs} >= {"russco_2025_1_1_13", "russco_2025_1_1_12"}
    by_id = {doc.doc_id: doc for doc in docs}
    assert by_id["russco_2025_1_1_13"].cancer_type == "gastric_cancer"
    assert by_id["russco_2025_1_1_12"].cancer_type == "esophagogastric_junction_cancer"
    assert by_id["russco_2025_2_4"].cancer_type == "supportive_care"
    assert by_id["russco_2025_9_9_9"].cancer_type == "unknown"
    assert all(doc.doc_version == "2025" for doc in docs)


def test_download_russco_pdf_uses_custom_fetcher() -> None:
    payload = download_russco_pdf("https://example.org/file.pdf", fetch_bytes=lambda _url: b"PDF")
    assert payload == b"PDF"
